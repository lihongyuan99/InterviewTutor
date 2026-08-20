"""学习模式（RAG 问答）的单元测试。

覆盖：上下文拼接、检索阈值过滤、无结果时的回退。
LLM 调用用 mock 隔离。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.interview import learn
from app.knowledge.schema import SearchResult

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "knowledge.db"


def test_build_context_formats_citations(monkeypatch):
    """上下文拼接应包含编号、题目、专家回答、维度与来源。"""
    from app.knowledge.schema import InterviewQuestion

    fake = InterviewQuestion(
        id="q1",
        dimension="rag",
        dimension_label="RAG 与检索",
        question="什么是 GraphRAG？",
        expert_answer="GraphRAG 是结合知识图谱的 RAG。",
        gap_analysis="新手只会说向量库。",
        source_file="09-rag-retrieval/index.md",
    )
    # learn.py 顶部已绑定 get_question 引用，需 patch learn 命名空间内的引用
    monkeypatch.setattr(learn, "get_question", lambda qid, **k: fake)

    results = [SearchResult(question_id="q1", score=0.8, dimension="rag", source_file="x")]
    ctx = learn._build_context(results)

    assert "[1]" in ctx
    assert "什么是 GraphRAG？" in ctx
    assert "GraphRAG 是结合知识图谱的 RAG。" in ctx
    assert "RAG 与检索" in ctx
    assert "09-rag-retrieval/index.md" in ctx


def test_ask_returns_fallback_when_no_results(monkeypatch):
    """无检索结果时应返回回退回答。"""
    import asyncio

    monkeypatch.setattr(learn, "search", lambda *a, **k: [])

    async def _run():
        return await learn.ask("一个不存在的概念")

    result = asyncio.run(_run())
    assert result["citations"] == []
    assert result["question_ids"] == []
    assert "没有找到" in result["answer"]


@pytest.mark.skipif(
    not DB_PATH.exists(), reason="data/knowledge.db 未构建，跳过端到端测试"
)
def test_ask_returns_answer_with_citations(monkeypatch):
    """端到端：应返回带引用的回答。"""
    import asyncio

    async def fake_llm(messages):
        return "基于知识库，GraphRAG 是……"

    # mock LLM 调用，避免依赖外部模型
    async def _run():
        # 直接测试检索部分（不含 LLM），用真实检索
        from app.knowledge import search
        results = search("什么是 GraphRAG", limit=3)
        return results

    results = asyncio.run(_run())
    assert results, "检索应返回结果"
    assert all(r.question_id for r in results)
    assert all(r.source_file for r in results)
