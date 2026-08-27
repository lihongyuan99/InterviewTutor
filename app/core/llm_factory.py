"""Create LangChain chat models from the active user configuration."""

from __future__ import annotations

import ipaddress
import threading
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from langchain_core.messages import AIMessage

from app.core.llm_settings import active_provider, load_llm_settings
from app.core.reply_metrics import get_active_reply_metrics_callback


class ModelConfigurationError(RuntimeError):
    """Raised when the selected provider cannot be initialized."""


ModelRole = Literal[
    "general",
    "router",
    "tutor",
    "judge",
    "inquiry",
    "aggregator",
    "chitchat",
    "plan",
    "summary",
    "maintenance",
]


_ROLE_MAX_TOKENS: dict[ModelRole, int | None] = {
    "general": None,
    "router": 256,
    "tutor": 2000,
    "judge": 512,
    "inquiry": 256,
    "aggregator": 1600,
    "chitchat": 256,
    "plan": 2000,
    "summary": 2000,
    "maintenance": 512,
}
_LOCAL_NON_THINKING_ROLES: set[ModelRole] = {
    "router",
    "judge",
    "inquiry",
    "aggregator",
    "chitchat",
    "plan",
    "summary",
    "maintenance",
}

_http_clients_lock = threading.Lock()
_http_clients: dict[tuple[str, bool], tuple[httpx.Client, httpx.AsyncClient]] = {}


def _is_loopback_url(url: str) -> bool:
    """Return whether an HTTP endpoint uses a loopback-only hostname."""

    try:
        hostname = urlparse(url).hostname
    except ValueError:
        return False
    if not hostname:
        return False

    hostname = hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return True

    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _get_http_clients(
    base_url: str,
    *,
    trust_env: bool,
) -> tuple[httpx.Client, httpx.AsyncClient]:
    """Reuse connection pools without sharing request-scoped callbacks."""

    key = (base_url.rstrip("/"), trust_env)
    with _http_clients_lock:
        clients = _http_clients.get(key)
        if clients is None:
            clients = (
                httpx.Client(trust_env=trust_env),
                httpx.AsyncClient(trust_env=trust_env),
            )
            _http_clients[key] = clients
        return clients


async def close_http_clients() -> None:
    """Close all shared clients during application shutdown."""

    with _http_clients_lock:
        clients = list(_http_clients.values())
        _http_clients.clear()

    for sync_client, async_client in clients:
        try:
            sync_client.close()
        except Exception:
            pass
        try:
            await async_client.aclose()
        except Exception:
            pass


def create_chat_model(
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    streaming: bool = False,
    role: ModelRole = "general",
    max_retries: int | None = None,
):
    provider = active_provider(load_llm_settings())
    if not provider.api_key:
        raise ModelConfigurationError(
            f"模型服务“{provider.name}”尚未配置 API 密钥，请在系统设置中补充"
        )

    selected_temperature = (
        provider.temperature if temperature is None else temperature
    )
    token_limits = [provider.max_tokens]
    role_limit = _ROLE_MAX_TOKENS[role]
    if role_limit is not None:
        token_limits.append(role_limit)
    if max_tokens is not None:
        token_limits.append(max_tokens)
    selected_max_tokens = min(token_limits)
    metrics_callback = get_active_reply_metrics_callback()
    selected_max_retries = 2 if max_retries is None else max(0, max_retries)
    is_local = bool(provider.api_base_url) and _is_loopback_url(
        provider.api_base_url
    )

    if provider.protocol in {"openai_compatible", "openai_responses"}:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise ModelConfigurationError(
                "缺少 langchain-openai，无法使用 OpenAI 协议"
            ) from exc

        kwargs: dict[str, Any] = {
            "model": provider.active_model,
            "api_key": provider.api_key,
            "temperature": selected_temperature,
            "streaming": streaming,
            "use_responses_api": provider.protocol == "openai_responses",
            "max_retries": selected_max_retries,
        }
        if metrics_callback is not None:
            kwargs["callbacks"] = [metrics_callback]
        if streaming:
            # Ask OpenAI-compatible streaming servers to include the final
            # usage block so per-reply token accounting remains available.
            kwargs["stream_usage"] = True
        extra_body: dict[str, Any] = {}
        if provider.protocol == "openai_responses":
            # ChatOpenAI maps this alias to Responses API's max_output_tokens.
            kwargs["max_tokens"] = selected_max_tokens
        else:
            # Keep Chat Completions compatibility for providers that implement
            # max_tokens but do not yet accept max_completion_tokens.
            extra_body["max_tokens"] = selected_max_tokens
        if is_local and role in _LOCAL_NON_THINKING_ROLES:
            extra_body["chat_template_kwargs"] = {"enable_thinking": False}
        if extra_body:
            kwargs["extra_body"] = extra_body
        if provider.api_base_url:
            kwargs["base_url"] = provider.api_base_url
            sync_client, async_client = _get_http_clients(
                provider.api_base_url,
                trust_env=not is_local,
            )
            kwargs["http_client"] = sync_client
            kwargs["http_async_client"] = async_client
        return ChatOpenAI(**kwargs)

    if provider.protocol == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:
            raise ModelConfigurationError(
                "缺少 langchain-anthropic，无法使用 Anthropic 协议"
            ) from exc

        kwargs = {
            "model": provider.active_model,
            "api_key": provider.api_key,
            "temperature": selected_temperature,
            "max_tokens": selected_max_tokens,
            "max_retries": selected_max_retries,
            "streaming": streaming,
        }
        if metrics_callback is not None:
            kwargs["callbacks"] = [metrics_callback]
        if provider.api_base_url:
            kwargs["base_url"] = provider.api_base_url
        return ChatAnthropic(**kwargs)

    raise ModelConfigurationError(f"不支持的模型协议：{provider.protocol}")


def message_text(message: Any) -> str:
    """Normalize string and block-based model responses to plain text.

    注意：当 content 是多个 text block（如 OpenAI Responses API 流式输出）时，
    block 之间用换行符连接而不是空字符串，否则会丢失表格/列表等块边界的换行，
    导致前端 Markdown 无法解析表格和列表。
    """

    if message is None:
        return ""

    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")

    chunks: list[str] = []
    for block in content:
        if isinstance(block, str):
            chunks.append(block)
            continue
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type not in {None, "text", "output_text"}:
            continue
        value = block.get("text") or block.get("content")
        if isinstance(value, str):
            chunks.append(value)

    # 用换行连接多个 block，保留块边界处的换行符。
    # 同时避免 block 之间相邻本就带换行时出现多余空行：先 strip 首尾空白，
    # 仅在非空块之间插入换行。
    non_empty = [c for c in chunks if c]
    return "\n".join(c.strip("\n") for c in non_empty)


def ensure_text_ai_message(message: Any) -> AIMessage:
    """Return an AIMessage whose content is safe for the existing app state."""

    content = message_text(message)
    if isinstance(message, AIMessage):
        try:
            message.content = content
            return message
        except Exception:
            pass
    return AIMessage(content=content)
