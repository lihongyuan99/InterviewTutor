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
from app.interview.progress import ProgressStore
from app.interview.session_store import delete_session, load_session, save_session


def _pick_question(
    dimensions: List[str],
    companies: List[str],
    difficulty: int,
    exclude_ids: Optional[set] = None,
) -> Optional[dict]:
    """从知识库选题。

    优先匹配公司（公司定向训练），否则按维度过滤；已做过的题（exclude_ids）
    会被排除。返回一道随机题。
    """
    from app.knowledge import KnowledgeRepository

    repo = KnowledgeRepository()
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
        sql += " ORDER BY RANDOM() LIMIT 1"

        row = repo.conn.execute(sql, params).fetchone()
        if not row:
            return None
        d = KnowledgeRepository._row_to_dict(row)
        d.pop("embedding", None)
        return d
    finally:
        repo.close()


def _pick_review_question(user_id: str, done_ids: set) -> Optional[dict]:
    """从复习队列选题：取到期待复习、且属于已做过的题。"""
    from app.knowledge import get_question

    store = ProgressStore(user_id)
    due = store.review_queue(limit=50)
    if not due:
        return None
    # 按掌握度升序（最不熟练的优先复习）
    due.sort(key=lambda p: p.mastery)
    for p in due:
        if p.question_id in done_ids:
            q = get_question(p.question_id)
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


async def start_session(req: StartRequest) -> dict:
    """开始一次刷题训练，返回题目（不含答案）。

    支持三种模式：
    - practice：普通刷题，随机选题（排除已做过的题）。
    - review：复习模式，从复习队列（到期待复习的题）中选题。
    - mock：模拟面试（与 practice 相同，仅标记语义不同）。
    """
    session_id = uuid.uuid4().hex
    session = InterviewSession(
        session_id=session_id,
        user_id=req.user_id,
        mode=req.mode,
        dimensions=req.dimensions,
        companies=req.companies,
        difficulty=req.difficulty,
        phase="asking",
        question_round=1,
    )

    # 已做过的题（排除，避免重复出题）
    done_ids = {p.question_id for p in ProgressStore(req.user_id).all()}

    question = None
    if req.mode == "review":
        question = _pick_review_question(req.user_id, done_ids)
        if not question:
            return {
                "session_id": session_id,
                "phase": "completed",
                "question": None,
                "message": "暂无待复习题目，先去刷几道新题吧！",
            }
    else:
        question = _pick_question(
            req.dimensions, req.companies, req.difficulty, exclude_ids=done_ids
        )
        if not question:
            return {
                "session_id": session_id,
                "phase": "completed",
                "question": None,
                "message": "知识库中没有符合条件的题目，请调整维度或公司筛选。",
            }

    session.current_question_id = question["id"]
    session.current_question = question["question"]
    # 仅保存出题所需的最小上下文（不含专家答案）
    session.retrieved_knowledge = {
        "question_id": question["id"],
        "dimension": question["dimension"],
        "dimension_label": question["dimension_label"],
        # 专家答案留空，评分阶段再补齐
    }

    # 出题阶段：只传题目，不传答案
    ask_prompt = prompts.INTERVIEWER_ASK_PROMPT.format(question=question["question"])
    question_text = await _call_llm(
        prompts.INTERVIEWER_SYSTEM_PROMPT.format(
            question=question["question"],
            dimension_label=question["dimension_label"],
            difficulty=req.difficulty,
        ),
        ask_prompt,
    )

    session.phase = "awaiting_answer"
    save_session(session)

    return {
        "session_id": session_id,
        "phase": session.phase,
        "round": session.question_round,
        "question": question_text or question["question"],
        "dimension": question["dimension"],
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

    # 从知识库补齐标准答案（此阶段才接触专家答案）
    from app.knowledge import get_question

    full = get_question(question_id)
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
    store = ProgressStore(session.user_id)
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
    from app.knowledge import get_question

    full = get_question(question_id)
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


def get_progress(user_id: str = "local_user", limit: int = 20) -> dict:
    store = ProgressStore(user_id)
    due = store.review_queue(limit=limit)
    all_progress = store.all()

    # 按维度聚合掌握度（通过知识库反查 question_id -> dimension）
    dimension_stats = _aggregate_dimension_stats(all_progress)
    wrong_questions = _aggregate_wrong_questions(all_progress)
    weak_dimensions = _aggregate_weak_dimensions(dimension_stats)

    return {
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
