"""Interview-goal workspace compatibility and isolation tests."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import memory
from app.interview.models import AnswerRequest, EvaluationResult, StartRequest
from app.interview.progress import GoalProgressStore, ProgressStore


def _isolate_task_index(monkeypatch, tmp_path):
    index_dir = tmp_path / "task_index"
    monkeypatch.setattr(memory, "TASK_INDEX_DIR", str(index_dir))
    monkeypatch.setattr(memory, "TASK_INDEX_PATH", str(index_dir / "tasks.json"))


def test_legacy_task_is_normalized_without_rewriting(monkeypatch, tmp_path):
    _isolate_task_index(monkeypatch, tmp_path)
    raw = [{"id": "task_old", "title": "旧学习", "icon": "📚", "status": "active"}]
    path = Path(memory.TASK_INDEX_PATH)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    task = memory.get_task("task_old")

    assert task is not None
    assert task["kind"] == "legacy_learning"
    assert task["target_role"] is None
    assert task["target_companies"] == []
    assert path.read_text(encoding="utf-8") == before


def test_goal_validation_server_title_and_single_read(monkeypatch, tmp_path):
    from fastapi import HTTPException
    from app.api.tasks import TaskUpsertRequest, get_task, upsert_task

    _isolate_task_index(monkeypatch, tmp_path)

    with pytest.raises(HTTPException) as caught:
        asyncio.run(upsert_task(TaskUpsertRequest(task_id="goal_missing", kind="interview_goal")))
    assert caught.value.status_code == 400

    created = asyncio.run(upsert_task(TaskUpsertRequest(
        task_id="goal_1",
        kind="interview_goal",
        title="客户端标题不应生效",
        target_role="AI Agent 工程师",
        target_companies=["字节", "阿里"],
        interview_date="2026-09-01",
        experience_level="intermediate",
    )))
    assert created.title == "字节 · AI Agent 工程师"
    assert created.kind == "interview_goal"

    loaded = asyncio.run(get_task("goal_1"))
    assert loaded.id == created.id
    assert loaded.target_companies == ["字节", "阿里"]
    assert loaded.interview_date == "2026-09-01"


def test_goal_progress_isolation_and_global_aggregation(monkeypatch, tmp_path):
    from app.interview import workflow

    monkeypatch.setattr("app.interview.progress.PROGRESS_DIR", str(tmp_path / "legacy"))
    monkeypatch.setattr("app.interview.progress.GOAL_PROGRESS_DIR", str(tmp_path / "v2"))
    monkeypatch.setattr(workflow, "_aggregate_dimension_stats", lambda items: [])
    monkeypatch.setattr(workflow, "_aggregate_wrong_questions", lambda items: [])
    monkeypatch.setattr(workflow, "_aggregate_weak_dimensions", lambda items: [])

    common = dict(question_id="same-question", scores={}, missing_points=[])
    ProgressStore("tester").record_attempt(overall_level=2, **common)
    GoalProgressStore("tester", "goal-a").record_attempt(overall_level=3, **common)
    GoalProgressStore("tester", "goal-b").record_attempt(overall_level=5, **common)

    goal_a = workflow.get_progress(user_id="tester", goal_id="goal-a")
    goal_b = workflow.get_progress(user_id="tester", goal_id="goal-b")
    global_progress = workflow.get_progress(user_id="tester")

    assert goal_a["total_attempted"] == 1
    assert goal_b["total_attempted"] == 1
    assert goal_a["average_mastery"] != goal_b["average_mastery"]
    assert global_progress["total_attempted"] == 3
    document = json.loads((tmp_path / "v2" / "tester.json").read_text(encoding="utf-8"))
    assert document["schema_version"] == 2
    assert set(document["goals"]) == {"goal-a", "goal-b"}


def _patch_interview_runtime(monkeypatch, tmp_path, question_total=8):
    from app.interview import workflow
    from app.knowledge.schema import InterviewQuestion

    monkeypatch.setattr("app.interview.progress.GOAL_PROGRESS_DIR", str(tmp_path / "progress"))
    monkeypatch.setattr("app.interview.session_store.SESSION_DIR", str(tmp_path / "sessions"))
    monkeypatch.setattr("app.interview.report_store.REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(workflow.memory, "get_task", lambda goal_id: {
        "id": goal_id,
        "kind": "interview_goal",
        "target_role": "AI Agent 工程师",
        "target_companies": [],
    })

    questions = []
    full = {}
    for index in range(question_total):
        question_id = f"q-{index}"
        dimension = f"dim-{index}"
        questions.append({
            "id": question_id,
            "dimension": dimension,
            "dimension_label": f"维度 {index}",
            "question": f"问题 {index}",
            "expert_answer": f"专家答案 {index}",
            "gap_analysis": f"差距 {index}",
            "key_points": [f"要点 {index}"],
            "source_file": "01-architecture-design/index.md",
        })
        full[question_id] = InterviewQuestion(
            id=question_id,
            dimension=dimension,
            dimension_label=f"维度 {index}",
            question=f"问题 {index}",
            source="测试",
            novice_answer="新手回答",
            expert_answer=f"专家答案 {index}",
            gap_analysis=f"差距 {index}",
            key_points=[f"要点 {index}"],
            source_file="test.md",
        )

    def pick(*args, **kwargs):
        excluded_ids = kwargs.get("exclude_ids") or set()
        excluded_dimensions = kwargs.get("exclude_dimensions") or set()
        return next((item for item in questions if item["id"] not in excluded_ids and item["dimension"] not in excluded_dimensions), None)

    async def call_llm(system_prompt, user_prompt=""):
        return next((item["question"] for item in questions if item["question"] in system_prompt), "面试问题")

    async def call_structured(system_prompt, user_prompt=""):
        return EvaluationResult(
            overall_level=3,
            correctness=3,
            depth=3,
            tradeoff_reasoning=3,
            engineering_evidence=3,
            clarity=3,
            strengths=["结构清晰"],
            missing_points=["量化证据"],
            improvement_advice=["补充指标"],
            mastery_delta=0.0,
        )

    monkeypatch.setattr(workflow, "_pick_question", pick)
    monkeypatch.setattr(workflow, "_call_llm", call_llm)
    monkeypatch.setattr(workflow, "_call_structured", call_structured)
    monkeypatch.setattr("app.knowledge.get_question", lambda question_id, **kwargs: full.get(question_id))
    return workflow


def test_diagnostic_is_three_distinct_questions_and_updates_baseline(monkeypatch, tmp_path):
    workflow = _patch_interview_runtime(monkeypatch, tmp_path)

    async def run_flow():
        started = await workflow.start_session(StartRequest(goal_id="goal-diag", mode="diagnostic"))
        assert started["question_count"] == 3
        session_id = started["session_id"]
        responses = []
        for index in range(3):
            response = await workflow.submit_answer(AnswerRequest(session_id=session_id, answer=f"回答 {index}"))
            responses.append(response)
        return session_id, responses

    session_id, responses = asyncio.run(run_flow())
    assert all("evaluation" in item for item in responses)
    assert responses[-1]["phase"] == "completed"
    assert responses[-1]["report"]["answered_count"] == 3
    assert len(GoalProgressStore("local_user", "goal-diag").all()) == 3
    restored = workflow.get_session_view(session_id)
    assert restored["phase"] == "completed"
    assert restored["report"]["mode"] == "diagnostic"


def test_mock_five_questions_hides_scores_until_final_report(monkeypatch, tmp_path):
    workflow = _patch_interview_runtime(monkeypatch, tmp_path)

    async def run_flow():
        started = await workflow.start_session(StartRequest(goal_id="goal-mock", mode="mock", question_count=5))
        assert started["question_count"] == 5
        session_id = started["session_id"]
        intermediate = []
        for index in range(5):
            response = await workflow.submit_answer(AnswerRequest(session_id=session_id, answer=f"回答 {index}"))
            if index < 4:
                intermediate.append(response)
            else:
                final = response
        return session_id, intermediate, final

    session_id, intermediate, final = asyncio.run(run_flow())
    for response in intermediate:
        assert response["phase"] == "awaiting_answer"
        assert "evaluation" not in response
        assert "progress" not in response
        assert "expert_answer" not in response
        assert "missing_points" not in response
    assert final["phase"] == "completed"
    assert final["report"]["answered_count"] == 5
    assert final["report"]["question_count"] == 5
    assert workflow.get_session_view(session_id)["report"]["overall_level"] == 3.0


def test_mock_refresh_restore_and_early_end(monkeypatch, tmp_path):
    workflow = _patch_interview_runtime(monkeypatch, tmp_path)

    async def run_flow():
        started = await workflow.start_session(StartRequest(goal_id="goal-partial", mode="mock", question_count=5))
        session_id = started["session_id"]
        restored_before = workflow.get_session_view(session_id)
        await workflow.submit_answer(AnswerRequest(session_id=session_id, answer="完成一题"))
        partial = workflow.end_session(session_id)
        return restored_before, partial

    restored_before, partial = asyncio.run(run_flow())
    assert restored_before["phase"] == "awaiting_answer"
    assert restored_before["question"]
    assert partial["report"]["completed"] is False
    assert partial["report"]["answered_count"] == 1


def test_plan_proposal_does_not_change_formal_plan_until_confirm(monkeypatch, tmp_path):
    from app.api import task_plan as task_plan_api
    from app.api.task_plan import TaskPlanConfirmRequest, TaskPlanProposalRequest

    _isolate_task_index(monkeypatch, tmp_path)
    monkeypatch.setattr(memory, "NOTES_DIR", str(tmp_path / "notes"))
    memory.upsert_task(
        "goal-plan",
        "AI Agent 工程师",
        "🎯",
        kind="interview_goal",
        target_role="AI Agent 工程师",
        target_companies=[],
    )
    formal = {"taskTitle": "AI Agent 工程师", "plan": ["正式步骤"], "overallSummary": "正式计划"}
    memory.save_task_plan("goal-plan", formal)
    proposal = {"taskTitle": "模型生成标题", "plan": ["草案步骤"], "overallSummary": "草案"}
    monkeypatch.setattr(task_plan_api, "generate_task_plan_from_state", lambda *args, **kwargs: proposal)

    asyncio.run(task_plan_api.propose_task_plan(TaskPlanProposalRequest(task_id="goal-plan", source="goal_setup")))
    after_proposal = memory.get_task_plan_data("goal-plan")
    assert after_proposal["plan"] == ["正式步骤"]
    assert after_proposal["overallSummary"] == "正式计划"
    assert after_proposal["draft_plan"]["plan"] == ["草案步骤"]

    asyncio.run(task_plan_api.confirm_task_plan(TaskPlanConfirmRequest(task_id="goal-plan", plan=proposal)))
    after_confirm = memory.get_task_plan_data("goal-plan")
    assert after_confirm["plan"] == ["草案步骤"]
    assert after_confirm["draft_plan"] is None
    assert after_confirm["taskTitle"] == "AI Agent 工程师"
