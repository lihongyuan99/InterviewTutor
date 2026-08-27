"""简历结构化解析。

把 ``extract.py`` 抽取出的纯文本，通过 LLM 结构化输出解析为
:class:`~app.resume.models.Resume`。

遵循设计文档「缺失字段不编造」的原则：解析提示词明确要求留空而非臆造。

本模块在解析失败时抛出 :class:`ResumeParseError`，并允许传入解析警告，
供上层提示用户。
"""

from __future__ import annotations

from typing import List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm_factory import create_chat_model, message_text
from app.resume.models import Resume
from app.resume.prompts import RESUME_PARSE_SYSTEM_PROMPT, RESUME_PARSE_USER_PROMPT


class ResumeParseError(RuntimeError):
    """简历结构化解析失败。"""


def _build_resume(resume_id: str, raw_text: str, parsed: dict) -> Resume:
    """把 LLM 解析出的 dict 组装为 Resume 模型，补齐元信息。"""
    data = dict(parsed or {})
    data.setdefault("resume_id", resume_id)
    data.setdefault("raw_text", raw_text)
    return Resume.model_validate(data)


async def parse_resume(
    raw_text: str,
    *,
    resume_id: str = "",
    source_file: str = "",
    source_type: str = "",
) -> Resume:
    """把简历纯文本解析为结构化 Resume。

    Args:
        raw_text: 抽取出的简历纯文本。
        resume_id: 简历 ID（无则自动为空，由上层回填）。
        source_file: 原始文件相对路径。
        source_type: 来源类型（pdf/docx/md）。

    Returns:
        结构化 Resume。

    Raises:
        ResumeParseError: 模型未配置或解析失败。
    """
    if not raw_text or not raw_text.strip():
        raise ResumeParseError("简历文本为空，无法解析")

    # 简历解析需要输出完整结构化 JSON，不能用 token 受限的 maintenance 角色，
    # 改用 general（无角色级 max_tokens 上限）并显式放宽到 8000，
    # 因为项目 + 实习/工作经历都要提取 tech_stack/metrics/highlights 等字段。
    model = create_chat_model(temperature=0.0, role="general", max_tokens=8000)
    structured = model.with_structured_output(Resume)

    system_prompt = RESUME_PARSE_SYSTEM_PROMPT
    user_prompt = RESUME_PARSE_USER_PROMPT.format(resume_text=raw_text.strip())

    try:
        result = await structured.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        )
    except Exception as exc:  # noqa: BLE001
        raise ResumeParseError(f"简历结构化解析失败：{exc}") from exc

    if result is None:
        raise ResumeParseError("模型未返回结构化解析结果")

    resume = _build_resume(resume_id, raw_text, result)
    if resume.resume_id and not resume_id:
        resume_id = resume.resume_id
    resume.resume_id = resume_id or ""
    resume.source_file = source_file
    resume.source_type = source_type
    return resume


async def parse_resume_plain(raw_text: str) -> Resume:
    """便捷入口：不关心元信息的纯解析（供测试与快速调用）。"""
    return await parse_resume(raw_text)
