"""一次性回填脚本：将 memory/sessions/ 下所有历史会话重建进 FAISS 向量库。

背景：早期 _index_session_for_rag 存在格式误判 bug，导致历史会话从未真正
写入向量库（memory/vector_store 目录缺失）。修复后，此脚本用于回填存量数据。

用法：
    tutor/bin/python scripts/backfill_vector_store.py [--force]

    --force  清空已有向量库后重建（默认跳过已存在的 task 向量库）
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import memory  # noqa: E402
from app.core import vector_store  # noqa: E402


SESSIONS_DIR = "memory/sessions"


def iter_session_files() -> list[str]:
    return sorted(glob.glob(os.path.join(SESSIONS_DIR, "*.json")))


def backfill(force: bool) -> None:
    files = iter_session_files()
    print(f"共发现 {len(files)} 个会话文件\n")

    # 按 task 分组，统计每个 task 的会话数
    task_files: dict[str, list[str]] = {}
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  [跳过] 无法解析 {os.path.basename(f)}: {e}")
            continue

        task_id = data.get("task_id")
        session_id = data.get("session_id")
        if not task_id or not session_id:
            print(f"  [跳过] 缺少 task_id/session_id: {os.path.basename(f)}")
            continue
        task_files.setdefault(task_id, []).append(f)

    total_indexed = 0
    for task_id, files_of_task in task_files.items():
        store = vector_store.get_vector_store(task_id)

        if force:
            store.clear()
            vector_store._store_cache.pop(task_id, None)
            store = vector_store.get_vector_store(task_id)

        # 统计当前向量库已有文档数
        existing = len(store.metadata)
        print(f"任务 {task_id}: {len(files_of_task)} 个会话, 现有向量文档 {existing} 条")

        for f in files_of_task:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            session_id = data["session_id"]
            serialized = data.get("messages", [])
            topic = data.get("topic", "General")

            # 复用 memory 内已修复的格式转换 + 索引逻辑
            memory._index_session_for_rag(
                session_id=session_id,
                task_id=task_id,
                messages=serialized,
                topic=topic,
            )
            total_indexed += 1
            print(f"    ✓ 已索引 {session_id}")

    print(f"\n完成，共索引 {total_indexed} 个会话。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="回填历史会话到 FAISS 向量库")
    parser.add_argument("--force", action="store_true", help="清空已有向量库后重建")
    args = parser.parse_args()
    backfill(force=args.force)
