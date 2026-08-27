#!/usr/bin/env python3
"""Generate the two workspace demos exclusively through InterviewTutor HTTP APIs.

The script intentionally does not import application storage modules or write files.
Run ``scripts/reset_goal_demo_data.py --apply`` first when replacing an older seed.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any


RECENT_GOAL_ID = "task_demo_recent_ai_agent"
ARCHIVED_GOAL_ID = "task_demo_archived_llm_platform"


@dataclass(frozen=True)
class GoalSeed:
    task_id: str
    role: str
    company: str
    interview_date: str
    experience_level: str
    status: str
    mode: str
    question_count: int
    sessions: tuple[tuple[str, tuple[str, ...]], ...]


GOALS = (
    GoalSeed(
        task_id=RECENT_GOAL_ID,
        role="AI Agent 应用工程师",
        company="字节跳动",
        interview_date="2026-09-18",
        experience_level="intermediate",
        status="active",
        mode="diagnostic",
        question_count=3,
        sessions=(
            (
                "岗位拆解与项目证据",
                (
                    "我准备面试字节跳动 AI Agent 应用工程师。请结合岗位梳理最优先的 4 个准备方向，并说明每个方向要准备什么项目证据。",
                    "把 Agent 架构这一项展开：ReAct、固定 Workflow 和混合架构分别适合什么场景？回答要包含取舍和线上指标。",
                ),
            ),
            (
                "RAG 与可靠性专项",
                (
                    "请用面试回答结构讲清 Agent 场景下 RAG 的检索触发、重排、失败降级和评测闭环，最后给我两道追问题。",
                ),
            ),
        ),
    ),
    GoalSeed(
        task_id=ARCHIVED_GOAL_ID,
        role="大模型平台工程师",
        company="阿里云",
        interview_date="2026-08-20",
        experience_level="advanced",
        status="archived",
        mode="mock",
        question_count=5,
        sessions=(
            (
                "企业级大模型平台架构",
                (
                    "请帮我复盘企业级大模型平台的控制面、数据面、模型网关和可观测性，重点讲清工程边界与取舍。",
                    "如果工作流节点部分成功，怎样用幂等、检查点和补偿机制安全恢复？请给出生产级回答框架。",
                ),
            ),
            (
                "多 Provider 与成本治理",
                (
                    "请按大模型平台工程师面试标准，给一版多 Provider 路由、限流、降级与成本治理的高质量回答框架。",
                ),
            ),
        ),
    ),
)


class ApiError(RuntimeError):
    pass


class ApiClient:
    def __init__(self, base_url: str, timeout: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ApiError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ApiError(f"{method} {path} failed: {exc.reason}") from exc
        if not body:
            return {}
        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ApiError(f"{method} {path} returned non-JSON: {body[:300]}") from exc
        if isinstance(result, dict) and result.get("error"):
            raise ApiError(f"{method} {path}: {result['error']}")
        return result

    def get(self, path: str) -> dict[str, Any]:
        return self.request("GET", path)

    def post(self, path: str, payload: dict[str, Any], *, timeout: int | None = None) -> dict[str, Any]:
        return self.request("POST", path, payload, timeout=timeout)

    def put(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("PUT", path, payload)

    def patch(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("PATCH", path, payload)


def log(message: str) -> None:
    print(message, flush=True)


def answer_for(question: str, index: int) -> str:
    """Return a substantial candidate answer tailored to common bank topics."""
    lowered = question.lower()
    if any(token in lowered for token in ("context", "上下文", "记忆", "window")):
        return (
            "我会把上下文分成最近原文、滚动摘要和可检索长期记忆三层。最近轮次保证推理连续性，"
            "摘要带版本、游标和来源引用，长期事实按用户、任务和有效期隔离。压缩触发由 token 预算和任务阶段共同决定，"
            "并用事实一致性、关键信息召回率、首 token 时延和单任务成本做回归；摘要失败时保留检查点并回退到上一版本。"
        )
    if any(token in lowered for token in ("rag", "检索", "召回", "重排")):
        return (
            "我先按证据新鲜度和风险决定是否检索：稳定事实可一次检索，研究或排障任务在每个新证据节点增量检索。"
            "链路采用查询改写、稀疏与向量混合召回、跨编码器重排和引用校验；零召回时逐级放宽过滤、切备用索引，"
            "仍无证据就明确拒答或转人工。离线看 Recall@K、nDCG 和忠实度，线上看任务成功率、引用点击率、时延与成本。"
        )
    if any(token in lowered for token in ("工具", "tool", "调用")):
        return (
            "工具层使用结构化契约、最小权限和幂等键。每次调用都带 deadline、重试预算与 trace id，"
            "只对可重试错误做指数退避；写操作先落意图和检查点，失败走补偿或人工接管。多轮调用还要限制总步数、"
            "token 与费用，检测重复参数和循环，并用成功率、P95 时延、回滚率及人工接管率观测质量。"
        )
    if any(token in lowered for token in ("多 agent", "multi", "handoff", "协作")):
        return (
            "多 Agent 的核心是可版本化的 Handoff 契约，而不只是路由。契约要包含目标、已完成事实、待办、证据引用、"
            "权限和预算；协调器只传最小必要状态，并用乐观版本避免并发覆盖。每个 Agent 的副作用可审计、可幂等、可取消，"
            "超时后由检查点恢复。评测同时覆盖任务完成率、错误传播率、交接次数、成本和端到端时延。"
        )
    if any(token in lowered for token in ("工作流", "workflow", "原子", "回滚", "补偿")):
        return (
            "我不会假设跨服务强事务，而是用状态机、幂等键、outbox 和 Saga 补偿实现可恢复执行。节点提交前记录输入版本，"
            "提交后写不可变检查点；重试先查幂等结果，补偿动作本身也幂等。不可自动恢复时冻结副作用并转人工。"
            "上线后重点监控重复执行率、补偿成功率、恢复时长和卡死任务数，并定期做故障注入。"
        )
    if any(token in lowered for token in ("provider", "模型平台", "网关", "路由", "限流")):
        return (
            "平台分控制面和数据面：控制面管理模型目录、策略、配额和版本，数据面通过统一网关承载推理流量。"
            "路由按能力、合规、健康度、P95 时延和单位有效输出成本打分；每个 Provider 独立限流与熔断，"
            "同能力模型做分级降级。全链路记录 prompt 版本、token、缓存命中、质量采样和 trace，结合容量压测设置预算告警。"
        )
    if any(token in lowered for token in ("评测", "evaluation", "指标", "2026")):
        return (
            "评测要从单轮答案分数升级为任务闭环。离线用固定集、对抗集和历史失败集测正确性、忠实度、工具参数与恢复能力；"
            "线上用影子流量和分桶实验观察任务成功率、人工接管率、P95 时延和单任务成本。每次模型、提示词或工具版本变化都"
            "绑定可回放 trace，失败样本自动进入回归集，同时设置业务风险阈值和一键回滚。"
        )
    return (
        f"我会先澄清目标与约束，再给出分层方案。第 {index} 题中，核心路径使用明确的接口契约、幂等状态机和可恢复检查点，"
        "不确定环节通过小范围 Agent 决策。生产上补齐超时、熔断、降级、人工接管和全链路追踪，"
        "并用任务成功率、P95 时延、错误恢复率、用户满意度及单任务成本验证取舍，最后通过灰度和故障演练持续校准。"
    )


def upsert_goal(client: ApiClient, goal: GoalSeed) -> None:
    result = client.post(
        "/api/v1/tasks",
        {
            "task_id": goal.task_id,
            "status": goal.status,
            "kind": "interview_goal",
            "target_role": goal.role,
            "target_companies": [goal.company],
            "interview_date": goal.interview_date,
            "experience_level": goal.experience_level,
        },
    )
    log(f"  task: {result['title']} [{result['status']}]")


def create_conversations(client: ApiClient, goal: GoalSeed, day_token: str) -> list[str]:
    session_ids: list[str] = []
    for session_index, (topic, prompts) in enumerate(goal.sessions, start=1):
        session_id = f"{goal.task_id}__{day_token}__{session_index:02d}0000"
        for turn_index, message in enumerate(prompts, start=1):
            response = client.post(
                "/api/v1/chat",
                {
                    "task_id": goal.task_id,
                    "session_id": session_id,
                    "topic": topic,
                    "message": message,
                },
                timeout=300,
            )
            session_id = response["session_id"]
            reply = str(response.get("reply") or "").replace("\n", " ")
            log(f"  chat {session_index}.{turn_index}: {reply[:72]}{'…' if len(reply) > 72 else ''}")
        session_ids.append(session_id)
    return session_ids


def run_training(client: ApiClient, goal: GoalSeed) -> dict[str, Any]:
    started = client.post(
        "/api/v1/interview/start",
        {
            "user_id": "local_user",
            "goal_id": goal.task_id,
            "mode": goal.mode,
            "question_count": goal.question_count,
        },
        timeout=300,
    )
    if not started.get("question"):
        raise ApiError(f"training did not start for {goal.task_id}: {started}")
    session_id = started["session_id"]
    current = started
    report: dict[str, Any] | None = None
    for index in range(1, goal.question_count + 1):
        question = str(current.get("question") or "")
        log(f"  {goal.mode} {index}/{goal.question_count}: {question[:82]}")
        current = client.post(
            "/api/v1/interview/answer",
            {"session_id": session_id, "answer": answer_for(question, index)},
            timeout=300,
        )
        if current.get("report"):
            report = current["report"]
        if current.get("phase") == "completed":
            break
        if not current.get("question"):
            raise ApiError(f"training stopped before next question: {current}")
    if not report:
        raise ApiError(f"training did not produce a report for {goal.task_id}: {current}")
    log(
        f"  report: L{report.get('overall_level')} · "
        f"{report.get('answered_count')}/{report.get('question_count')} questions"
    )
    return report


def generate_and_confirm_plan(client: ApiClient, goal: GoalSeed) -> dict[str, Any]:
    draft = client.post(
        "/api/v1/agent/task-plan/propose",
        {"task_id": goal.task_id, "source": "progress"},
        timeout=300,
    )
    proposal = draft.get("proposal")
    if not isinstance(proposal, dict):
        raise ApiError(f"invalid plan proposal for {goal.task_id}: {draft}")
    proposal = normalize_plan(client, goal, proposal)
    confirmed = client.post(
        "/api/v1/agent/task-plan/confirm",
        {"task_id": goal.task_id, "plan": proposal},
    )
    steps = confirmed.get("plan") or []
    if not isinstance(steps, list):
        steps = []
    complete_count = len(steps) if goal.status == "archived" else min(2, len(steps))
    checklist = {str(index): index < complete_count for index in range(len(steps))}
    client.put(
        "/api/v1/notes/task/plan-checklist",
        {"task_id": goal.task_id, "checklist": checklist},
    )
    log(f"  plan: {len(steps)} steps · {complete_count} completed")
    return confirmed


def normalize_plan(
    client: ApiClient,
    goal: GoalSeed,
    proposal: dict[str, Any],
) -> dict[str, Any]:
    """Keep model-produced context while presenting a compact five-stage demo plan."""
    encoded = urllib.parse.quote(goal.task_id)
    progress = client.get(f"/api/v1/interview/progress?goal_id={encoded}")
    weak_labels = [
        str(item.get("dimension_label") or item.get("dimension") or "").strip()
        for item in progress.get("weak_dimensions") or []
    ]
    weak_labels = [item for item in weak_labels if item]
    focus_one = weak_labels[0] if weak_labels else "核心架构"
    focus_two = weak_labels[1] if len(weak_labels) > 1 else "工程可靠性"
    if goal.status == "archived":
        steps = [
            f"复盘 {goal.company} {goal.role} 的平台分层、模型网关与核心 SLA",
            f"完成「{focus_one}」专项：原理、方案取舍与工程证据",
            f"完成「{focus_two}」专项：故障恢复、容量与成本边界",
            "演练多 Provider 路由、限流、熔断、降级和可观测性设计",
            "完成 5 题完整模拟面试，并将报告缺失点整理进最终复盘",
        ]
        start_date = "2026-08-06"
        total_days = 14
        total_hours = 24.0
        progress_value = 100
    else:
        steps = [
            f"拆解 {goal.company} {goal.role} 要求，建立能力矩阵和项目证据清单",
            f"专项补强「{focus_one}」，完成概念辨析、代码示例和高频追问",
            f"专项补强「{focus_two}」，形成带取舍与指标的结构化回答",
            "完善生产级 Agent 执行循环、状态管理、容错和评测闭环案例",
            "完成 5 题限时模拟面试，并根据报告调整最后一轮复习重点",
        ]
        start_date = datetime.now().astimezone().strftime("%Y-%m-%d")
        total_days = max(
            1,
            (datetime.fromisoformat(goal.interview_date).date() - datetime.now().date()).days,
        )
        total_hours = 32.0
        progress_value = 40
    mastery = [
        {
            "topic": item.get("dimension_label") or item.get("dimension"),
            "level": round(float(item.get("avg_mastery") or 0) * 100),
        }
        for item in (progress.get("dimension_stats") or [])[:5]
    ]
    summary = str(proposal.get("overallSummary") or "").strip()
    if not summary or summary.lower() == "none. 当前水平：未说明。 约束条件：灵活。":
        summary = (
            f"围绕 {goal.company} {goal.role}，根据目标内训练证据补强薄弱维度，"
            "同步准备架构取舍、工程指标和可复盘的项目案例。"
        )
    if goal.status == "archived":
        milestones = [
            {"date": "2026-08-06", "achievement": "完成岗位能力基线与平台架构梳理"},
            {"date": "2026-08-13", "achievement": "完成薄弱维度专项与工程案例整理"},
            {"date": "2026-08-19", "achievement": "完成 5 题模拟面试并形成最终复盘"},
        ]
    else:
        milestones = [
            {"date": start_date, "achievement": "完成目标能力诊断并识别薄弱维度"},
            {"date": "2026-09-05", "achievement": "完成薄弱维度专项和项目证据整理"},
            {"date": goal.interview_date, "achievement": "完成模拟面试与最终查漏补缺"},
        ]
    return {
        "startDate": start_date,
        "totalDays": total_days,
        "totalHours": total_hours,
        "progress": progress_value,
        "overallSummary": summary,
        "coreKnowledge": list(dict.fromkeys(weak_labels + ["架构取舍", "工程可靠性", "量化项目证据"]))[:6],
        "masteryLevel": mastery,
        "milestones": milestones,
        "plan": steps,
    }


def finalize_existing_plan(client: ApiClient, goal: GoalSeed) -> dict[str, Any]:
    encoded = urllib.parse.quote(goal.task_id)
    current = client.get(f"/api/v1/notes/task?task_id={encoded}")
    normalized = normalize_plan(client, goal, current)
    confirmed = client.post(
        "/api/v1/agent/task-plan/confirm",
        {"task_id": goal.task_id, "plan": normalized},
    )
    complete_count = 5 if goal.status == "archived" else 2
    checklist = {str(index): index < complete_count for index in range(5)}
    client.put(
        "/api/v1/notes/task/plan-checklist",
        {"task_id": goal.task_id, "checklist": checklist},
    )
    client.patch(f"/api/v1/tasks/{goal.task_id}/status", {"status": goal.status})
    log(f"  finalized plan: 5 steps · {complete_count} completed")
    return confirmed


def generate_notes(client: ApiClient, goal: GoalSeed, today: str) -> None:
    daily = client.post(
        f"/api/v1/history/tasks/{urllib.parse.quote(goal.task_id)}/daily-summary",
        {"task_id": goal.task_id, "date": today},
        timeout=300,
    )
    log(f"  daily summary: {len(str(daily.get('summary') or ''))} chars")
    task_note = client.post(
        f"/api/v1/history/tasks/{urllib.parse.quote(goal.task_id)}/summary",
        {"task_id": goal.task_id},
        timeout=300,
    )
    log(f"  goal note: {len(str(task_note.get('summary') or ''))} chars")


def verify_goal(client: ApiClient, goal: GoalSeed) -> dict[str, Any]:
    encoded = urllib.parse.quote(goal.task_id)
    task = client.get(f"/api/v1/tasks/{encoded}")
    sessions = client.get(f"/api/v1/history/tasks/{encoded}/sessions").get("sessions", [])
    timeline = client.get(f"/api/v1/history/tasks/{encoded}/timeline").get("timeline", [])
    plan_note = client.get(f"/api/v1/notes/task?task_id={encoded}")
    progress = client.get(f"/api/v1/interview/progress?goal_id={encoded}")
    reports = client.get(f"/api/v1/interview/reports?goal_id={encoded}").get("reports", [])
    summary = {
        "title": task.get("title"),
        "status": task.get("status"),
        "sessions": len(sessions),
        "messages": sum(int(item.get("message_count") or 0) for item in sessions),
        "timeline_days": len(timeline),
        "plan_steps": len(plan_note.get("plan") or []),
        "completed_steps": sum(1 for done in (plan_note.get("planChecklist") or {}).values() if done),
        "note_chars": len(str(plan_note.get("content") or "")),
        "attempted_questions": progress.get("total_attempted", 0),
        "weak_dimensions": len(progress.get("weak_dimensions") or []),
        "reports": len(reports),
    }
    if summary["status"] != goal.status:
        raise ApiError(f"unexpected goal status: {summary}")
    if summary["sessions"] < 2 or summary["messages"] < 6:
        raise ApiError(f"conversation verification failed: {summary}")
    if summary["attempted_questions"] < goal.question_count or summary["reports"] < 1:
        raise ApiError(f"training verification failed: {summary}")
    if summary["plan_steps"] < 1 or summary["note_chars"] < 1:
        raise ApiError(f"plan/note verification failed: {summary}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--finalize-only",
        action="store_true",
        help="Normalize existing API-generated plans and run final verification.",
    )
    args = parser.parse_args()
    client = ApiClient(args.base_url, args.timeout)

    try:
        task_list = client.get("/api/v1/tasks")
        log(f"API ready: {len(task_list.get('tasks') or [])} existing goals/tasks")
        if args.finalize_only:
            for goal in GOALS:
                log(f"\nFinalizing {goal.task_id} through APIs")
                finalize_existing_plan(client, goal)
        else:
            now = datetime.now().astimezone()
            day_token = now.strftime("%Y%m%d")
            today = now.strftime("%Y-%m-%d")
            for goal in GOALS:
                log(f"\nGenerating {goal.task_id} through APIs")
                upsert_goal(client, goal)
                create_conversations(client, goal, day_token)
                run_training(client, goal)
                generate_and_confirm_plan(client, goal)
                generate_notes(client, goal, today)
                client.patch(f"/api/v1/tasks/{goal.task_id}/status", {"status": goal.status})

        log("\nAPI verification")
        result = {goal.task_id: verify_goal(client, goal) for goal in GOALS}
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    except (ApiError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
