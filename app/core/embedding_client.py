"""统一的 Embedding 客户端（Qwen3-Embedding，OpenAI 兼容接口）。

题库检索（app/knowledge/）与对话记忆检索（app/core/vector_store.py）
共用此客户端，避免两套 embedding 逻辑重复。

使用 ``requests`` 而非 ``openai`` SDK：本地 ``omlx`` 服务对 httpx
（openai SDK 底层）的请求返回 502，但 requests 可稳定工作。
"""

from __future__ import annotations

from typing import List, Optional

from langchain_core.embeddings import Embeddings


class Qwen3EmbeddingClient(Embeddings):
    """OpenAI 兼容 Embedding 客户端（默认 Qwen3-Embedding-0.6B-4bit-DWQ）。

    继承 LangChain ``Embeddings`` 基类，实现 ``embed_documents`` / ``embed_query``，
    可直接作为 FAISS 的 embeddings 参数使用。

    使用 ``requests.Session`` 复用底层 TCP 连接，避免每次 embedding 都
    重新握手（本地 omlx 服务无 keep-alive 时这能显著降低单次请求延迟）。
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        dim: Optional[int] = None,
    ):
        from app.core.config import settings

        self.base_url = (base_url or settings.KNOWLEDGE_EMBEDDING_BASE_URL).rstrip("/")
        self.model = model or settings.KNOWLEDGE_EMBEDDING_MODEL
        self.api_key = api_key or settings.KNOWLEDGE_EMBEDDING_API_KEY
        self.dim = dim or settings.KNOWLEDGE_EMBEDDING_DIM
        self._session = None

    def _get_session(self):
        import requests

        if self._session is None:
            self._session = requests.Session()
        return self._session

    def embed(self, texts: List[str]) -> List[List[float]]:
        """批量生成向量，返回与输入等长的向量列表。"""
        if not texts:
            return []
        session = self._get_session()
        resp = session.post(
            f"{self.base_url}/embeddings",
            json={"model": self.model, "input": texts},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        data = sorted(data, key=lambda d: d.get("index", 0))
        return [list(d["embedding"]) for d in data]

    def embed_query(self, query: str) -> List[float]:
        return self.embed([query])[0]

    # LangChain Embeddings 接口
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.embed(texts)

    def __call__(self, texts: List[str]) -> List[List[float]]:
        """兼容部分 LangChain 内部直接调用 embedding 函数的路径。"""
        return self.embed(texts)
