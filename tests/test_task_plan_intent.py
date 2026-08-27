import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from app.api.chat import _should_offer_plan
from app.core import agent_builder
from app.core.models import ExecutionPlan
from app.core.task_plan import PLAN_SESSION_KEY
from app.core.task_plan.dialog import (
    PlanReadinessDecision,
    _has_time_signal,
    _is_exit_confirm_no,
    _is_exit_confirm_yes,
    _is_exit_intent,
    _is_no,
    _is_resume_plan_intent,
    _is_yes,
    handle_plan_chat,
)


def _execution_plan(**overrides) -> ExecutionPlan:
    values = {
        "needs_tutor_answer": True,
        "needs_judge": False,
        "needs_inquiry": False,
        "request_summary": False,
        "request_plan": False,
        "is_concluding": False,
    }
    values.update(overrides)
    return ExecutionPlan(**values)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("需要", True),
        ("需要，我想学 RAG", True),
        ("嗯，需要", True),
        ("行列式是什么", False),
        ("生成式 AI 是什么", False),
        ("这个需要怎么实现", False),
        ("不需要，我先问个问题", False),
    ],
)
def test_yes_reply_matches_complete_clause_only(text, expected):
    assert _is_yes(text) is expected


def test_no_reply_does_not_match_words_inside_a_question():
    assert _is_no("不需要") is True
    assert _is_no("是否可以继续讲") is False


def test_exit_confirmation_handles_negation_before_positive_word():
    assert _is_exit_confirm_no("不退出") is True
    assert _is_exit_confirm_yes("不退出") is False
    assert _is_exit_confirm_no("不结束") is True
    assert _is_exit_confirm_yes("不结束") is False


def test_explicit_plan_exit_and_resume_phrases_are_recognized():
    assert _is_exit_intent("暂不调整计划") is True
    assert _is_exit_intent("先不讲这个概念") is False
    assert _is_resume_plan_intent("继续") is True
    assert _is_resume_plan_intent("继续调整计划") is True
    assert _is_exit_intent("继续调整计划") is False


def test_time_signal_ignores_unrelated_day_and_week_words():
    assert _has_time_signal("今天讲什么") is False
    assert _has_time_signal("周围有什么") is False
    assert _has_time_signal("时间复杂度怎么计算") is False
    assert _has_time_signal("计划四周，每天一小时") is True


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("什么是机器学习？", False),
        ("生成式 AI 是什么？", False),
        ("我想学习率应该怎么调整？", False),
        ("行列式怎么计算？", False),
        ("如何制定项目计划？", False),
        ("我想系统学习 RAG", True),
        ("准备面试，想复习算法", True),
        ("帮我制定一个四周学习计划", True),
    ],
)
def test_plan_offer_requires_a_persistent_learning_goal(text, expected):
    assert _should_offer_plan(text, True, False, False) is expected


def test_plan_offer_respects_session_and_existing_plan_guards():
    text = "我想系统学习 RAG"
    assert _should_offer_plan(text, False, False, False) is False
    assert _should_offer_plan(text, True, True, False) is False
    assert _should_offer_plan(text, True, False, True) is False


def test_exit_confirmation_can_continue_collection():
    result = asyncio.run(
        handle_plan_chat(
            task_id="task-test",
            user_message="不退出",
            existing_plan=None,
            plan_session={
                "status": "await_exit_confirm",
                "mode": "init",
                "exit_from": "collecting",
                "messages": [],
            },
            has_plan=False,
        )
    )

    assert result["handled"] is True
    assert result["plan_session"]["status"] == "collecting"
    assert result["plan_session"]["exit_from"] == ""


def test_paused_plan_can_resume_from_natural_language():
    result = asyncio.run(
        handle_plan_chat(
            task_id="task-test",
            user_message="继续调整计划",
            existing_plan=None,
            plan_session={
                "status": "paused",
                "paused_from": "collecting",
                "mode": "init",
                "messages": [],
            },
            has_plan=False,
        )
    )

    assert result["handled"] is True
    assert result["plan_session"]["status"] == "collecting"
    assert result["plan_session"]["paused_from"] == ""


def test_plan_draft_can_be_confirmed_in_chat():
    draft = {"taskTitle": "RAG 学习", "plan": ["第 1 天：学习检索基础"]}
    result = asyncio.run(
        handle_plan_chat(
            task_id="task-test",
            user_message="确认计划",
            existing_plan=draft,
            plan_session={
                "status": "await_plan_confirm",
                "draft_plan": draft,
                "messages": [],
            },
            has_plan=True,
        )
    )

    assert result["handled"] is True
    assert result["confirmed_plan"] == draft
    assert result["plan_session"]["status"] == "idle"
    assert result["plan_session"]["draft_plan"] is None


def test_incomplete_collection_does_not_generate_a_plan(monkeypatch):
    class FakeReadinessModel:
        async def ainvoke(self, _messages):
            return PlanReadinessDecision(ready=False)

    class FakePlanModel:
        def with_structured_output(self, _schema):
            return FakeReadinessModel()

        async def ainvoke(self, _messages):
            return SimpleNamespace(content="")

    from app.core.task_plan import generator

    monkeypatch.setattr(generator, "_get_chat_model", lambda: FakePlanModel())
    result = asyncio.run(
        handle_plan_chat(
            task_id="task-test",
            user_message="基础一般",
            existing_plan=None,
            plan_session={
                "status": "collecting",
                "mode": "init",
                "turns": 0,
                "max_turns": 5,
                "messages": [
                    {"role": "user", "content": "我想学习 RAG"},
                    {"role": "assistant", "content": "你想达到什么程度？"},
                ],
            },
            has_plan=False,
        )
    )

    assert result["handled"] is True
    assert result["plan_proposal"] is None
    assert result["plan_session"]["status"] == "collecting"


def test_assistant_time_question_does_not_count_as_user_time_constraint(monkeypatch):
    class FakeReadinessModel:
        async def ainvoke(self, _messages):
            return PlanReadinessDecision(ready=False)

    class FakePlanModel:
        def with_structured_output(self, _schema):
            return FakeReadinessModel()

        async def ainvoke(self, _messages):
            return SimpleNamespace(content="不应调用普通追问模型")

    from app.core.task_plan import generator

    monkeypatch.setattr(generator, "_get_chat_model", lambda: FakePlanModel())
    result = asyncio.run(
        handle_plan_chat(
            task_id="task-test",
            user_message="目前没有特别限制",
            existing_plan=None,
            plan_session={
                "status": "collecting",
                "mode": "init",
                "turns": 3,
                "max_turns": 5,
                "messages": [
                    {"role": "user", "content": "我想系统学习 RAG"},
                    {"role": "assistant", "content": "你打算学多久，每天能投入多少时间？"},
                ],
            },
            has_plan=False,
        )
    )

    assert result["plan_proposal"] is None
    assert result["reply"] == "你打算用多久学完，每天或每周能投入多少时间？"


def test_analyzer_forces_short_plan_answer_back_to_plan_node(monkeypatch):
    stored_plan = {
        PLAN_SESSION_KEY: {
            "status": "collecting",
            "mode": "init",
            "messages": [
                {"role": "assistant", "content": "你最想学习哪个主题？"},
            ],
        }
    }

    async def plan_related(*_args, **_kwargs):
        return True

    class FakePlanner:
        async def ainvoke(self, _messages):
            return _execution_plan()

    class FakeModel:
        def with_structured_output(self, _schema):
            return FakePlanner()

    monkeypatch.setattr(agent_builder.memory, "get_task_plan_data", lambda _task_id: stored_plan)
    monkeypatch.setattr(agent_builder.memory, "has_task_plan", lambda _task_id: False)
    monkeypatch.setattr(agent_builder.memory, "save_task_plan", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agent_builder, "_is_plan_related_llm", plan_related)
    monkeypatch.setattr(agent_builder, "create_chat_model", lambda **_kwargs: FakeModel())
    monkeypatch.setattr(agent_builder, "_inject_profile", lambda prompt, _state: prompt)
    monkeypatch.setattr(agent_builder, "_inject_teaching_style", lambda prompt: prompt)

    result = asyncio.run(
        agent_builder.analyzer_node(
            {
                "messages": [HumanMessage(content="RAG")],
                "task_id": "task-test",
                "session_id": "session-test",
                "conversation_summary": "",
            }
        )
    )

    assert result["plan"].request_plan is True


@pytest.mark.parametrize(
    ("message", "route_result", "expected_status", "expected_save_count"),
    [
        ("RAG", None, "collecting", 0),
        ("这个模块怎么实现？", False, "paused", 1),
    ],
)
def test_plan_router_fallback_and_unrelated_question_state(
    monkeypatch, message, route_result, expected_status, expected_save_count
):
    session = {
        "status": "collecting",
        "mode": "init",
        "messages": [{"role": "assistant", "content": "你最想学习哪个主题？"}],
    }
    stored_plan = {PLAN_SESSION_KEY: session}
    saves = []

    async def route_decision(*_args, **_kwargs):
        return route_result

    class FakePlanner:
        async def ainvoke(self, _messages):
            return _execution_plan()

    class FakeModel:
        def with_structured_output(self, _schema):
            return FakePlanner()

    monkeypatch.setattr(agent_builder.memory, "get_task_plan_data", lambda _task_id: stored_plan)
    monkeypatch.setattr(agent_builder.memory, "has_task_plan", lambda _task_id: False)
    monkeypatch.setattr(agent_builder.memory, "save_task_plan", lambda *args, **kwargs: saves.append((args, kwargs)))
    monkeypatch.setattr(agent_builder, "_is_plan_related_llm", route_decision)
    monkeypatch.setattr(agent_builder, "create_chat_model", lambda **_kwargs: FakeModel())
    monkeypatch.setattr(agent_builder, "_inject_profile", lambda prompt, _state: prompt)
    monkeypatch.setattr(agent_builder, "_inject_teaching_style", lambda prompt: prompt)

    result = asyncio.run(
        agent_builder.analyzer_node(
            {
                "messages": [HumanMessage(content=message)],
                "task_id": "task-test",
                "session_id": "session-test",
                "conversation_summary": "",
            }
        )
    )

    assert result["plan"].request_plan is False
    assert session["status"] == expected_status
    assert len(saves) == expected_save_count


@pytest.mark.parametrize(
    ("status", "message"),
    [
        ("collecting", "结束计划"),
        ("await_exit_confirm", "不退出"),
    ],
)
def test_plan_exit_flow_does_not_end_whole_learning_session(monkeypatch, status, message):
    stored_plan = {
        PLAN_SESSION_KEY: {
            "status": status,
            "mode": "init",
            "messages": [],
        }
    }

    class FakePlanner:
        async def ainvoke(self, _messages):
            return _execution_plan(is_concluding=True, request_summary=True)

    class FakeModel:
        def with_structured_output(self, _schema):
            return FakePlanner()

    monkeypatch.setattr(agent_builder.memory, "get_task_plan_data", lambda _task_id: stored_plan)
    monkeypatch.setattr(agent_builder.memory, "has_task_plan", lambda _task_id: False)
    monkeypatch.setattr(agent_builder.memory, "save_task_plan", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agent_builder, "create_chat_model", lambda **_kwargs: FakeModel())
    monkeypatch.setattr(agent_builder, "_inject_profile", lambda prompt, _state: prompt)
    monkeypatch.setattr(agent_builder, "_inject_teaching_style", lambda prompt: prompt)

    result = asyncio.run(
        agent_builder.analyzer_node(
            {
                "messages": [HumanMessage(content=message)],
                "task_id": "task-test",
                "session_id": "session-test",
                "conversation_summary": "",
            }
        )
    )

    assert result["plan"].request_plan is True
    assert result["plan"].request_summary is False
    assert result["should_exit"] is False


def test_plan_node_persists_confirmed_draft_as_official_plan(monkeypatch):
    draft = {
        "taskTitle": "RAG 学习",
        "overallSummary": "四周掌握 RAG",
        "plan": ["第 1 天：学习检索基础"],
    }
    stored = {
        "draft_plan": draft,
        PLAN_SESSION_KEY: {
            "status": "await_plan_confirm",
            "draft_plan": draft,
            "messages": [],
        },
    }
    saved_payloads = []

    def save_task_plan(_task_id, payload):
        saved_payloads.append(dict(payload))
        stored.update(payload)
        return stored

    monkeypatch.setattr(agent_builder.memory, "get_task_plan_data", lambda _task_id: stored)
    monkeypatch.setattr(agent_builder.memory, "has_task_plan", lambda _task_id: False)
    monkeypatch.setattr(agent_builder.memory, "load_session", lambda _session_id: None)
    monkeypatch.setattr(agent_builder.memory, "save_task_plan", save_task_plan)
    monkeypatch.setattr(
        agent_builder.memory,
        "save_session",
        lambda _state, **_kwargs: "",
    )
    monkeypatch.setattr(agent_builder.context, "manage_memory", lambda _state: ("", 0))

    result = asyncio.run(
        agent_builder.plan_node(
            {
                "messages": [HumanMessage(content="确认计划")],
                "task_id": "task-test",
                "session_id": "session-test",
                "conversation_summary": "",
                "summarized_msg_count": 0,
                "plan": _execution_plan(request_plan=True),
            }
        )
    )

    assert result["plan_handled"] is True
    assert stored["taskTitle"] == draft["taskTitle"]
    assert stored["draft_plan"] is None
    assert stored[PLAN_SESSION_KEY]["status"] == "idle"
    assert any(payload.get("taskTitle") == draft["taskTitle"] for payload in saved_payloads)
