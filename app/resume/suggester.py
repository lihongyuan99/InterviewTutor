"""简历优化建议。

调用 LLM 从 STAR 完整性、量化成果、技术栈表述、措辞、缺失项
五个类别给出改进建议，返回按 severity 排序的建议列表。
"""

from __future__ import annotations

import json
from typing import List

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm_factory import create_chat_model, message_text
from app.resume.models import Resume, ResumeSuggestion
from app.resume.prompts import SUGGEST_SYSTEM_PROMPT, SUGGEST_USER_PROMPT

# 建议条数上限
_SUGGEST_LIMIT = 8

# 严重程度排序权重（高在前）
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _summarize_resume(resume: Resume) -> str:
    """把简历压缩为供建议模型阅读的摘要。"""
    lines = []
    if resume.summary:
        lines.append(f"个人简介：{resume.summary}")
    if resume.skills:
        lines.append("技能：" + "、".join(s.name for s in resume.skills))
    for p in resume.projects:
        seg = [f"项目「{p.name}」"]
        if p.description:
            seg.append(p.description)
        if p.tech_stack:
            seg.append("技术栈：" + "、".join(p.tech_stack))
        if p.metrics:
            seg.append("成果：" + "、".join(p.metrics))
        else:
            seg.append("（无量化成果）")
        lines.append(" ".join(seg))
    for w in resume.works:
        seg = [f"工作「{w.company} {w.role}」"]
        if w.description:
            seg.append(w.description)
        lines.append(" ".join(seg))
    return "\n".join(lines) if lines else "（简历内容为空）"


async def suggest(
    resume: Resume, target_role: str = "", limit: int = _SUGGEST_LIMIT
) -> List[ResumeSuggestion]:
    """生成简历优化建议。"""
    role = target_role or resume.target_role or "AI Agent / LLM 应用工程师"
    companies = "、".join(resume.target_companies) or "未指定"

    model = create_chat_model(temperature=0.2, role="general", max_tokens=2000)
    system_prompt = SUGGEST_SYSTEM_PROMPT.format(limit=limit)
    user_prompt = SUGGEST_USER_PROMPT.format(
        target_role=role,
        target_companies=companies,
        resume_summary=_summarize_resume(resume),
    )

    raw = await model.ainvoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    text = message_text(raw).strip()
    if text.startswith("```"):
        text = text.strip("`").replace("json", "", 1).strip()

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return []

    suggestions: List[ResumeSuggestion] = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        suggestions.append(
            ResumeSuggestion(
                category=item.get("category", ""),
                severity=item.get("severity", "medium"),
                target=item.get("target", ""),
                advice=item.get("advice", ""),
            )
        )

    suggestions.sort(
        key=lambda s: _SEVERITY_ORDER.get(s.severity, 9)
    )
    return suggestions[:limit]
