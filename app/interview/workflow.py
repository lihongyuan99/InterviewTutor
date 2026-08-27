"""单题训练闭环状态机。

显式管理出题、等待回答、评分、追问、讲解与完成状态（Handoff §9），
不使用 LLM 猜测状态迁移。关键防泄露约束：

- 出题阶段只向 Interviewer 提供题目与维度，不传专家答案。
- 用户提交作答后，才向 Evaluator 提供标准答案、考察点与差距分析。

流程：
    start → asking → awaiting_answer → evaluating → probing/reviewing → completed
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm_factory import create_chat_model, message_text
from app.interview import prompts
from app.interview.models import (
    AnswerRequest,
    EvaluationResult,
    InterviewSession,
    StartRequest,
)
from app.core import memory
from app.interview.progress import GoalProgressStore, ProgressStore, list_all_goal_progress
from app.interview.report_store import get_report, list_reports, save_report
from app.interview.session_store import delete_session, load_session, save_session
from app.interview.models import InterviewQuestionResult, InterviewReport


def _pick_question(
    dimensions: List[str],
    companies: List[str],
    difficulty: int,
    exclude_ids: Optional[set] = None,
    exclude_dimensions: Optional[set] = None,
    snapshot_id: Optional[str] = None,
) -> Optional[dict]:
    """从知识库选题。

    优先匹配公司（公司定向训练），否则按维度过滤；已做过的题（exclude_ids）
    会被排除。返回一道随机题。
    """
    from app.knowledge import KnowledgeRepository

    repo = KnowledgeRepository(snapshot_id=snapshot_id)
    try:
        params: list = []

        # 公司定向：优先选匹配公司的题
        if companies:
            like_clauses = " OR ".join(["companies LIKE ?"] * len(companies))
            sql = f"SELECT * FROM knowledge WHERE ({like_clauses})"
            params.extend(f"%{c}%" for c in companies)
            if dimensions:
                sql += " AND dimension IN ({})".format(",".join("?" * len(dimensions)))
                params.extend(dimensions)
        elif dimensions:
            sql = "SELECT * FROM knowledge WHERE dimension IN ({})".format(
                ",".join("?" * len(dimensions))
            )
            params.extend(dimensions)
        else:
            sql = "SELECT * FROM knowledge WHERE 1=1"

        if difficulty > 0:
            sql += " AND difficulty = ?"
            params.append(difficulty)
        if exclude_ids:
            sql += " AND id NOT IN ({})".format(",".join("?" * len(exclude_ids)))
            params.extend(exclude_ids)
        if exclude_dimensions:
            sql += " AND dimension NOT IN ({})".format(",".join("?" * len(exclude_dimensions)))
            params.extend(exclude_dimensions)
        sql += " ORDER BY RANDOM() LIMIT 1"

        row = repo.conn.execute(sql, params).fetchone()
        if not row:
            return None
        d = KnowledgeRepository._row_to_dict(row)
        d.pop("embedding", None)
        return d
    finally:
        repo.close()


def _progress_store(user_id: str, goal_id: Optional[str] = None):
    return GoalProgressStore(user_id, goal_id) if goal_id else ProgressStore(user_id)


def _pick_review_question(
    user_id: str,
    done_ids: set,
    goal_id: Optional[str] = None,
    snapshot_id: Optional[str] = None,
) -> Optional[dict]:
    """从复习队列选题：取到期待复习、且属于已做过的题。"""
    from app.knowledge import get_question

    store = _progress_store(user_id, goal_id)
    due = store.review_queue(limit=50)
    if not due:
        return None
    # 按掌握度升序（最不熟练的优先复习）
    due.sort(key=lambda p: p.mastery)
    for p in due:
        if p.question_id in done_ids:
            q = get_question(p.question_id, snapshot_id=snapshot_id)
            if q:
                d = q.model_dump()
                d.pop("id", None)
                d["id"] = p.question_id
                return d
    return None


async def _call_llm(system_prompt: str, user_prompt: str = "") -> str:
    """调用 LLM，返回纯文本。

    注意：部分 OpenAI 兼容网关（如 Deepseek-v4-flash）在请求只有
    system 消息、没有 user 消息时会返回乱码。因此 user_prompt 为空时
    自动补一个非空占位 user 消息。
    """
    model = create_chat_model(temperature=0.2)
    if not user_prompt:
        user_prompt = "请开始回答。"
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    response = await model.ainvoke(messages)
    return message_text(response)


async def _call_structured(system_prompt: str, user_prompt: str) -> EvaluationResult:
    """调用 LLM 并解析为结构化评分。"""
    model = create_chat_model(temperature=0.0)
    structured = model.with_structured_output(EvaluationResult)
    result = await structured.ainvoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    return result


def _resolve_goal_filters(req: StartRequest) -> tuple[List[str], List[str]]:
    dimensions = list(dict.fromkeys(req.dimensions))
    companies = list(dict.fromkeys(req.companies))
    if not req.goal_id:
        return dimensions, companies
    task = memory.get_task(req.goal_id)
    if task and task.get("kind") == "interview_goal":
        if not companies:
            companies = list(task.get("target_companies") or [])
        if not dimensions and req.mode in {"diagnostic", "mock"}:
            dimensions.extend(_role_dimension_hints(task.get("target_role") or ""))
    if req.mode in {"diagnostic", "mock"} and not dimensions:
        weak = get_progress(req.user_id, goal_id=req.goal_id).get("weak_dimensions", [])
        dimensions = [item["dimension"] for item in weak[:5] if item.get("dimension")]
    elif req.mode in {"diagnostic", "mock"}:
        weak = get_progress(req.user_id, goal_id=req.goal_id).get("weak_dimensions", [])
        dimensions = list(dict.fromkeys(
            [item["dimension"] for item in weak[:5] if item.get("dimension")] + dimensions
        ))
    return dimensions, companies


def _role_dimension_hints(target_role: str) -> List[str]:
    """Map common role language to knowledge dimensions used for candidate selection."""
    role = target_role.lower()
    mappings = [
        (("agent", "智能体"), ["agent-concepts", "tool-management", "memory-context", "multi-agent"]),
        (("rag", "检索"), ["rag", "evaluation", "prompt-engineering"]),
        (("前端", "frontend", "全栈", "full stack"), ["full-stack", "engineering", "architecture"]),
        (("模型", "算法", "训练", "llm"), ["model", "training", "evaluation"]),
        (("测试", "质量"), ["ai-code-testing", "engineering-pitfalls", "evaluation"]),
    ]
    result: List[str] = []
    for keywords, dimensions in mappings:
        if any(keyword in role for keyword in keywords):
            result.extend(dimensions)
    return list(dict.fromkeys(result))


def _question_count(req: StartRequest) -> int:
    if req.mode == "diagnostic":
        return 3
    if req.mode == "mock":
        return req.question_count if req.question_count in {3, 5, 8} else 5
    return 1


def _select_question(session: InterviewSession, *, done_ids: set) -> Optional[dict]:
    excluded = set(done_ids) | set(session.question_ids)
    excluded_dimensions = set()
    if session.mode == "diagnostic":
        excluded_dimensions = {
            item.get("dimension")
            for item in session.answers
            if item.get("dimension")
        }
    question = _pick_question(
        session.dimensions,
        session.companies,
        session.difficulty,
        exclude_ids=excluded,
        exclude_dimensions=excluded_dimensions,
        snapshot_id=session.knowledge_snapshot_id,
    )
    if question is None and session.mode in {"diagnostic", "mock"} and session.dimensions:
        # Role/weakness filters are preferences. Fall back to the broader bank so
        # a multi-question session can still complete with distinct questions.
        question = _pick_question(
            [],
            session.companies,
            session.difficulty,
            exclude_ids=excluded,
            exclude_dimensions=excluded_dimensions,
            snapshot_id=session.knowledge_snapshot_id,
        )
    if question is None and session.mode in {"diagnostic", "mock"} and session.companies:
        question = _pick_question(
            [],
            [],
            session.difficulty,
            exclude_ids=excluded,
            exclude_dimensions=excluded_dimensions,
            snapshot_id=session.knowledge_snapshot_id,
        )
    if question is None and done_ids:
        question = _pick_question(
            session.dimensions,
            session.companies,
            session.difficulty,
            exclude_ids=set(session.question_ids),
            exclude_dimensions=excluded_dimensions,
            snapshot_id=session.knowledge_snapshot_id,
        )
    if question is None and done_ids and session.mode in {"diagnostic", "mock"}:
        question = _pick_question(
            [],
            [],
            session.difficulty,
            exclude_ids=set(session.question_ids),
            exclude_dimensions=excluded_dimensions,
            snapshot_id=session.knowledge_snapshot_id,
        )
    return question


async def _activate_question(session: InterviewSession, question: dict) -> str:
    from app.knowledge.schema import InterviewQuestion

    session.current_question_id = question["id"]
    if question["id"] not in session.question_ids:
        session.question_ids.append(question["id"])
    # 将当前题的完整结构化内容存入会话。即使后台切换并清理了
    # 对应 release，当前题仍能完成评分和复盘。
    session.retrieved_knowledge = InterviewQuestion.model_validate(question).model_dump()
    ask_prompt = prompts.INTERVIEWER_ASK_PROMPT.format(question=question["question"])
    role_context = f"\n目标岗位：{session.target_role}" if session.target_role else ""
    question_text = await _call_llm(
        prompts.INTERVIEWER_SYSTEM_PROMPT.format(
            question=question["question"],
            dimension_label=question["dimension_label"],
            difficulty=session.difficulty,
        ) + role_context,
        ask_prompt,
    )
    session.current_question = question_text or question["question"]
    session.question_round = len(session.question_ids)
    session.phase = "awaiting_answer"
    return session.current_question


def _session_question(session: InterviewSession):
    """优先读取会话内固定的完整题目，兼容旧会话数据。"""
    from app.knowledge import get_question
    from app.knowledge.schema import InterviewQuestion

    cached = session.retrieved_knowledge or {}
    if cached.get("id") == session.current_question_id:
        try:
            return InterviewQuestion.model_validate(cached)
        except ValueError:
            pass
    try:
        return get_question(
            session.current_question_id or "",
            snapshot_id=session.knowledge_snapshot_id,
        )
    except FileNotFoundError:
        # 旧版会话未缓存完整题目，且所指快照已被清理时，尝试当前库。
        return get_question(session.current_question_id or "")


def _unique_strings(values: List[str], limit: int = 8) -> List[str]:
    result: List[str] = []
    for value in values:
        cleaned = str(value).strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def _build_report(session: InterviewSession, *, completed: bool) -> InterviewReport:
    score_keys = ["correctness", "depth", "tradeoff_reasoning", "engineering_evidence", "clarity"]
    evaluations = session.evaluations
    scores = {
        key: round(sum(float(item.get(key, 0)) for item in evaluations) / len(evaluations), 1)
        for key in score_keys
    } if evaluations else {key: 0.0 for key in score_keys}
    overall = round(
        sum(float(item.get("overall_level", 0)) for item in evaluations) / len(evaluations),
        1,
    ) if evaluations else 0.0
    strengths = _unique_strings([
        value for item in evaluations for value in item.get("strengths", [])
    ])
    missing = _unique_strings([
        value for item in evaluations for value in item.get("missing_points", [])
    ])
    question_results = []
    for answer, evaluation in zip(session.answers, evaluations):
        question_results.append(InterviewQuestionResult(
            question_id=answer.get("question_id", ""),
            question=answer.get("question", ""),
            answer=answer.get("answer", ""),
            overall_level=int(evaluation.get("overall_level", 0)),
            scores={key: int(evaluation.get(key, 0)) for key in score_keys},
            strengths=evaluation.get("strengths", []),
            missing_points=evaluation.get("missing_points", []),
        ))
    report = InterviewReport(
        report_id=uuid.uuid4().hex,
        session_id=session.session_id,
        user_id=session.user_id,
        goal_id=session.goal_id,
        mode=session.mode,
        completed=completed,
        question_count=session.question_count,
        answered_count=len(question_results),
        overall_level=overall,
        scores=scores,
        strengths=strengths,
        missing_points=missing,
        question_results=question_results,
        study_recommendations=[f"针对「{item}」安排专项复习" for item in missing[:5]],
        plan_adjustment_points=missing[:5],
        created_at=datetime.now().isoformat(),
    )
    save_report(report)
    session.report_id = report.report_id
    session.phase = "completed"
    save_session(session)
    return report


async def start_session(req: StartRequest) -> dict:
    """开始一次刷题训练，返回题目（不含答案）。

    支持四种模式：
    - practice：普通刷题，随机选题（排除已做过的题）。
    - review：复习模式，从复习队列（到期待复习的题）中选题。
    - diagnostic：固定三题、不同维度，逐题简评并生成能力基线。
    - mock：连续 3/5/8 题，过程中隐藏评分，最后统一生成报告。
    """
    from app.knowledge.snapshot import snapshot_manager

    session_id = uuid.uuid4().hex
    knowledge_snapshot_id = snapshot_manager.resolve().snapshot_id
    dimensions, companies = _resolve_goal_filters(req)
    session = InterviewSession(
        session_id=session_id,
        user_id=req.user_id,
        goal_id=req.goal_id,
        target_role=(memory.get_task(req.goal_id) or {}).get("target_role") if req.goal_id else None,
        mode=req.mode,
        dimensions=dimensions,
        companies=companies,
        difficulty=req.difficulty,
        phase="asking",
        question_round=1,
        question_count=_question_count(req),
        knowledge_snapshot_id=knowledge_snapshot_id,
    )

    # 已做过的题（排除，避免重复出题）
    store = _progress_store(req.user_id, req.goal_id)
    done_ids = {p.question_id for p in store.all()}

    question = None
    if req.mode == "review":
        question = _pick_review_question(
            req.user_id,
            done_ids,
            req.goal_id,
            snapshot_id=session.knowledge_snapshot_id,
        )
        if not question:
            return {
                "session_id": session_id,
                "phase": "completed",
                "question": None,
                "message": "暂无待复习题目，先去刷几道新题吧！",
            }
    else:
        question = _select_question(session, done_ids=done_ids)
        if not question:
            return {
                "session_id": session_id,
                "phase": "completed",
                "question": None,
                "message": "知识库中没有符合条件的题目，请调整维度或公司筛选。",
            }

    question_text = await _activate_question(session, question)
    save_session(session)

    return {
        "session_id": session_id,
        "phase": session.phase,
        "round": session.question_round,
        "question_count": session.question_count,
        "question": question_text or question["question"],
        "dimension": question["dimension"],
        "mode": session.mode,
        "goal_id": session.goal_id,
        "knowledge_snapshot_id": session.knowledge_snapshot_id,
    }


async def submit_answer(req: AnswerRequest) -> dict:
    """用户提交作答：结构化评分 + 生成追问。"""
    session = load_session(req.session_id)
    if not session:
        return {"error": "会话不存在或已过期", "phase": "completed"}

    if session.phase != "awaiting_answer":
        return {"error": f"当前阶段为 {session.phase}，无法提交作答", "phase": session.phase}

    question_id = session.current_question_id
    session.last_answer = req.answer

    # 从会话内的快照题目补齐标准答案（此阶段才接触专家答案）。
    full = _session_question(session)
    if not full:
        return {"error": "题目信息缺失", "phase": "completed"}

    session.phase = "evaluating"

    # 结构化评分
    eval_prompt = prompts.EVALUATOR_SYSTEM_PROMPT.format(
        question=full.question,
        answer=req.answer,
        expert_answer=full.expert_answer,
        gap_analysis=full.gap_analysis,
        key_points="、".join(full.key_points) if full.key_points else "（未提供）",
    )
    try:
        evaluation = await _call_structured(eval_prompt, "")
    except Exception as e:
        print(f"[Interview] 结构化评分失败，回退默认：{e}")
        evaluation = EvaluationResult(
            overall_level=3,
            correctness=3,
            depth=3,
            tradeoff_reasoning=3,
            engineering_evidence=3,
            clarity=3,
        )

    session.evaluation_result = evaluation.model_dump()

    # 更新学习进度
    store = _progress_store(session.user_id, session.goal_id)
    progress = store.record_attempt(
        question_id=question_id,
        overall_level=evaluation.overall_level,
        scores={
            "correctness": evaluation.correctness,
            "depth": evaluation.depth,
            "tradeoff_reasoning": evaluation.tradeoff_reasoning,
            "engineering_evidence": evaluation.engineering_evidence,
            "clarity": evaluation.clarity,
        },
        missing_points=evaluation.missing_points,
        mastery_delta=evaluation.mastery_delta,
    )

    answer_record = {
        "question_id": question_id,
        "question": full.question,
        "answer": req.answer,
        "dimension": full.dimension,
    }
    session.answers.append(answer_record)
    session.evaluations.append(evaluation.model_dump())

    if session.mode in {"diagnostic", "mock"}:
        if len(session.answers) >= session.question_count:
            report = _build_report(session, completed=True)
            response = {
                "session_id": session.session_id,
                "phase": "completed",
                "round": len(session.answers),
                "question_count": session.question_count,
                "report": report.model_dump(),
            }
            if session.mode == "diagnostic":
                response["evaluation"] = evaluation.model_dump()
                response["progress"] = progress.model_dump()
            return response

        done_ids = {p.question_id for p in store.all()}
        question = _select_question(session, done_ids=done_ids)
        if not question:
            report = _build_report(session, completed=False)
            return {
                "session_id": session.session_id,
                "phase": "completed",
                "round": len(session.answers),
                "question_count": session.question_count,
                "report": report.model_dump(),
                "message": "符合条件的题目不足，已根据完成部分生成报告。",
            }
        next_question = await _activate_question(session, question)
        save_session(session)
        response = {
            "session_id": session.session_id,
            "phase": "awaiting_answer",
            "round": session.question_round,
            "question_count": session.question_count,
            "question": next_question,
            "dimension": question.get("dimension"),
        }
        if session.mode == "diagnostic":
            response["evaluation"] = evaluation.model_dump()
            response["progress"] = progress.model_dump()
        return response

    # 生成追问（针对缺失点）
    followup = ""
    if evaluation.missing_points:
        followup_prompt = prompts.INTERVIEWER_FOLLOWUP_PROMPT.format(
            missing_points="、".join(evaluation.missing_points)
        )
        followup = await _call_llm(
            prompts.INTERVIEWER_SYSTEM_PROMPT.format(
                question=full.question,
                dimension_label=full.dimension_label,
                difficulty=session.difficulty,
            ),
            followup_prompt,
        )

    session.phase = "reviewing"
    save_session(session)

    return {
        "session_id": session.session_id,
        "phase": session.phase,
        "evaluation": evaluation.model_dump(),
        "progress": progress.model_dump(),
        "followup": followup or None,
        "mastery": progress.mastery,
        "next_review_at": progress.next_review_at,
    }


async def review(session_id: str) -> dict:
    """展示高手答与复盘反馈，结束本轮训练。"""
    session = load_session(session_id)
    if not session:
        return {"error": "会话不存在或已过期", "phase": "completed"}

    question_id = session.current_question_id
    full = _session_question(session)
    if not full:
        return {"error": "题目信息缺失", "phase": "completed"}

    evaluation = session.evaluation_result or {}
    score_summary = json.dumps(evaluation, ensure_ascii=False, indent=2)

    coach_prompt = prompts.COACH_SYSTEM_PROMPT.format(
        question=full.question,
        answer=session.last_answer,
        score_summary=score_summary,
        expert_answer=full.expert_answer,
    )
    feedback = await _call_llm(coach_prompt)

    session.phase = "completed"
    save_session(session)

    return {
        "session_id": session_id,
        "phase": "completed",
        "feedback": feedback,
        "expert_answer": full.expert_answer,
        "gap_analysis": full.gap_analysis,
    }


def get_session(session_id: str) -> Optional[InterviewSession]:
    return load_session(session_id)


def get_session_view(session_id: str) -> Optional[dict]:
    session = load_session(session_id)
    if not session:
        return None
    result = {
        "session_id": session.session_id,
        "goal_id": session.goal_id,
        "mode": session.mode,
        "phase": session.phase,
        "round": session.question_round,
        "question_count": session.question_count,
        "question": session.current_question if session.phase == "awaiting_answer" else None,
        "answered_count": len(session.answers),
        "report_id": session.report_id,
        "knowledge_snapshot_id": session.knowledge_snapshot_id,
    }
    if session.phase == "completed" and session.report_id:
        report = get_report(session.report_id)
        result["report"] = report.model_dump() if report else None
    return result


def end_session(session_id: str) -> dict:
    session = load_session(session_id)
    if not session:
        return {"error": "会话不存在或已过期", "phase": "completed"}
    if session.mode not in {"diagnostic", "mock"}:
        return {"error": "当前会话不支持提前结束", "phase": session.phase}
    if not session.answers:
        delete_session(session_id)
        return {"session_id": session_id, "phase": "cancelled", "report": None}
    report = _build_report(session, completed=False)
    return {"session_id": session_id, "phase": "completed", "report": report.model_dump()}


def get_progress(
    user_id: str = "local_user",
    limit: int = 20,
    goal_id: Optional[str] = None,
) -> dict:
    if goal_id:
        store = GoalProgressStore(user_id, goal_id)
        all_progress = store.all()
        due = store.review_queue(limit=limit)
    else:
        all_progress = ProgressStore(user_id).all() + list_all_goal_progress(user_id)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        due = [item for item in all_progress if item.next_review_at and item.next_review_at <= now]
        due.sort(key=lambda item: (item.next_review_at, item.mastery))
        due = due[:limit]

    # 按维度聚合掌握度（通过知识库反查 question_id -> dimension）
    dimension_stats = _aggregate_dimension_stats(all_progress)
    wrong_questions = _aggregate_wrong_questions(all_progress)
    weak_dimensions = _aggregate_weak_dimensions(dimension_stats)

    return {
        "goal_id": goal_id,
        "review_queue": [p.model_dump() for p in due],
        "total_attempted": len(all_progress),
        "average_mastery": round(
            sum(p.mastery for p in all_progress) / len(all_progress), 3
        ) if all_progress else 0.0,
        "dimension_stats": dimension_stats,
        "wrong_questions": wrong_questions,
        "weak_dimensions": weak_dimensions,
    }


def _aggregate_dimension_stats(progress_list: list) -> list:
    """按维度聚合掌握度，返回 [{dimension, dimension_label, count, avg_mastery, avg_level}]。"""
    from app.knowledge import KnowledgeRepository

    repo = KnowledgeRepository()
    try:
        # 批量反查 question_id -> (dimension, dimension_label)
        ids = [p.question_id for p in progress_list]
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        rows = repo.conn.execute(
            f"SELECT id, dimension, dimension_label FROM knowledge WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        id_to_dim = {r["id"]: (r["dimension"], r["dimension_label"]) for r in rows}
    finally:
        repo.close()

    agg: dict = {}
    for p in progress_list:
        dim_info = id_to_dim.get(p.question_id)
        if not dim_info:
            continue
        dim, label = dim_info
        entry = agg.setdefault(dim, {
            "dimension": dim,
            "dimension_label": label,
            "count": 0,
            "mastery_sum": 0.0,
            "level_sum": 0,
        })
        entry["count"] += 1
        entry["mastery_sum"] += p.mastery
        entry["level_sum"] += p.best_level

    result = []
    for dim, e in agg.items():
        result.append({
            "dimension": dim,
            "dimension_label": e["dimension_label"],
            "count": e["count"],
            "avg_mastery": round(e["mastery_sum"] / e["count"], 3),
            "avg_level": round(e["level_sum"] / e["count"], 1),
        })
    result.sort(key=lambda x: -x["avg_mastery"])
    return result


def _aggregate_wrong_questions(progress_list: list) -> list:
    """聚合错题本：best_level <= 2 的题，按掌握度升序（最弱优先）。

    返回 [{question_id, question, dimension, dimension_label, best_level, mastery, attempts, missing_points}]。
    """
    from app.knowledge import KnowledgeRepository

    wrong = [p for p in progress_list if p.best_level <= 2]
    if not wrong:
        return []

    repo = KnowledgeRepository()
    try:
        ids = [p.question_id for p in wrong]
        placeholders = ",".join("?" * len(ids))
        rows = repo.conn.execute(
            f"SELECT id, question, dimension, dimension_label FROM knowledge WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        id_to_q = {r["id"]: r for r in rows}
    finally:
        repo.close()

    result = []
    for p in wrong:
        q = id_to_q.get(p.question_id)
        if not q:
            continue
        result.append({
            "question_id": p.question_id,
            "question": q["question"],
            "dimension": q["dimension"],
            "dimension_label": q["dimension_label"],
            "best_level": p.best_level,
            "mastery": p.mastery,
            "attempts": p.attempts,
            "missing_points": p.missing_points,
        })
    result.sort(key=lambda x: x["mastery"])
    return result


def _aggregate_weak_dimensions(dimension_stats: list) -> list:
    """从维度统计中筛出薄弱维度（平均掌握度 < 0.6，且练过题）。"""
    weak = [d for d in dimension_stats if d["avg_mastery"] < 0.6]
    weak.sort(key=lambda x: x["avg_mastery"])
    return weak
