"""简历模块。

提供简历文本抽取（extract）、结构化解析（parser）、数据模型（models）、
项目深挖（linker）、匹配分析（matcher）、优化建议（suggester）与
编排入口（analyzer）。
"""

from app.resume.extract import (
    ExtractionError,
    detect_source_type,
    extract_text,
    extract_text_from_bytes,
)
from app.resume.models import (
    Resume,
    ResumeAnalysis,
    ResumeEducation,
    ResumeMatch,
    ResumeProject,
    ResumeSuggestion,
    ResumeWork,
)
from app.resume.parser import ResumeParseError, parse_resume, parse_resume_plain

__all__ = [
    "Resume",
    "ResumeAnalysis",
    "ResumeEducation",
    "ResumeWork",
    "ResumeProject",
    "ResumeSkill",
    "ResumeMatch",
    "ResumeSuggestion",
    "detect_source_type",
    "extract_text",
    "extract_text_from_bytes",
    "ExtractionError",
    "parse_resume",
    "parse_resume_plain",
    "ResumeParseError",
]
