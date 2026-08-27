"""简历经历（项目 + 实习/工作）↔ 面试题库联动（深挖）。

针对简历中的每段经历（项目经历、实习/工作经历），用其技术栈 + 描述
作为查询，跨维度检索参考题目，再用 LLM 基于经历内容生成面试官最可能
追问的问题，并解释关联原因。

复用 ``app.knowledge.service.search``（双通道混合检索）。
"""

from __future__ import annotations

import asyncio
import json
from typing import List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm_factory import create_chat_model, message_text
from app.knowledge import get_question, search
from app.resume.models import ProjectQuestionLink, Resume, ResumeProject, ResumeWork
from app.resume.prompts import (
    DEEP_DIVE_SYSTEM_PROMPT,
    DEEP_DIVE_USER_PROMPT,
    DEEP_DIVE_WORK_USER_PROMPT,
)

# 深挖维度（LLM 定制题标注用）
_DEEP_DIVE_DIMENSION = "project-deep-dive"
# 每段经历召回的参考题目数（作为 LLM 生成追问的参考锚点）
_CANDIDATE_K = 8
# 每段经历最终保留的追问数
_TOP_N = 3


def _build_query(tech_stack: List[str], description: str, name: str = "") -> str:
    """把经历信息拼成检索查询（侧重技术栈与描述，弱化名称噪音）。"""
    parts: List[str] = []
    if tech_stack:
        parts.extend(tech_stack)
    if description:
        parts.append(description[:200])
    if not parts and name:
        parts.append(name)
    return " ".join(parts)


def _retrieve_candidates(query: str, limit: int = _CANDIDATE_K) -> List[dict]:
    """跨维度检索参考题目（不锁 project-deep-dive，让候选覆盖技术栈相关维度）。"""
    results = search(
        query,
        dimension=None,  # 全维度检索，候选更贴合经历技术栈
        limit=limit,
        threshold=0.0,
    )
    candidates = []
    for r in results:
        full = get_question(r.question_id, snapshot_id=r.snapshot_id or None)
        if not full:
            continue
        candidates.append(
            {
                "question_id": full.id,
                "question": full.question,
                "score": round(r.score, 4),
            }
        )
    return candidates


async def _deep_dive_experience(
    *,
    name: str,
    role: str,
    description: str,
    tech_stack: List[str],
    metrics: List[str],
    period: str = "",
    highlights: Optional[List[str]] = None,
    source_type: str,
    candidates: List[dict],
    limit: int = _TOP_N,
) -> List[ProjectQuestionLink]:
    """对一段经历（项目或工作）生成针对性追问。

    传入解析阶段已提取的全部信息（含时间段与亮点），
    让追问建立在完整提取结果之上，而非仅凭描述。
    """
    candidate_text = "\n".join(
        f"- {c['question']}" for c in candidates
    ) if candidates else "（无参考题目）"

    highlights_text = "、".join(highlights) if highlights else ""

    model = create_chat_model(temperature=0.3, role="general", max_tokens=2000)
    system_prompt = DEEP_DIVE_SYSTEM_PROMPT.format(
        candidates=candidate_text, limit=limit
    )
    if source_type == "work":
        user_prompt = DEEP_DIVE_WORK_USER_PROMPT.format(
            company=name,
            role=role,
            period=period,
            description=description,
            tech_stack="、".join(tech_stack),
            metrics="、".join(metrics),
            highlights=highlights_text,
        )
    else:
        user_prompt = DEEP_DIVE_USER_PROMPT.format(
            name=name,
            role=role,
            period=period,
            description=description,
            tech_stack="、".join(tech_stack),
            metrics="、".join(metrics),
            highlights=highlights_text,
        )

    raw = await model.ainvoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    text = message_text(raw)

    try:
        # 容忍模型输出被 ```json 包裹
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.replace("json", "", 1).strip()
        picked = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return []

    links: List[ProjectQuestionLink] = []
    for item in picked if isinstance(picked, list) else []:
        if not isinstance(item, dict):
            continue
        question = (item.get("question") or "").strip()
        if not question:
            continue
        links.append(
            ProjectQuestionLink(
                project_name=name,
                question_id="",  # LLM 定制题，无固定题库 ID
                dimension=_DEEP_DIVE_DIMENSION,
                question=question,
                score=0.0,
                reason=(item.get("reason") or "").strip(),
                source_type=source_type,
            )
        )
    return links[:limit]


async def deep_dive_projects(
    resume: Resume,
    project_names: Optional[List[str]] = None,
    limit: int = _TOP_N,
) -> List[ProjectQuestionLink]:
    """针对简历项目经历做深挖。

    Args:
        resume: 结构化简历。
        project_names: 限定项目名列表；为空则分析全部项目。
        limit: 每个项目保留的追问数。

    Returns:
        项目经历相关的追问列表（保持简历中项目顺序）。
    """
    projects = resume.projects
    if project_names:
        wanted = set(project_names)
        projects = [p for p in projects if p.name in wanted]

    all_links: List[ProjectQuestionLink] = []
    for project in projects:
        query = _build_query(project.tech_stack, project.description, project.name)
        candidates = await asyncio.to_thread(_retrieve_candidates, query)
        links = await _deep_dive_experience(
            name=project.name,
            role=project.role,
            description=project.description,
            tech_stack=project.tech_stack,
            metrics=project.metrics,
            period=project.period,
            highlights=project.highlights,
            source_type="project",
            candidates=candidates,
            limit=limit,
        )
        all_links.extend(links)

    return all_links


async def deep_dive_works(
    resume: Resume,
    limit: int = _TOP_N,
) -> List[ProjectQuestionLink]:
    """针对简历实习/工作经历做深挖。

    Args:
        resume: 结构化简历。
        limit: 每段经历保留的追问数。

    Returns:
        实习/工作经历相关的追问列表（保持简历中顺序）。
    """
    all_links: List[ProjectQuestionLink] = []
    for work in resume.works:
        query = _build_query(work.tech_stack, work.description, work.company)
        candidates = await asyncio.to_thread(_retrieve_candidates, query)
        # 把 start/end 拼成时间段（与项目的 period 对齐）
        period = " - ".join(p for p in [work.start, work.end] if p)
        links = await _deep_dive_experience(
            name=work.company,
            role=work.role,
            description=work.description,
            tech_stack=work.tech_stack,
            metrics=work.metrics,
            period=period,
            highlights=work.highlights,
            source_type="work",
            candidates=candidates,
            limit=limit,
        )
        all_links.extend(links)

    return all_links


async def deep_dive(
    resume: Resume,
    project_names: Optional[List[str]] = None,
    limit: int = _TOP_N,
) -> List[ProjectQuestionLink]:
    """针对简历全部经历（项目 + 实习/工作）做深挖。

    兼容旧签名：返回合并后的追问列表（先项目、后工作经历）。
    如需区分来源，请分别使用 ``deep_dive_projects`` / ``deep_dive_works``。
    """
    project_links = await deep_dive_projects(resume, project_names=project_names, limit=limit)
    work_links = await deep_dive_works(resume, limit=limit)
    return project_links + work_links
