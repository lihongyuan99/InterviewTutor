"""面试知识库数据模型。

本模块定义知识解析、存储与检索所依赖的核心数据结构。
数据模型与 Handoff 文档 §6 保持一致，用于将 Markdown 题目
解析为结构化的 ``InterviewQuestion`` 记录。
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class InterviewQuestion(BaseModel):
    """一道面试主问题的规范化表示。"""

    id: str = Field(description="稳定、可复现的题目 ID")
    dimension: str = Field(description="所属知识维度（目录名归一化）")
    dimension_label: str = Field(default="", description="维度中文名")
    title: str = Field(default="", description="题目标题，缺失时回退为问题文本")
    question: str = Field(description="面试问题正文")
    source: str = Field(default="", description="来源（公司/岗位）原始文本")
    novice_answer: str = Field(default="", description="新手答")
    expert_answer: str = Field(default="", description="高手答 / 专家回答")
    gap_analysis: str = Field(default="", description="差距在哪 / 新手与高手的差距分析")
    key_points: List[str] = Field(default_factory=list, description="考察点")
    followups: List[str] = Field(default_factory=list, description="追问")
    companies: List[str] = Field(default_factory=list, description="来源公司（从 来源 提取）")
    tags: List[str] = Field(default_factory=list, description="标签")
    difficulty: int = Field(default=0, description="难度，0 表示未知")
    source_file: str = Field(description="来源文件相对路径")
    source_heading: str = Field(default="", description="原始 Q 标题（含级别）")


class KnowledgeChunk(BaseModel):
    """用于向量检索的文档块，携带父问题上下文。"""

    chunk_id: str = Field(description="子块 ID")
    parent_id: str = Field(description="父问题 ID")
    content: str = Field(description="子块文本")
    chunk_type: str = Field(
        default="expert_answer", description="question / novice_answer / expert_answer / key_point / followup"
    )
    dimension: str = ""
    question: str = ""
    companies: List[str] = Field(default_factory=list)
    source_file: str = ""


class SearchResult(BaseModel):
    """检索返回的一条结果。"""

    question_id: str
    score: float
    chunk_id: Optional[str] = None
    content: str = ""
    dimension: str = ""
    source_file: str = ""
    snapshot_id: str = Field(
        default="", description="生成该结果的知识库快照，用于后续一致读取"
    )


class ParseWarning(BaseModel):
    """解析过程中产生的一条警告，用于人工抽查与排错。"""

    file: str
    message: str
    line: Optional[int] = None
