"""面试知识库 SQLite 存储层。

将结构化题目写入 SQLite，并使用 FTS5 全文索引支持关键词检索。
存储路径由 ``settings.KNOWLEDGE_DB_PATH`` 指定，与用户对话记忆向量库
（``memory/vector_store``）物理隔离。

参考上游方案（FTS5 + embedding 双通道）：
- ``knowledge`` 表保存题目完整字段，``embedding`` 列存 Float32 向量 BLOB。
- ``knowledge_fts`` 虚拟表对 question / expert_answer / tags 建全文索引。
- 触发器在插入/删除时自动同步 FTS。
"""

from __future__ import annotations

import json
import sqlite3
import struct
from pathlib import Path
from typing import List, Optional

from app.knowledge.schema import InterviewQuestion

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS knowledge (
    id TEXT PRIMARY KEY,
    dimension TEXT NOT NULL,
    dimension_label TEXT NOT NULL,
    question TEXT NOT NULL,
    source TEXT,
    novice_answer TEXT NOT NULL DEFAULT '',
    expert_answer TEXT NOT NULL DEFAULT '',
    gap_analysis TEXT NOT NULL DEFAULT '',
    key_points TEXT NOT NULL DEFAULT '[]',
    followups TEXT NOT NULL DEFAULT '[]',
    companies TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    difficulty INTEGER NOT NULL DEFAULT 0,
    source_file TEXT NOT NULL,
    source_heading TEXT NOT NULL DEFAULT '',
    embedding BLOB,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    id UNINDEXED,
    question,
    expert_answer,
    tags,
    content='knowledge',
    content_rowid='rowid',
    tokenize='unicode61'
);

CREATE INDEX IF NOT EXISTS idx_knowledge_dimension ON knowledge(dimension);
"""

# FTS5 触发器：同步 knowledge 表的增删改
_TRIGGERS_SQL = """
CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge BEGIN
    INSERT INTO knowledge_fts(rowid, id, question, expert_answer, tags)
    VALUES (new.rowid, new.id, new.question, new.expert_answer, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, id, question, expert_answer, tags)
    VALUES ('delete', old.rowid, old.id, old.question, old.expert_answer, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_au AFTER UPDATE ON knowledge BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, id, question, expert_answer, tags)
    VALUES ('delete', old.rowid, old.id, old.question, old.expert_answer, old.tags);
    INSERT INTO knowledge_fts(rowid, id, question, expert_answer, tags)
    VALUES (new.rowid, new.id, new.question, new.expert_answer, new.tags);
END;
"""


def _pack_embedding(vec: List[float]) -> bytes:
    """将 float 列表打包为 Float32 BLOB。"""
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_embedding(blob: bytes) -> List[float]:
    """从 Float32 BLOB 还原 float 列表。"""
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _to_json(value: list) -> str:
    return json.dumps(value, ensure_ascii=False)


def _from_json(value: Optional[str]) -> list:
    if not value:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


class KnowledgeRepository:
    """SQLite 知识库读写与筛选。"""

    def __init__(self, db_path: Optional[str] = None):
        from app.core.config import settings

        self.db_path = Path(db_path or settings.KNOWLEDGE_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(_SCHEMA_SQL)
        self.conn.executescript(_TRIGGERS_SQL)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---- 写入 ----

    def upsert(self, q: InterviewQuestion, embedding: Optional[List[float]] = None) -> None:
        blob = _pack_embedding(embedding) if embedding is not None else None
        self.conn.execute(
            """
            INSERT OR REPLACE INTO knowledge (
                id, dimension, dimension_label, question, source,
                novice_answer, expert_answer, gap_analysis,
                key_points, followups, companies, tags, difficulty,
                source_file, source_heading, embedding
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                q.id,
                q.dimension,
                q.dimension_label,
                q.question,
                q.source,
                q.novice_answer,
                q.expert_answer,
                q.gap_analysis,
                _to_json(q.key_points),
                _to_json(q.followups),
                _to_json(q.companies),
                _to_json(q.tags),
                q.difficulty,
                q.source_file,
                q.source_heading,
                blob,
            ),
        )

    def upsert_batch(
        self, questions: List[InterviewQuestion], embeddings: Optional[dict] = None
    ) -> None:
        """批量写入。``embeddings`` 为 {id: vector} 映射，可缺省。"""
        embeddings = embeddings or {}
        with self.conn:
            for q in questions:
                self.upsert(q, embeddings.get(q.id))

    def replace_all(
        self, questions: List[InterviewQuestion], embeddings: Optional[dict] = None
    ) -> None:
        """清空并全量重建。"""
        with self.conn:
            self.conn.execute("DELETE FROM knowledge")
            self.upsert_batch(questions, embeddings)

    # ---- 读取与筛选 ----

    def get(self, qid: str) -> Optional[InterviewQuestion]:
        row = self.conn.execute(
            "SELECT * FROM knowledge WHERE id = ?", (qid,)
        ).fetchone()
        return self._row_to_question(row) if row else None

    def count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS c FROM knowledge").fetchone()
        return int(row["c"]) if row else 0

    def count_with_embedding(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM knowledge WHERE embedding IS NOT NULL"
        ).fetchone()
        return int(row["c"]) if row else 0

    def list_dimensions(self) -> List[dict]:
        rows = self.conn.execute(
            """
            SELECT dimension AS id, dimension_label AS label, COUNT(*) AS count
            FROM knowledge GROUP BY dimension ORDER BY dimension
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def list_all(self, dimension: Optional[str] = None) -> List[InterviewQuestion]:
        if dimension:
            rows = self.conn.execute(
                "SELECT * FROM knowledge WHERE dimension = ?", (dimension,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM knowledge").fetchall()
        return [self._row_to_question(r) for r in rows]

    def list_with_embedding(self, dimension: Optional[str] = None) -> List[dict]:
        """返回带 embedding 的行（用于向量召回）。"""
        if dimension:
            rows = self.conn.execute(
                "SELECT * FROM knowledge WHERE embedding IS NOT NULL AND dimension = ?",
                (dimension,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM knowledge WHERE embedding IS NOT NULL"
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def _row_to_question(self, row: sqlite3.Row) -> InterviewQuestion:
        d = self._row_to_dict(row)
        d.pop("embedding", None)
        return InterviewQuestion(**d)

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["key_points"] = _from_json(d.get("key_points"))
        d["followups"] = _from_json(d.get("followups"))
        d["companies"] = _from_json(d.get("companies"))
        d["tags"] = _from_json(d.get("tags"))
        blob = d.get("embedding")
        d["embedding"] = _unpack_embedding(blob) if blob else None
        return d
