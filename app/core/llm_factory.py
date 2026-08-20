"""Create LangChain chat models from the active user configuration."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from app.core.llm_settings import active_provider, load_llm_settings


class ModelConfigurationError(RuntimeError):
    """Raised when the selected provider cannot be initialized."""


def create_chat_model(
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
):
    provider = active_provider(load_llm_settings())
    if not provider.api_key:
        raise ModelConfigurationError(
            f"模型服务“{provider.name}”尚未配置 API 密钥，请在系统设置中补充"
        )

    selected_temperature = (
        provider.temperature if temperature is None else temperature
    )
    selected_max_tokens = provider.max_tokens if max_tokens is None else max_tokens

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
            "use_responses_api": provider.protocol == "openai_responses",
            "max_retries": 2,
        }
        if provider.protocol == "openai_responses":
            # ChatOpenAI maps this alias to Responses API's max_output_tokens.
            kwargs["max_tokens"] = selected_max_tokens
        else:
            # Keep Chat Completions compatibility for providers that implement
            # max_tokens but do not yet accept max_completion_tokens.
            kwargs["extra_body"] = {"max_tokens": selected_max_tokens}
        if provider.api_base_url:
            kwargs["base_url"] = provider.api_base_url
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
            "max_retries": 2,
        }
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
