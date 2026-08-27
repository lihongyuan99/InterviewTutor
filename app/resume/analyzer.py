"""简历分析编排入口。

把深挖（linker）、匹配（matcher）、建议（suggester）组合为一次
完整的简历分析，产出 :class:`ResumeAnalysis`，并持久化分析结果。

这是「一次性批量任务」的编排层，不进入主对话 Agent 的多智能体图
（见设计文档 §6）。
"""

from __future__ import annotations

import json
import os
import time
from typing import List, Optional

from app.resume import linker, matcher, store, suggester
from app.resume.models import Resume, ResumeAnalysis, ResumeMatch, ResumeSuggestion

# 分析结果存储目录
ANALYSIS_DIR = "memory/resume_analysis"


def _make_analysis_id(resume_id: str) -> str:
    return f"analysis_{resume_id}_{time.strftime('%H%M%S')}"


def _save_analysis(analysis: ResumeAnalysis) -> str:
    os.makedirs(ANALYSIS_DIR, exist_ok=True)
    path = os.path.join(ANALYSIS_DIR, f"{analysis.analysis_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(analysis.model_dump(), f, ensure_ascii=False, indent=2)
    return path


async def analyze_resume(
    resume_id: str,
    *,
    project_names: Optional[List[str]] = None,
    target_role: str = "",
    target_company: str = "",
) -> ResumeAnalysis:
    """对一份简历执行完整分析（深挖 + 匹配 + 建议）。

    Args:
        resume_id: 简历 ID。
        project_names: 限定深挖的项目名；为空则全部。
        target_role: 目标岗位（缺省用简历自带）。
        target_company: 目标公司（用于匹配，可缺省跳过匹配）。

    Returns:
        完整的 ResumeAnalysis。
    """
    resume = store.load_resume(resume_id)
    if resume is None:
        raise ValueError(f"简历不存在：{resume_id}")

    project_questions = await linker.deep_dive_projects(resume, project_names=project_names)
    work_questions = await linker.deep_dive_works(resume)

    match: Optional[ResumeMatch] = None
    if target_company or resume.target_companies:
        company = target_company or (resume.target_companies[0] if resume.target_companies else "")
        if company:
            match = await matcher.match_resume(resume, target_role, company)

    suggestions: List[ResumeSuggestion] = await suggester.suggest(resume, target_role)

    analysis = ResumeAnalysis(
        analysis_id=_make_analysis_id(resume_id),
        resume_id=resume_id,
        project_questions=project_questions,
        work_questions=work_questions,
        match=match,
        suggestions=suggestions,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )
    _save_analysis(analysis)
    return analysis
