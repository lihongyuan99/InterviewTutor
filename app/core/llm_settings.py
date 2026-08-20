"""Persistent, user-editable LLM provider settings.

The browser never receives a stored API key.  An empty ``api_key`` in an
update means "keep the existing secret", which lets the settings UI edit the
rest of a provider without asking the user to paste the key again.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import settings as env_settings


LLMProtocol = Literal["openai_compatible", "anthropic", "openai_responses"]
TutorStyle = Literal["socratic", "direct", "interactive", "custom"]


TUTOR_STYLE_INSTRUCTIONS: dict[TutorStyle, str] = {
    "socratic": (
        "采用苏格拉底式教学：先判断学习者已经理解到哪一步，再用循序渐进的提问和提示"
        "引导其自行发现答案；必要时给出关键线索，但不要一开始就包办完整推理。每轮最多提出一个核心问题。"
    ),
    "direct": (
        "采用直接讲解型教学：优先给出清晰结论，再分步骤解释关键概念、依据和例子；少用反问，"
        "除非用户明确要求测验或追问，否则不要用问题代替答案。"
    ),
    "interactive": (
        "采用问答互动型教学：先做简短讲解，再用一个小问题或选择题确认理解，根据学习者的回答"
        "继续补充或纠正；保持节奏轻快，一次只推进一个知识点。"
    ),
    "custom": "",
}


class ModelEntry(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)


class ProviderConfig(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    protocol: LLMProtocol = "openai_compatible"
    api_key: str = ""
    api_base_url: str = ""
    models: list[ModelEntry] = Field(default_factory=list)
    active_model: str = ""
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=2000, ge=1, le=200000)


class TutorPreferences(BaseModel):
    style: TutorStyle = "socratic"
    custom_prompt: str = Field(default="", max_length=4000)


class LLMSettings(BaseModel):
    active_provider_id: str
    providers: list[ProviderConfig]
    tutor_preferences: TutorPreferences = Field(default_factory=TutorPreferences)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = Path(
    os.getenv(
        "INTERVIEW_TUTOR_LLM_SETTINGS_PATH",
        str(PROJECT_ROOT / "memory" / "llm_settings.json"),
    )
)
_settings_lock = threading.RLock()


def _default_settings() -> LLMSettings:
    api_key = env_settings.DEEPSEEK_API_KEY or env_settings.OPENAI_API_KEY
    if env_settings.DEEPSEEK_API_KEY:
        provider_name = "DeepSeek"
        provider_id = "deepseek-official"
        base_url = "https://api.deepseek.com/v1"
        model_id = env_settings.MODEL_NAME or "deepseek-chat"
        model_name = "DeepSeek Chat" if model_id == "deepseek-chat" else model_id
    else:
        provider_name = "OpenAI"
        provider_id = "openai"
        base_url = "https://api.openai.com/v1"
        model_id = env_settings.MODEL_NAME or "gpt-4o-mini"
        model_name = model_id

    provider = ProviderConfig(
        id=provider_id,
        name=provider_name,
        protocol="openai_compatible",
        api_key=api_key,
        api_base_url=base_url,
        models=[ModelEntry(id=model_id, name=model_name)],
        active_model=model_id,
        temperature=0.7,
        max_tokens=2000,
    )
    return LLMSettings(active_provider_id=provider.id, providers=[provider])


def _clean_provider(provider: ProviderConfig) -> ProviderConfig:
    provider.id = provider.id.strip()
    provider.name = provider.name.strip()
    provider.api_key = provider.api_key.strip()
    provider.api_base_url = provider.api_base_url.strip().rstrip("/")
    provider.active_model = provider.active_model.strip()
    provider.models = [
        ModelEntry(id=model.id.strip(), name=model.name.strip())
        for model in provider.models
        if model.id.strip() and model.name.strip()
    ]
    return provider


def validate_settings(value: LLMSettings) -> LLMSettings:
    if not value.providers:
        raise ValueError("至少需要保留一个模型服务")

    provider_ids: set[str] = set()
    for provider in value.providers:
        _clean_provider(provider)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", provider.id):
            raise ValueError(f"服务 ID 格式无效：{provider.id}")
        if provider.id in provider_ids:
            raise ValueError(f"服务 ID 重复：{provider.id}")
        provider_ids.add(provider.id)

        if not provider.models:
            raise ValueError(f"{provider.name} 至少需要配置一个模型")
        model_ids = [model.id for model in provider.models]
        if len(model_ids) != len(set(model_ids)):
            raise ValueError(f"{provider.name} 中存在重复的模型 ID")
        if provider.active_model not in model_ids:
            provider.active_model = model_ids[0]

    if value.active_provider_id not in provider_ids:
        raise ValueError("当前启用的模型服务不存在")
    value.tutor_preferences.custom_prompt = (
        value.tutor_preferences.custom_prompt.strip()
    )
    return value


def load_llm_settings() -> LLMSettings:
    with _settings_lock:
        if not SETTINGS_PATH.exists():
            return _default_settings()
        try:
            raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            return validate_settings(LLMSettings.model_validate(raw))
        except Exception as exc:
            raise ValueError(f"模型配置文件无效：{exc}") from exc


def _secret_hint(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "••••"
    return f"{secret[:3]}••••{secret[-4:]}"


def public_settings(value: LLMSettings | None = None) -> dict:
    current = value or load_llm_settings()
    result = current.model_dump()
    for provider in result["providers"]:
        secret = provider.get("api_key", "")
        provider["api_key"] = ""
        provider["api_key_configured"] = bool(secret)
        provider["api_key_hint"] = _secret_hint(secret)
    return result


def save_llm_settings(incoming: LLMSettings) -> LLMSettings:
    """Validate and persist settings while preserving omitted secrets."""

    with _settings_lock:
        try:
            current = load_llm_settings()
        except ValueError:
            current = _default_settings()
        current_secrets = {provider.id: provider.api_key for provider in current.providers}

        # Preserve the teaching preference when an older client saves only the
        # model-provider fields.
        if "tutor_preferences" not in incoming.model_fields_set:
            incoming.tutor_preferences = current.tutor_preferences.model_copy()

        for provider in incoming.providers:
            if not provider.api_key.strip():
                provider.api_key = current_secrets.get(provider.id, "")

        validated = validate_settings(incoming)
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = SETTINGS_PATH.with_name(
            f".{SETTINGS_PATH.name}.{uuid.uuid4().hex}.tmp"
        )
        temporary_path.write_text(
            json.dumps(validated.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            os.chmod(temporary_path, 0o600)
        except OSError:
            pass
        temporary_path.replace(SETTINGS_PATH)
        return validated


def active_provider(value: LLMSettings | None = None) -> ProviderConfig:
    current = value or load_llm_settings()
    for provider in current.providers:
        if provider.id == current.active_provider_id:
            return provider
    raise ValueError("当前启用的模型服务不存在")


def tutor_style_instruction(value: LLMSettings | None = None) -> str:
    """Return the currently selected teaching-style instruction.

    A blank custom prompt intentionally falls back to the Socratic preset so a
    partially edited setting never removes all teaching guidance.
    """

    current = value or load_llm_settings()
    preferences = current.tutor_preferences
    if preferences.style == "custom":
        return (
            preferences.custom_prompt.strip()
            or TUTOR_STYLE_INSTRUCTIONS["socratic"]
        )
    return TUTOR_STYLE_INSTRUCTIONS[preferences.style]
