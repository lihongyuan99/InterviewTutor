"""面试知识库双通道混合检索。

通道一：SQLite FTS5 全文检索（精确/关键词匹配）。
通道二：Embedding 向量检索（语义匹配）。

两条通道结果合并去重：向量结果优先（语义更准），双通道同时命中则
提升分数，最终返回 Top-K。

每条结果必须携带题目 ID 与来源，方便回答引用与离线评估（Handoff §8）。
"""

from __future__ import annotations

import math
import re
from typing import List, Optional

from app.knowledge.indexer import EmbeddingClient
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.schema import SearchResult


class KnowledgeRetriever:
    """知识库检索器。"""

    def __init__(
        self,
        repository: Optional[KnowledgeRepository] = None,
        client: Optional[EmbeddingClient] = None,
    ):
        self.repo = repository or KnowledgeRepository()
        self.client = client or EmbeddingClient()

    def search(
        self,
        query: str,
        dimension: Optional[str] = None,
        limit: int = 5,
        threshold: float = 0.0,
    ) -> List[SearchResult]:
        """双通道检索，返回 Top-K 结果。"""
        fts = self._search_fts(query, dimension=dimension, limit=limit * 3)
        emb = self._search_embedding(
            query, dimension=dimension, limit=limit * 3, threshold=threshold
        )

        # 关键词通道分数折扣：避免「精确命中一个词」压过「语义强相关」。
        # embedding 语义匹配对中文更可靠，作为主通道。
        _KEYWORD_DISCOUNT = 0.6

        merged: dict = {}
        # 向量结果优先
        for r in emb:
            merged[r.question_id] = r
        # 关键词结果补充，双命中提升分数
        for r in fts:
            if r.question_id in merged:
                existing = merged[r.question_id]
                existing.score = min(1.0, existing.score * 1.1 + r.score * 0.1)
            else:
                r.score = r.score * _KEYWORD_DISCOUNT
                merged[r.question_id] = r

        ranked = sorted(merged.values(), key=lambda r: -r.score)
        # 统一 threshold 过滤：对合并后的最终结果也做分数门槛，
        # 避免关键词通道的兜底结果在无相关查询时也混入。
        if threshold > 0:
            ranked = [r for r in ranked if r.score >= threshold]
        return ranked[:limit]

    # ---- 通道一：关键词匹配（SQL LIKE + 覆盖率打分） ----

    def _search_fts(
        self, query: str, dimension: Optional[str], limit: int
    ) -> List[SearchResult]:
        """关键词通道。

        FTS5 的 ``unicode61`` tokenizer 无法切分中文（连续汉字视为一个
        token），因此改用 SQL ``LIKE`` 子串匹配：对 query 拆分出的每个
        关键词，统计其在 question + expert_answer 中的命中覆盖情况打分。
        英文技术词由 FTS5 语义精确匹配，中文由 LIKE 子串匹配兜底。
        """
        keywords = self._extract_keywords(query)
        if not keywords:
            return []

        sql = """
            SELECT id, dimension, source_file, question, expert_answer, tags
            FROM knowledge
        """
        params: list = []
        if dimension:
            sql += " WHERE dimension = ?"
            params.append(dimension)

        try:
            rows = self.repo.conn.execute(sql, params).fetchall()
        except Exception:
            return []

        scored = []
        for row in rows:
            haystack = (
                row["question"] + " " + row["expert_answer"] + " " + (row["tags"] or "")
            )
            hits = sum(1 for kw in keywords if kw in haystack)
            if hits == 0:
                continue
            # 覆盖率打分：命中关键词占比，落在 0-1
            coverage = hits / len(keywords)
            # 命中比例越高越相关；叠加一个基础分保证能进入候选
            scored.append((row, coverage))

        scored.sort(key=lambda x: -x[1])

        results = []
        for row, coverage in scored[:limit]:
            results.append(
                SearchResult(
                    question_id=row["id"],
                    score=coverage,
                    dimension=row["dimension"],
                    source_file=row["source_file"],
                    content=row["question"],
                )
            )
        return results

    # ---- 通道二：Embedding ----

    def _search_embedding(
        self,
        query: str,
        dimension: Optional[str],
        limit: int,
        threshold: float,
    ) -> List[SearchResult]:
        rows = self.repo.list_with_embedding(dimension=dimension)
        if not rows:
            return []

        query_vec = self.client.embed_query(query)

        scored = []
        for row in rows:
            vec = row.get("embedding")
            if not vec:
                continue
            sim = self._cosine(query_vec, vec)
            if sim >= threshold:
                scored.append((row, sim))

        scored.sort(key=lambda x: -x[1])

        results = []
        for row, sim in scored[:limit]:
            results.append(
                SearchResult(
                    question_id=row["id"],
                    score=sim,
                    dimension=row["dimension"],
                    source_file=row["source_file"],
                    content=row["question"],
                )
            )
        return results

    # ---- 工具方法 ----

    @staticmethod
    def _extract_keywords(text: str) -> List[str]:
        """从查询中提取关键词。

        英文/数字词整体保留（如 ReAct、Plan-and-Execute、RAG）；
        中文用 jieba 分词，过滤虚词与单字，得到有语义边界的关键词。
        相比旧版 2-gram 滑窗，jieba 按词边界切分，避免「怎么做红烧肉」
        被切成「么做」「做红」这类跨词边界的噪声词。
        """
        keywords: List[str] = []

        # 1) 英文/数字词整体保留
        keywords.extend(re.findall(r"[A-Za-z][A-Za-z0-9\-]*", text))

        # 2) 中文用 jieba 分词（精确模式）
        try:
            import jieba

            zh_segments = re.findall(r"[\u4e00-\u9fff]+", text)
            for seg in zh_segments:
                keywords.extend(jieba.lcut(seg))
        except ImportError:  # 兜底：无 jieba 时退回 2-gram
            zh_segments = re.findall(r"[\u4e00-\u9fff]+", text)
            for seg in zh_segments:
                if len(seg) <= 4:
                    keywords.append(seg)
                else:
                    for i in range(len(seg) - 1):
                        keywords.append(seg[i : i + 2])

        # 去重 + 过滤（长度、无意义虚词/单字）
        stopwords = {
            "怎么", "如何", "什么", "为什么", "哪些", "一个", "进行", "可以",
            "这个", "那个", "的", "了", "是", "在", "有", "和", "与", "或",
            "做", "么", "样", "怎", "帮", "我", "写", "首", "诗", "呢", "啊",
            "吗", "吧", "你", "他", "她", "它", "们", "就", "都", "还", "也",
        }
        seen = []
        for kw in keywords:
            kw = kw.strip()
            if len(kw) < 2 or kw in stopwords or kw in seen:
                continue
            seen.append(kw)
        return seen

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        if len(a) != len(b):
            return 0.0
        dot = 0.0
        na = 0.0
        nb = 0.0
        for x, y in zip(a, b):
            dot += x * y
            na += x * x
            nb += y * y
        if na == 0.0 or nb == 0.0:
            return 0.0
        return dot / (math.sqrt(na) * math.sqrt(nb))
