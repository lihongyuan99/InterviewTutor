"""面试训练会话的持久化存储。

将内存态会话替换为 JSON 文件存储，后端重启后会话仍可恢复，
避免多用户/重启导致会话丢失。存储目录与学习进度、对话记忆隔离。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, Optional

from app.interview.models import InterviewSession

SESSION_DIR = "memory/interview_sessions"

_lock = threading.Lock()


def _session_file(session_id: str) -> Path:
    return Path(SESSION_DIR) / f"{session_id}.json"


def save_session(session: InterviewSession) -> None:
    """保存（覆盖）一个会话。"""
    path = _session_file(session.session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        path.write_text(
            json.dumps(session.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def load_session(session_id: str) -> Optional[InterviewSession]:
    """加载会话，不存在则返回 None。"""
    path = _session_file(session_id)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return InterviewSession(**raw)
    except (json.JSONDecodeError, OSError):
        return None


def delete_session(session_id: str) -> None:
    """删除会话（训练完成后清理）。"""
    path = _session_file(session_id)
    with _lock:
        if path.exists():
            path.unlink()
