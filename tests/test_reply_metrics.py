import asyncio
import time
import uuid

from langchain_core.messages import AIMessage, HumanMessage, messages_to_dict
from langchain_core.outputs import ChatGeneration, LLMResult

from app.core import memory
from app.core.reply_metrics import (
    ReplyMetricsCallback,
    get_active_reply_metrics_callback,
)
from app.api import chat


def _llm_result(message: AIMessage) -> LLMResult:
    return LLMResult(generations=[[ChatGeneration(message=message)]])


def test_reply_metrics_callback_aggregates_and_deduplicates_runs():
    callback = ReplyMetricsCallback()
    first_run = uuid.uuid4()
    first_result = _llm_result(
        AIMessage(
            content="first",
            usage_metadata={
                "input_tokens": 10,
                "output_tokens": 4,
                "total_tokens": 14,
            },
        )
    )
    second_result = _llm_result(
        AIMessage(
            content="second",
            response_metadata={
                "token_usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 3,
                    "total_tokens": 10,
                }
            },
        )
    )

    callback.on_llm_end(first_result, run_id=first_run)
    callback.on_llm_end(first_result, run_id=first_run)
    callback.on_llm_end(second_result, run_id=uuid.uuid4())
    metrics = callback.snapshot(time.perf_counter() - 0.01)

    assert metrics.elapsed_ms >= 10
    assert metrics.input_tokens == 17
    assert metrics.output_tokens == 7
    assert metrics.total_tokens == 24
    assert metrics.llm_calls == 2


def test_model_end_event_usage_is_counted_and_deduplicated():
    callback = ReplyMetricsCallback()
    run_id = uuid.uuid4()
    message = AIMessage(
        content="event output",
        usage_metadata={
            "input_tokens": 667,
            "output_tokens": 810,
            "total_tokens": 1477,
        },
    )

    callback.record_llm_end({}, run_id=run_id)
    chat._record_model_metrics(
        {
            "event": "on_chat_model_end",
            "run_id": run_id,
            "data": {"output": message},
        },
        callback,
    )
    callback.on_llm_end(_llm_result(message), run_id=run_id)
    metrics = callback.snapshot(time.perf_counter())

    assert metrics.input_tokens == 667
    assert metrics.output_tokens == 810
    assert metrics.total_tokens == 1477
    assert metrics.llm_calls == 1


def test_non_stream_invoke_binds_metrics_context(monkeypatch):
    final_state = {
        "messages": [HumanMessage(content="question"), AIMessage(content="answer")],
        "should_exit": False,
    }
    callback = ReplyMetricsCallback()

    class FakeGraph:
        async def ainvoke(self, state, **kwargs):
            assert get_active_reply_metrics_callback() is callback
            assert kwargs["config"]["callbacks"] == [callback]
            callback.record_llm_end(
                AIMessage(
                    content="analysis",
                    usage_metadata={
                        "input_tokens": 25,
                        "output_tokens": 5,
                        "total_tokens": 30,
                    },
                ),
                run_id="analyzer-run",
            )
            return final_state

    monkeypatch.setattr(chat, "agent_graph", FakeGraph())
    result, reply, is_concluded = asyncio.run(
        chat._invoke_agent({"session_id": "fake-session"}, callback)
    )
    metrics = callback.snapshot(time.perf_counter())

    assert result == final_state
    assert reply == "answer"
    assert not is_concluded
    assert metrics.total_tokens == 30
    assert metrics.llm_calls == 1


def test_reply_metrics_are_persisted_and_returned_with_history(tmp_path, monkeypatch):
    session_id = "task_metrics__20260825__120000"
    monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
    session_data = {
        "session_id": session_id,
        "task_id": "task_metrics",
        "last_updated": "2026-08-25T12:00:00",
        "topic": "Metrics",
        "conversation_summary": "",
        "summarized_msg_count": 0,
        "messages": messages_to_dict(
            [HumanMessage(content="question"), AIMessage(content="answer")]
        ),
    }
    memory.file_io.save_json(session_data, memory._get_session_path(session_id))
    metrics = {
        "elapsed_ms": 1234,
        "input_tokens": 100,
        "output_tokens": 25,
        "total_tokens": 125,
        "llm_calls": 3,
    }

    assert memory.attach_reply_metrics(session_id, metrics)

    history = memory.get_session_messages(session_id)
    assert history is not None
    assert history["messages"][-1]["metrics"] == metrics
