"""简历 vs 目标公司偏好匹配。

读取 ``knowledge/14-company-preferences/index.md``，提取目标公司的
高频考察维度（表格第一列为维度名），再调用 LLM 结合简历技能/项目
做匹配度评估，输出 :class:`ResumeMatch`。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm_factory import create_chat_model, message_text
from app.resume.models import Resume, ResumeMatch
from app.resume.prompts import MATCH_SYSTEM_PROMPT, MATCH_USER_PROMPT

# 公司偏好源文件（相对项目根）
_COMPANY_PREFS_PATH = Path("knowledge/14-company-preferences/index.md")

# 已知公司别名 -> 标准名（用于模糊匹配用户输入）
_COMPANY_ALIASES = {
    "腾讯": "腾讯",
    "字节": "字节跳动",
    "字节跳动": "字节跳动",
    "抖音": "字节跳动",
    "阿里": "阿里-淘天",
    "阿里巴巴": "阿里-淘天",
    "淘天": "阿里-淘天",
    "淘宝": "淘宝闪购",
    "淘宝闪购": "淘宝闪购",
    "蚂蚁": "蚂蚁集团",
    "蚂蚁集团": "蚂蚁集团",
    "快手": "快手",
    "美团": "美团",
    "百度": "百度",
    "京东": "京东",
    "拼多多": "拼多多",
    "滴滴": "滴滴",
    "携程": "携程",
    "高德": "高德",
    "bilibili": "bilibili",
    "B站": "bilibili",
    "阿里国际": "阿里国际",
}


def _resolve_company(name: str) -> str:
    """把用户输入的公司名归一化为偏好文件中的标准名。"""
    return _COMPANY_ALIASES.get(name.strip(), name.strip())


def _parse_company_dimensions(text: str, company: str) -> List[str]:
    """从公司偏好 Markdown 中提取指定公司的高频维度列表。

    返回按出现顺序（即题量降序）的维度中文名列表。
    """
    # 定位公司章节（## 公司名），直到下一个 ## 为止
    pattern = re.compile(rf"^##\s+{re.escape(company)}\s*[（(].*?[）)]", re.MULTILINE)
    m = pattern.search(text)
    if not m:
        return []

    section_start = m.start()
    next_heading = re.search(r"^##\s+", text[section_start + 1 :], re.MULTILINE)
    section_end = (
        section_start + 1 + next_heading.start()
        if next_heading
        else len(text)
    )
    section = text[section_start:section_end]

    # 提取该章节内所有表格行中的「维度」列（第一列）
    dimensions: List[str] = []
    for line in section.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not cells:
            continue
        first = cells[0]
        # 跳过表头、分隔行、公司列等非维度单元格
        if first in {"维度", "公司", ""}:
            continue
        if re.fullmatch(r":?-{2,}:?", first):
            continue
        if first.startswith("[") and "]" in first:
            # [RAG 与检索](...) -> 取链接文本
            first = first[1 : first.index("]")]
        if first and first not in dimensions:
            dimensions.append(first)
    return dimensions


def _load_company_dimensions(company: str) -> List[str]:
    """读取偏好文件并返回该公司高频维度（可能为空）。"""
    path = _COMPANY_PREFS_PATH
    if not path.exists():
        # 回退到绝对路径（相对当前工作目录）
        alt = Path(__file__).resolve().parent.parent.parent / _COMPANY_PREFS_PATH
        path = alt if alt.exists() else path
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return _parse_company_dimensions(text, company)


async def match_resume(
    resume: Resume,
    target_role: str = "",
    target_company: str = "",
) -> Optional[ResumeMatch]:
    """评估简历与目标公司的匹配度。

    Args:
        resume: 结构化简历。
        target_role: 目标岗位（缺省时用简历自带的 target_role）。
        target_company: 目标公司（用户输入，可含别名）。

    Returns:
        ResumeMatch；若无法解析公司偏好则返回 None。
    """
    company = _resolve_company(target_company or "")
    role = target_role or resume.target_role

    dimensions = _load_company_dimensions(company)
    if not dimensions:
        return None

    skills_text = "、".join(
        f"{s.name}({s.level})" for s in resume.skills
    ) or "（无）"
    projects_text = "\n".join(
        f"- {p.name}：{p.description}（{('、'.join(p.tech_stack)) if p.tech_stack else '无技术栈'}）"
        for p in resume.projects
    ) or "（无）"

    model = create_chat_model(temperature=0.0, role="general", max_tokens=2000)
    system_prompt = MATCH_SYSTEM_PROMPT
    user_prompt = MATCH_USER_PROMPT.format(
        target_role=role or "AI Agent / LLM 应用工程师",
        target_company=company,
        company_dimensions="、".join(dimensions),
        skills=skills_text,
        projects=projects_text,
    )

    raw = await model.ainvoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    text = message_text(raw)
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").replace("json", "", 1).strip()

    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        data = {}

    return ResumeMatch(
        target_role=role or "",
        target_company=company,
        overall_score=float(data.get("overall_score", 0.0) or 0.0),
        dimension_scores=data.get("dimension_scores") or {},
        matched_points=data.get("matched_points") or [],
        gap_points=data.get("gap_points") or [],
        company_focus=data.get("company_focus") or dimensions,
    )
