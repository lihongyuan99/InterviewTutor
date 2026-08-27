import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.core import llm_factory
from app.core.reply_metrics import ReplyMetricsCallback, bind_reply_metrics_callback


class _FakeChatOpenAI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _provider(
    base_url: str,
    protocol: str = "openai_compatible",
    *,
    max_tokens: int = 2000,
):
    return SimpleNamespace(
        name="test-provider",
        api_key="test-key",
        protocol=protocol,
        active_model="test-model",
        temperature=0.7,
        max_tokens=max_tokens,
        api_base_url=base_url,
    )


def _create_model(monkeypatch, provider, **model_kwargs):
    monkeypatch.setattr(llm_factory, "load_llm_settings", lambda: object())
    monkeypatch.setattr(llm_factory, "active_provider", lambda _settings: provider)
    fake_module = ModuleType("langchain_openai")
    fake_module.ChatOpenAI = _FakeChatOpenAI
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)
    return llm_factory.create_chat_model(**model_kwargs)


@pytest.fixture(autouse=True)
def _reset_shared_http_clients():
    llm_factory._http_clients.clear()
    yield
    clients = list(llm_factory._http_clients.values())
    llm_factory._http_clients.clear()
    for sync_client, async_client in clients:
        close = getattr(sync_client, "close", None)
        if close:
            close()
        aclose = getattr(async_client, "aclose", None)
        if aclose:
            asyncio.run(aclose())


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/v1",
        "http://service.localhost:8000/v1",
        "http://127.0.0.1:8000/v1",
        "http://127.1.2.3:8000/v1",
        "http://[::1]:8000/v1",
    ],
)
def test_is_loopback_url_accepts_loopback_hosts(url):
    assert llm_factory._is_loopback_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1",
        "http://192.168.1.10:8000/v1",
        "http://localhost.example.com/v1",
        "not-a-url",
        "",
    ],
)
def test_is_loopback_url_rejects_non_loopback_hosts(url):
    assert not llm_factory._is_loopback_url(url)


@pytest.mark.parametrize("protocol", ["openai_compatible", "openai_responses"])
def test_local_openai_provider_disables_environment_proxy(monkeypatch, protocol):
    created_clients = []

    class FakeClient:
        def __init__(self, **kwargs):
            created_clients.append(("sync", kwargs))

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            created_clients.append(("async", kwargs))

    monkeypatch.setattr(llm_factory.httpx, "Client", FakeClient)
    monkeypatch.setattr(llm_factory.httpx, "AsyncClient", FakeAsyncClient)

    model = _create_model(
        monkeypatch,
        _provider("http://127.0.0.1:8000/v1", protocol=protocol),
    )

    assert created_clients == [
        ("sync", {"trust_env": False}),
        ("async", {"trust_env": False}),
    ]
    assert isinstance(model.kwargs["http_client"], FakeClient)
    assert isinstance(model.kwargs["http_async_client"], FakeAsyncClient)


def test_cloud_openai_provider_keeps_environment_proxy_enabled(monkeypatch):
    created_clients = []

    class FakeClient:
        def __init__(self, **kwargs):
            created_clients.append(("sync", kwargs))

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            created_clients.append(("async", kwargs))

    monkeypatch.setattr(llm_factory.httpx, "Client", FakeClient)
    monkeypatch.setattr(llm_factory.httpx, "AsyncClient", FakeAsyncClient)

    model = _create_model(
        monkeypatch,
        _provider("https://api.openai.com/v1"),
    )

    assert created_clients == [
        ("sync", {"trust_env": True}),
        ("async", {"trust_env": True}),
    ]
    assert isinstance(model.kwargs["http_client"], FakeClient)
    assert isinstance(model.kwargs["http_async_client"], FakeAsyncClient)


def test_openai_provider_reuses_clients_for_the_same_endpoint(monkeypatch):
    created_clients = []

    class FakeClient:
        def __init__(self, **kwargs):
            created_clients.append(("sync", kwargs))

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            created_clients.append(("async", kwargs))

    monkeypatch.setattr(llm_factory.httpx, "Client", FakeClient)
    monkeypatch.setattr(llm_factory.httpx, "AsyncClient", FakeAsyncClient)
    provider = _provider("https://api.openai.com/v1")

    first = _create_model(monkeypatch, provider)
    second = _create_model(monkeypatch, provider)

    assert created_clients == [
        ("sync", {"trust_env": True}),
        ("async", {"trust_env": True}),
    ]
    assert first.kwargs["http_client"] is second.kwargs["http_client"]
    assert first.kwargs["http_async_client"] is second.kwargs["http_async_client"]


def test_local_router_disables_thinking_and_uses_role_token_cap(monkeypatch):
    model = _create_model(
        monkeypatch,
        _provider("http://127.0.0.1:8000/v1", max_tokens=4096),
        role="router",
        max_retries=0,
    )

    assert model.kwargs["max_retries"] == 0
    assert model.kwargs["extra_body"] == {
        "max_tokens": 256,
        "chat_template_kwargs": {"enable_thinking": False},
    }


def test_local_tutor_keeps_default_thinking_and_uses_role_token_cap(monkeypatch):
    model = _create_model(
        monkeypatch,
        _provider("http://127.0.0.1:8000/v1", max_tokens=4096),
        role="tutor",
    )

    assert model.kwargs["extra_body"] == {"max_tokens": 2000}


def test_cloud_role_cap_does_not_send_omlx_thinking_parameter(monkeypatch):
    model = _create_model(
        monkeypatch,
        _provider("https://api.openai.com/v1", max_tokens=4096),
        role="aggregator",
    )

    assert model.kwargs["extra_body"] == {"max_tokens": 1600}


def test_openai_provider_can_enable_streaming(monkeypatch):
    model = _create_model(
        monkeypatch,
        _provider("https://api.openai.com/v1"),
        streaming=True,
    )

    assert model.kwargs["streaming"] is True
    assert model.kwargs["stream_usage"] is True


def test_request_metrics_callback_is_attached_to_nested_models(monkeypatch):
    callback = ReplyMetricsCallback()

    with bind_reply_metrics_callback(callback):
        model = _create_model(
            monkeypatch,
            _provider("https://api.openai.com/v1"),
        )

    assert model.kwargs["callbacks"] == [callback]

    model_without_context = _create_model(
        monkeypatch,
        _provider("https://api.openai.com/v1"),
    )
    assert "callbacks" not in model_without_context.kwargs
