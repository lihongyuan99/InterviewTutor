"""知识库检索的单元测试。

覆盖：关键词提取、余弦相似度、双通道合并、按维度过滤。
检索的端到端效果依赖已构建的 ``data/knowledge.db``，若数据库不存在
则跳过需要 embedding 的用例。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.knowledge.retriever import KnowledgeRetriever  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "knowledge.db"


def test_extract_keywords_english_and_chinese():
    """关键词应同时提取英文词与中文实义词（jieba 分词，虚词被过滤）。"""
    kw = KnowledgeRetriever._extract_keywords("ReAct 和 Plan-and-Execute 怎么选")
    assert "ReAct" in kw
    assert "Plan-and-Execute" in kw


def test_extract_keywords_chinese_segmentation():
    """中文按词边界分词，不应产生跨词边界的噪声 2-gram。"""
    kw = KnowledgeRetriever._extract_keywords("怎么做红烧肉")
    assert "红烧肉" in kw
    # 旧版 2-gram 滑窗会切出「么做」「做红」这类噪声词，新版应避免
    assert "么做" not in kw
    assert "做红" not in kw


def test_extract_keywords_filters_stopwords():
    """独立虚词 token（用空格分隔）应被过滤。"""
    kw = KnowledgeRetriever._extract_keywords("怎么 如何 什么 的 了 吗")
    assert kw == []


def test_cosine_similarity_identical():
    vec = [1.0, 2.0, 3.0]
    assert abs(KnowledgeRetriever._cosine(vec, vec) - 1.0) < 1e-6


def test_cosine_similarity_orthogonal():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(KnowledgeRetriever._cosine(a, b)) < 1e-6


@pytest.mark.skipif(
    not DB_PATH.exists(), reason="data/knowledge.db 未构建，跳过端到端检索测试"
)
def test_search_returns_results_with_dimension_filter():
    """端到端：检索应返回结果，且可按维度过滤。"""
    from app.knowledge import search

    results = search("RAG 检索", dimension="rag", limit=5)
    assert results, "RAG 检索应返回结果"
    for r in results:
        assert r.dimension == "rag", f"维度过滤失效：{r.dimension}"
        assert r.question_id, "结果缺少题目 ID"
        assert r.source_file, "结果缺少来源"


@pytest.mark.skipif(
    not DB_PATH.exists(), reason="data/knowledge.db 未构建，跳过端到端检索测试"
)
def test_search_memory_query_hits_memory_dimension():
    """记忆相关查询应命中 memory-context 维度。"""
    from app.knowledge import search

    results = search("Agent 的记忆系统怎么设计", limit=5)
    assert results
    top_dims = [r.dimension for r in results[:3]]
    assert "memory-context" in top_dims, f"记忆查询未命中 memory-context：{top_dims}"
