"""面试知识库向量生成。

调用本地部署的 Embedding 服务（OpenAI 兼容接口，默认 Qwen3-Embedding）
为题目生成向量。向量拼接 ``question + expert_answer`` 前若干字符，
与上游参考方案一致（question 太短语义不足，expert_answer 太长浪费）。

首版不做复杂分块：每道主问题作为一个文档整体向量化，保证父问题
上下文完整，避免 Markdown 表格/代码块被从中间切断。
"""

from __future__ import annotations

import time
from typing import List, Optional

from app.core.embedding_client import Qwen3EmbeddingClient
from app.knowledge.schema import InterviewQuestion

# embedding 输入的最大字符数（约合 token 上限的宽松估计）
_MAX_TEXT_CHARS = 1500


def build_embedding_text(q: InterviewQuestion) -> str:
    """构造 embedding 输入文本。"""
    expert = q.expert_answer[: _MAX_TEXT_CHARS]
    return f"问题：{q.question}\n答案：{expert}"


# 兼容旧导入路径的别名：EmbeddingClient 现指向统一客户端
EmbeddingClient = Qwen3EmbeddingClient


class KnowledgeIndexer:
    """为题目批量生成向量并写回数据库。"""

    def __init__(
        self,
        client: Optional[EmbeddingClient] = None,
        batch_size: int = 32,
    ):
        self.client = client or EmbeddingClient()
        self.batch_size = batch_size

    def index_questions(
        self,
        questions: List[InterviewQuestion],
        progress: bool = False,
    ) -> dict:
        """为题目生成向量，返回 {id: vector} 映射。"""
        result: dict = {}
        texts = [build_embedding_text(q) for q in questions]
        total = len(texts)

        for i in range(0, total, self.batch_size):
            batch = texts[i : i + self.batch_size]
            batch_qs = questions[i : i + self.batch_size]
            vecs = self.client.embed(batch)
            for q, vec in zip(batch_qs, vecs):
                result[q.id] = vec
            if progress:
                done = min(i + self.batch_size, total)
                print(f"  Embedded {done}/{total}")
            if i + self.batch_size < total:
                time.sleep(0.05)

        return result
