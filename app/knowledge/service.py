"""面试知识库统一入口。

为 Agent 与 API 层提供高层能力：解析 + 入库 + 索引 + 检索。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from app.knowledge.indexer import EmbeddingClient, KnowledgeIndexer
from app.knowledge.parser import KnowledgeParser
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.retriever import KnowledgeRetriever
from app.knowledge.schema import InterviewQuestion, SearchResult


def parse_knowledge(knowledge_dir: str) -> tuple[List[InterviewQuestion], list]:
    """解析知识库目录，返回 (题目列表, 警告列表)。"""
    parser = KnowledgeParser(Path(knowledge_dir))
    questions = parser.parse_all()
    return questions, parser.warnings


def build_index(
    knowledge_dir: str,
    db_path: Optional[str] = None,
    with_embedding: bool = True,
    progress: bool = False,
) -> dict:
    """解析知识库并构建索引（可选生成向量）。

    返回统计信息 dict。
    """
    questions, warnings = parse_knowledge(knowledge_dir)

    # CLI/manual builds always target the configured bundled database unless an
    # explicit path is supplied; they never mutate the currently active release.
    if db_path is None:
        from app.core.config import settings

        db_path = settings.KNOWLEDGE_DB_PATH
    repo = KnowledgeRepository(db_path)
    embeddings: Optional[dict] = None

    if with_embedding:
        indexer = KnowledgeIndexer()
        embeddings = indexer.index_questions(questions, progress=progress)

    repo.replace_all(questions, embeddings)
    stats = {
        "total": repo.count(),
        "dimensions": len(repo.list_dimensions()),
        "with_embedding": repo.count_with_embedding(),
        "warnings": len(warnings),
    }
    repo.close()
    return stats


def search(
    query: str,
    dimension: Optional[str] = None,
    limit: int = 5,
    threshold: float = 0.0,
    db_path: Optional[str] = None,
    snapshot_id: Optional[str] = None,
) -> List[SearchResult]:
    """检索知识库。"""
    repo = KnowledgeRepository(db_path, snapshot_id=snapshot_id)
    retriever = KnowledgeRetriever(repository=repo)
    results = retriever.search(
        query, dimension=dimension, limit=limit, threshold=threshold
    )
    repo.close()
    return results


def get_question(
    qid: str,
    db_path: Optional[str] = None,
    snapshot_id: Optional[str] = None,
) -> Optional[InterviewQuestion]:
    """按 ID 获取完整题目（含高手答、差距分析）。"""
    repo = KnowledgeRepository(db_path, snapshot_id=snapshot_id)
    q = repo.get(qid)
    repo.close()
    return q
