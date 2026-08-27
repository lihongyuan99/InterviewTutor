"""简历数据模型。

定义简历上传、结构化解析、项目深挖与匹配分析所依赖的核心数据结构，
与 ``docs/resume-analysis-design.md`` §3 保持一致。

本模块只定义数据结构，不做解析、不调用模型、不读写磁盘。
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ResumeEducation(BaseModel):
    """一段教育经历。"""

    school: str = ""
    degree: str = ""  # 本科 / 硕士 / 博士
    major: str = ""
    start: str = ""
    end: str = ""
    highlights: List[str] = Field(default_factory=list)


class ResumeWork(BaseModel):
    """一段工作/实习经历（深挖重点之一）。"""

    company: str = ""
    role: str = ""
    start: str = ""
    end: str = ""
    description: str = ""
    # 技术栈与量化成果（与项目对齐，深挖依赖这两个字段生成针对性追问）
    tech_stack: List[str] = Field(default_factory=list)
    metrics: List[str] = Field(default_factory=list)
    highlights: List[str] = Field(default_factory=list)


class ResumeProject(BaseModel):
    """一个项目经历（简历深挖的核心对象）。"""

    name: str = ""
    role: str = ""
    period: str = ""
    description: str = ""
    # 关键技术栈，用于题库维度映射（如 LangGraph、RAG、Embedding）
    tech_stack: List[str] = Field(default_factory=list)
    # 量化成果（STAR 的 R，缺失则提示）
    metrics: List[str] = Field(default_factory=list)
    highlights: List[str] = Field(default_factory=list)


class ResumeSkill(BaseModel):
    """一项技能。"""

    name: str = ""
    level: str = ""  # 熟悉 / 掌握 / 精通
    category: str = ""  # 编程语言 / 框架 / ML / AI / 工程 / 其他


class Resume(BaseModel):
    """一份简历的结构化表示。"""

    resume_id: str = ""
    user_id: str = "local_user"
    source_file: str = ""  # 原始文件相对路径
    source_type: str = ""  # pdf / docx / md
    raw_text: str = ""  # 解析出的纯文本（保留备查）
    name: str = ""
    contact: str = ""  # 脱敏：默认不存手机/邮箱原文
    target_role: str = ""  # 目标岗位
    target_companies: List[str] = Field(default_factory=list)
    summary: str = ""  # 个人简介 / 自我评价
    educations: List[ResumeEducation] = Field(default_factory=list)
    works: List[ResumeWork] = Field(default_factory=list)
    projects: List[ResumeProject] = Field(default_factory=list)
    skills: List[ResumeSkill] = Field(default_factory=list)
    honors: List[str] = Field(default_factory=list)
    mapped_dimensions: List[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class ProjectQuestionLink(BaseModel):
    """简历经历（项目/工作）与面试题的一条关联。"""

    project_name: str  # 项目名或公司名
    question_id: str  # InterviewQuestion.id（LLM 定制题则为空）
    dimension: str
    question: str
    score: float  # 关联相关度
    reason: str = ""  # 为什么这道题会问到这段经历
    source_type: str = "project"  # project=项目经历, work=实习/工作经历


class ResumeMatch(BaseModel):
    """简历 vs 目标公司/岗位的匹配度。"""

    target_role: str = ""
    target_company: str = ""
    overall_score: float = 0.0  # 0-1
    dimension_scores: dict = Field(default_factory=dict)  # dimension -> score
    matched_points: List[str] = Field(default_factory=list)
    gap_points: List[str] = Field(default_factory=list)
    company_focus: List[str] = Field(default_factory=list)  # 该公司高频维度


class ResumeSuggestion(BaseModel):
    """一条简历优化建议。"""

    category: str = ""  # star / metrics / tech_stack / wording / missing
    severity: str = ""  # high / medium / low
    target: str = ""  # 指向的项目/技能/字段
    advice: str = ""


class ResumeAnalysis(BaseModel):
    """一次简历分析的完整输出。"""

    analysis_id: str = ""
    resume_id: str = ""
    project_questions: List[ProjectQuestionLink] = Field(default_factory=list)
    work_questions: List[ProjectQuestionLink] = Field(default_factory=list)
    match: Optional[ResumeMatch] = None
    suggestions: List[ResumeSuggestion] = Field(default_factory=list)
    created_at: str = ""
