import asyncio
import json
import time

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from app.core import agent_builder, memory
from app.core.models import ExecutionPlan
from app.core.task_plan import PLAN_SESSION_KEY


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
    "text",
    [
        "什么是 RAG？",
        "请解释一下 Transformer 的工作原理",
        "哈希表为什么查询很快？",
        "Python 的生成器和迭代器有何区别",
    ],
)
def test_high_confidence_knowledge_questions_use_fast_route(text):
    assert agent_builder._high_confidence_tutor_question(
        [HumanMessage(content=text)]
    )


@pytest.mark.parametrize(
    "text",
    [
        "帮我制定四周学习计划？",
        "总结一下刚才的内容？",
        "我觉得哈希表是数组，你评价一下？",
        "哈希表就是数组，对吗？",
        "请检查我的回答有什么问题？",
        "接下来考考我？",
        "搜索一下今天最新的 AI 新闻？",
    ],
)
def test_ambiguous_or_multimodule_requests_do_not_use_fast_route(text):
    assert not agent_builder._high_confidence_tutor_question(
        [HumanMessage(content=text)]
    )


def test_reply_to_an_assistant_question_does_not_use_fast_route():
    messages = [
        AIMessage(content="你认为哈希表为什么查询很快？"),
        HumanMessage(content="因为可以直接找到下标？"),
    ]

    assert not agent_builder._high_confidence_tutor_question(messages)


def test_route_selects_direct_tutor_only_for_non_search_tutor_plan():
    plan = _execution_plan()

    assert (
        agent_builder.route_from_analyzer(
            {"plan": plan, "_requires_search": False}
        )
        == "direct_tutor"
    )
    assert (
        agent_builder.route_from_analyzer(
            {"plan": plan, "_requires_search": True}
        )
        == "parallel_workers"
    )
    assert (
        agent_builder.route_from_analyzer(
            {"plan": _execution_plan(needs_judge=True)}
        )
        == "parallel_workers"
    )


def _patch_analyzer_dependencies(monkeypatch, stored_plan=None):
    monkeypatch.setattr(
        agent_builder.memory,
        "get_task_plan_data",
        lambda _task_id: stored_plan or {},
    )
    monkeypatch.setattr(
        agent_builder.memory,
        "has_task_plan",
        lambda _task_id: False,
    )
    monkeypatch.setattr(
        agent_builder.memory,
        "save_task_plan",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        agent_builder,
        "_inject_profile",
        lambda prompt, _state: prompt,
    )
    monkeypatch.setattr(
        agent_builder,
        "_inject_teaching_style",
        lambda prompt: prompt,
    )


def test_analyzer_rule_route_skips_classifier_model(monkeypatch):
    _patch_analyzer_dependencies(monkeypatch)
    monkeypatch.setattr(agent_builder.settings, "CHAT_FAST_ROUTE_ENABLED", True)

    def unexpected_model(**_kwargs):
        raise AssertionError("high-confidence question must skip Analyzer LLM")

    monkeypatch.setattr(agent_builder, "create_chat_model", unexpected_model)
    result = asyncio.run(
        agent_builder.analyzer_node(
            {
                "messages": [HumanMessage(content="什么是向量数据库？")],
                "task_id": "task-test",
                "session_id": "session-test",
                "conversation_summary": "",
            }
        )
    )

    assert result["_route_source"] == "rule"
    assert agent_builder.route_from_analyzer(result) == "direct_tutor"


def test_analyzer_timeout_falls_back_within_total_budget(monkeypatch):
    _patch_analyzer_dependencies(monkeypatch)
    monkeypatch.setattr(agent_builder.settings, "CHAT_FAST_ROUTE_ENABLED", False)
    monkeypatch.setattr(agent_builder.settings, "CHAT_ROUTER_TIMEOUT_SECONDS", 0.03)
    create_kwargs = []

    class SlowPlanner:
        async def ainvoke(self, _messages):
            await asyncio.sleep(0.2)
            return _execution_plan(needs_judge=True)

    class FakeModel:
        def with_structured_output(self, _schema):
            return SlowPlanner()

    def create_model(**kwargs):
        create_kwargs.append(kwargs)
        return FakeModel()

    monkeypatch.setattr(agent_builder, "create_chat_model", create_model)
    started_at = time.perf_counter()
    result = asyncio.run(
        agent_builder.analyzer_node(
            {
                "messages": [HumanMessage(content="继续")],
                "task_id": "task-test",
                "session_id": "session-test",
                "conversation_summary": "",
            }
        )
    )

    assert time.perf_counter() - started_at < 0.15
    assert result["_route_source"] == "timeout_fallback"
    assert result["plan"] == _execution_plan()
    assert create_kwargs == [
        {"temperature": 0.1, "role": "router", "max_retries": 0}
    ]


def test_active_plan_timeout_returns_to_plan_with_shared_budget(monkeypatch):
    stored_plan = {
        PLAN_SESSION_KEY: {
            "status": "collecting",
            "messages": [
                {"role": "assistant", "content": "你每天能投入多少时间？"}
            ],
        }
    }
    _patch_analyzer_dependencies(monkeypatch, stored_plan)
    monkeypatch.setattr(agent_builder.settings, "CHAT_FAST_ROUTE_ENABLED", True)
    monkeypatch.setattr(agent_builder.settings, "CHAT_ROUTER_TIMEOUT_SECONDS", 0.05)

    async def inconclusive_plan_router(*_args, **_kwargs):
        await asyncio.sleep(0.03)
        return None

    class SlowPlanner:
        async def ainvoke(self, _messages):
            await asyncio.sleep(0.2)
            return _execution_plan()

    class FakeModel:
        def with_structured_output(self, _schema):
            return SlowPlanner()

    monkeypatch.setattr(
        agent_builder,
        "_is_plan_related_llm",
        inconclusive_plan_router,
    )
    monkeypatch.setattr(
        agent_builder,
        "create_chat_model",
        lambda **_kwargs: FakeModel(),
    )

    started_at = time.perf_counter()
    result = asyncio.run(
        agent_builder.analyzer_node(
            {
                "messages": [HumanMessage(content="大概一小时")],
                "task_id": "task-test",
                "session_id": "session-test",
                "conversation_summary": "",
            }
        )
    )

    assert time.perf_counter() - started_at < 0.15
    assert result["_route_source"] == "timeout_fallback"
    assert result["plan"].request_plan is True
    assert agent_builder.route_from_analyzer(result) == "plan"


def test_direct_tutor_streams_with_one_tutor_model_and_saves_raw_reply(
    monkeypatch,
):
    calls = []
    saves = []

    class FakeTutor:
        async def astream(self, _messages, config=None):
            assert config is None
            yield AIMessageChunk(content="直接")
            yield AIMessageChunk(content="回答")

    def create_model(**kwargs):
        calls.append(kwargs)
        return FakeTutor()

    monkeypatch.setattr(agent_builder, "create_chat_model", create_model)
    monkeypatch.setattr(
        agent_builder.context,
        "build_context",
        lambda state, _prompt: state["messages"],
    )
    monkeypatch.setattr(
        agent_builder,
        "_inject_profile",
        lambda prompt, _state: prompt,
    )
    monkeypatch.setattr(
        agent_builder,
        "_inject_teaching_style",
        lambda prompt: prompt,
    )
    monkeypatch.setattr(
        agent_builder.memory,
        "get_task_plan_data",
        lambda _task_id: {},
    )

    def save_session(state, **kwargs):
        saves.append((state, kwargs))
        return "session.json"

    monkeypatch.setattr(agent_builder.memory, "save_session", save_session)
    result = asyncio.run(
        agent_builder.direct_tutor_node(
            {
                "messages": [HumanMessage(content="什么是 RAG？")],
                "task_id": "task-test",
                "session_id": "session-test",
                "current_topic": "RAG",
                "conversation_summary": "",
                "summarized_msg_count": 0,
                "plan": _execution_plan(),
                "_cache_trace": {},
            }
        )
    )

    assert calls == [{"role": "tutor", "streaming": True}]
    assert result["messages"][0].content == "直接回答"
    assert saves[0][1] == {"index_for_rag": False}
    assert saves[0][0]["messages"][-1].content == "直接回答"


def test_stream_endpoint_forwards_direct_tutor_deltas_without_fallback_duplicates(
    monkeypatch,
):
    from app.api import chat

    plan = _execution_plan()

    class FakeGraph:
        async def astream_events(self, _state, **_kwargs):
            yield {
                "event": "on_chain_end",
                "metadata": {"langgraph_node": "analyzer"},
                "data": {
                    "output": {
                        "plan": plan,
                        "_route_source": "rule",
                        "_requires_search": False,
                    }
                },
            }
            yield {
                "event": "on_chain_start",
                "metadata": {"langgraph_node": "direct_tutor"},
                "data": {},
            }
            yield {
                "event": "on_chat_model_stream",
                "metadata": {"langgraph_node": "direct_tutor"},
                "data": {"chunk": AIMessage(content="第一段")},
            }
            yield {
                "event": "on_chat_model_stream",
                "metadata": {"langgraph_node": "direct_tutor"},
                "data": {"chunk": AIMessage(content="第二段")},
            }
            yield {
                "event": "on_chain_end",
                "metadata": {"langgraph_node": "direct_tutor"},
                "data": {"output": {"messages": [AIMessage(content="第一段第二段")]}},
            }

    async def no_maintenance(**_kwargs):
        return None

    monkeypatch.setattr(chat, "agent_graph", FakeGraph())
    monkeypatch.setattr(chat.memory, "load_session", lambda _session_id: None)
    monkeypatch.setattr(chat.memory, "get_task_plan_data", lambda _task_id: {})
    monkeypatch.setattr(chat.memory, "has_task_plan", lambda _task_id: False)
    monkeypatch.setattr(chat.memory, "attach_reply_metrics", lambda *_args: True)
    monkeypatch.setattr(chat, "_dispatch_reply_maintenance", no_maintenance)

    async def collect_events():
        response = await chat.chat_stream_endpoint(
            chat.ChatRequest(
                task_id="task-test",
                message="什么是 RAG？",
                topic="RAG",
            )
        )
        payload = ""
        async for chunk in response.body_iterator:
            payload += chunk.decode() if isinstance(chunk, bytes) else chunk
        return [json.loads(line) for line in payload.splitlines() if line]

    events = asyncio.run(collect_events())
    deltas = [event["data"]["text"] for event in events if event["event"] == "delta"]

    assert deltas == ["第一段", "第二段"]
    assert [event["event"] for event in events].count("done") == 1
    assert not any(event["event"] == "error" for event in events)


def test_background_summary_preserves_newer_messages_and_reply_metrics(
    tmp_path,
    monkeypatch,
):
    session_id = "task-latency__20260825__120000"
    original_messages = [
        HumanMessage(content="旧问题"),
        AIMessage(content="旧回答"),
        HumanMessage(content="当前问题"),
        AIMessage(content="当前回答"),
    ]
    monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
    monkeypatch.setattr(memory, "maybe_auto_title_task", lambda *_args: None)
    monkeypatch.setattr(memory, "_index_session_for_rag", lambda **_kwargs: None)
    monkeypatch.setattr(
        memory,
        "_update_learning_profile_from_messages",
        lambda *_args, **_kwargs: None,
    )
    memory._MAINTAINING_SESSIONS.clear()
    memory.save_session(
        {
            "session_id": session_id,
            "task_id": "task-latency",
            "current_topic": "Latency",
            "conversation_summary": "",
            "summarized_msg_count": 0,
            "messages": original_messages,
        },
        index_for_rag=False,
    )
    memory.attach_reply_metrics(
        session_id,
        {
            "elapsed_ms": 1200,
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "llm_calls": 1,
        },
    )

    def compress_while_next_reply_arrives(_state):
        newer_state = memory.load_session(session_id)
        newer_state["messages"].extend(
            [HumanMessage(content="新问题"), AIMessage(content="新回答")]
        )
        memory.save_session(newer_state, index_for_rag=False)
        return "后台摘要", 2

    from app.core import context_rag

    monkeypatch.setattr(context_rag, "manage_memory", compress_while_next_reply_arrives)

    assert memory.run_session_maintenance(session_id)
    persisted = memory.get_session_messages(session_id)
    raw_state = memory.load_session(session_id)

    assert [message["content"] for message in persisted["messages"]][-2:] == [
        "新问题",
        "新回答",
    ]
    assert persisted["messages"][3]["metrics"]["total_tokens"] == 15
    assert raw_state["conversation_summary"] == "后台摘要"
    assert raw_state["summarized_msg_count"] == 2


def test_background_summary_rejects_a_changed_message_prefix(tmp_path, monkeypatch):
    session_id = "task-latency__20260825__120001"
    monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
    monkeypatch.setattr(memory, "maybe_auto_title_task", lambda *_args: None)
    monkeypatch.setattr(memory, "_index_session_for_rag", lambda **_kwargs: None)
    monkeypatch.setattr(
        memory,
        "_update_learning_profile_from_messages",
        lambda *_args, **_kwargs: None,
    )
    memory._MAINTAINING_SESSIONS.clear()
    memory.save_session(
        {
            "session_id": session_id,
            "task_id": "task-latency",
            "current_topic": "Latency",
            "conversation_summary": "原摘要",
            "summarized_msg_count": 0,
            "messages": [
                HumanMessage(content="原问题"),
                AIMessage(content="原回答"),
                HumanMessage(content="当前问题"),
                AIMessage(content="当前回答"),
            ],
        },
        index_for_rag=False,
    )

    def compress_after_history_was_rewritten(_state):
        rewritten = memory.load_session(session_id)
        rewritten["messages"][0] = HumanMessage(content="被改写的问题")
        memory.save_session(rewritten, index_for_rag=False)
        return "不应提交的摘要", 2

    from app.core import context_rag

    monkeypatch.setattr(context_rag, "manage_memory", compress_after_history_was_rewritten)

    assert memory.run_session_maintenance(session_id)
    persisted = memory.load_session(session_id)

    assert persisted["messages"][0].content == "被改写的问题"
    assert persisted["conversation_summary"] == "原摘要"
    assert persisted["summarized_msg_count"] == 0
