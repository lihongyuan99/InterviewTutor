"""文档驱动的知识图谱（渐进式点亮）。

数据源为 ``knowledge/`` 目录下的 Markdown 题库，每个题目对应一个图谱节点，
按 ``dimension``（知识维度）聚类成分组子图。

当用户在对话中命中某个知识点（通过 ``KnowledgeRetriever`` 双通道检索打分
超过阈值），对应节点被「点亮」。点亮状态按 ``task_id`` 隔离，持久化到
``memory/kg_progress/`` 目录下的 JSON 文件。

本模块只负责「标记学习进度」，不改变教学流程。
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# 项目根目录（app/kg/doc_graph.py -> 项目根）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_PROGRESS_DIR = _PROJECT_ROOT / "memory" / "kg_progress"

# 向量检索点亮阈值：相似度 >= 该值视为命中点亮
LIT_THRESHOLD = 0.5

# 进程内缓存：task_id -> {node_id: {...}}
_progress_cache: Dict[str, dict] = {}
_cache_lock = threading.Lock()


def _progress_path(task_id: str) -> Path:
    # 防御：task_id 可能包含路径分隔符
    safe = str(task_id).replace("/", "_").replace("\\", "_")
    return _PROGRESS_DIR / f"{safe}.json"


def _load_progress(task_id: str) -> dict:
    """加载某任务的点亮状态（带进程内缓存）。"""
    with _cache_lock:
        cached = _progress_cache.get(task_id)
        if cached is not None:
            return cached
    path = _progress_path(task_id)
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    lit_nodes = data.get("lit_nodes", {}) if isinstance(data, dict) else {}
    with _cache_lock:
        _progress_cache[task_id] = lit_nodes
    return lit_nodes


def _save_progress(task_id: str, lit_nodes: dict) -> None:
    _PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    path = _progress_path(task_id)
    payload = {"task_id": task_id, "lit_nodes": lit_nodes}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with _cache_lock:
        _progress_cache[task_id] = lit_nodes


def mark_lit(task_id: str, node_id: str, score: float) -> None:
    """点亮某个节点（若已点亮则累加命中次数、保留最高分）。"""
    if not node_id:
        return
    lit = _load_progress(task_id)
    entry = lit.get(node_id)
    if entry is None:
        lit[node_id] = {
            "score": round(float(score), 4),
            "count": 1,
            "at": datetime.now().isoformat(timespec="seconds"),
        }
    else:
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["score"] = round(max(float(entry.get("score", 0)), float(score)), 4)
        entry["at"] = datetime.now().isoformat(timespec="seconds")
    _save_progress(task_id, lit)


def get_lit_map(task_id: str) -> dict:
    """返回 {node_id: {score, count, at}}。"""
    return _load_progress(task_id)


def _iter_questions() -> List:
    """从知识库 SQLite 读取全部题目（已解析入 knowledge 表）。"""
    from app.knowledge.repository import KnowledgeRepository

    repo = KnowledgeRepository()
    try:
        questions = repo.list_all()
    finally:
        repo.close()
    return questions


def get_dimensions() -> List[dict]:
    """返回维度列表（dimension, label, count），供前端展示分组。"""
    from app.knowledge.repository import KnowledgeRepository

    repo = KnowledgeRepository()
    try:
        return repo.list_dimensions()
    finally:
        repo.close()


def build_doc_graph(task_id: str) -> dict:
    """组装文档知识图谱结构（含点亮状态）。

    返回结构:
    {
        "task_id": str,
        "dimensions": [
            {"dimension": str, "label": str, "nodes": [
                {"id", "title", "lit", "score", "count"} ...]},
        ],
        "stats": {"total": int, "lit": int},
    }
    """
    questions = _iter_questions()
    lit_map = get_lit_map(task_id)

    grouped: Dict[str, Dict] = {}
    total = 0
    lit_total = 0

    for q in questions:
        dim = q.dimension or "unknown"
        if dim not in grouped:
            grouped[dim] = {
                "dimension": dim,
                "label": q.dimension_label or dim,
                "nodes": [],
            }
        entry = lit_map.get(q.id)
        lit = entry is not None
        total += 1
        if lit:
            lit_total += 1
        grouped[dim]["nodes"].append(
            {
                "id": q.id,
                "title": q.question or q.title or q.id,
                "lit": lit,
                "score": entry.get("score") if entry else None,
                "count": entry.get("count", 0) if entry else 0,
            }
        )

    dimensions = list(grouped.values())
    # 维度按名称稳定排序
    dimensions.sort(key=lambda d: d["dimension"])
    # 每个维度内节点按标题排序
    for d in dimensions:
        d["nodes"].sort(key=lambda n: n["title"])

    return {
        "task_id": task_id,
        "dimensions": dimensions,
        "stats": {"total": total, "lit": lit_total},
    }


def hit_doc_graph(task_id: str, user_text: str, threshold: float = LIT_THRESHOLD) -> int:
    """用用户消息检索知识库，点亮命中的节点，返回本次点亮的节点数。

    检索失败或未命中时静默返回 0，不抛出异常（不阻塞对话主流程）。
    """
    if not user_text or not user_text.strip():
        return 0
    try:
        from app.knowledge.retriever import KnowledgeRetriever

        retriever = KnowledgeRetriever()
        results = retriever.search(user_text.strip(), limit=8, threshold=threshold)
    except Exception as e:
        print(f"[KG] doc graph hit failed: {e}")
        return 0

    lit_count = 0
    for r in results:
        if r.score < threshold:
            continue
        mark_lit(task_id, r.question_id, r.score)
        lit_count += 1
    return lit_count


def rebuild_doc_graph() -> dict:
    """重新解析 knowledge/ 目录并重建索引（含向量）。"""
    from app.knowledge.service import build_index
    from app.core.config import settings

    knowledge_dir = os.environ.get("KNOWLEDGE_DIR") or str(_PROJECT_ROOT / "knowledge")
    stats = build_index(
        knowledge_dir=knowledge_dir,
        db_path=settings.KNOWLEDGE_DB_PATH,
        with_embedding=True,
        progress=False,
    )
    return stats
