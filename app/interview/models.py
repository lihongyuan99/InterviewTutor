"""面试训练模块的数据模型。

定义刷题会话、结构化评分与学习进度等核心结构。
与 Handoff 文档 §10 / §11 保持一致。
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ---- 训练会话 ----

InterviewPhase = Literal[
    "idle",
    "asking",
    "awaiting_answer",
    "evaluating",
    "probing",
    "reviewing",
    "completed",
]

InterviewMode = Literal["practice", "mock", "review"]


class InterviewSession(BaseModel):
    """一次刷题训练会话。"""

    session_id: str
    user_id: str = "local_user"
    mode: InterviewMode = "practice"
    dimensions: List[str] = Field(default_factory=list)
    companies: List[str] = Field(default_factory=list)
    difficulty: int = 0

    phase: InterviewPhase = "idle"
    current_question_id: Optional[str] = None
    current_question: Optional[str] = None
    question_round: int = 0

    # 出题阶段绝不注入专家答案；用户提交后才注入评分所需的标准答案
    retrieved_knowledge: Optional[dict] = None
    evaluation_result: Optional[dict] = None

    # 用户最近一次作答
    last_answer: str = ""


# ---- 结构化评分 ----

class EvaluationResult(BaseModel):
    """Judge 的结构化评分输出（L1-L5）。"""

    overall_level: int = Field(description="总体等级 1-5")
    correctness: int = Field(description="正确性 1-5")
    depth: int = Field(description="深度 1-5")
    tradeoff_reasoning: int = Field(description="权衡推理 1-5")
    engineering_evidence: int = Field(description="工程证据 1-5")
    clarity: int = Field(description="表达清晰度 1-5")

    covered_points: List[str] = Field(default_factory=list)
    missing_points: List[str] = Field(default_factory=list)
    strengths: List[str] = Field(default_factory=list)
    improvement_advice: List[str] = Field(default_factory=list)

    next_followup: str = Field(default="", description="针对缺失点的追问")
    mastery_delta: float = Field(default=0.0, description="掌握度变化 -1 ~ 1")


# ---- 学习进度 ----

class QuestionProgress(BaseModel):
    """单道题的学习进度记录。"""

    user_id: str = "local_user"
    question_id: str
    attempts: int = 0
    best_level: int = 0
    last_scores: Dict[str, int] = Field(default_factory=dict)
    missing_points: List[str] = Field(default_factory=list)
    last_reviewed_at: str = ""
    next_review_at: str = ""
    mastery: float = 0.0


# ---- API 请求体 ----

class StartRequest(BaseModel):
    user_id: str = "local_user"
    mode: InterviewMode = "practice"
    dimensions: List[str] = Field(default_factory=list)
    companies: List[str] = Field(default_factory=list)
    difficulty: int = 0


class AnswerRequest(BaseModel):
    session_id: str
    answer: str


class FollowupAnswerRequest(BaseModel):
    session_id: str
    answer: str
