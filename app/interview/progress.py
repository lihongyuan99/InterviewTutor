"""学习进度与复习调度。

存储每道题的掌握度、评分与下次复习时间。首版使用简单分箱规则
（Handoff §11），不引入复杂间隔重复算法：

- L1-L2：次日复习
- L3：3 天后复习
- L4：7 天后复习
- L5：14 天后复习
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from app.interview.models import QuestionProgress

# 进度存储目录（与用户对话记忆 memory/vector_store 物理隔离）
PROGRESS_DIR = "memory/interview_progress"

# 等级 -> 复习间隔天数
_REVIEW_INTERVAL_DAYS = {
    1: 1,
    2: 1,
    3: 3,
    4: 7,
    5: 14,
}


def _user_file(user_id: str) -> Path:
    """用户进度文件路径。"""
    safe = user_id.replace("/", "_").replace("..", "_")
    return Path(PROGRESS_DIR) / f"{safe}.json"


def _load_all(user_id: str) -> Dict[str, dict]:
    path = _user_file(user_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_all(user_id: str, data: Dict[str, dict]) -> None:
    path = _user_file(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _next_review_at(level: int, now: Optional[datetime] = None) -> str:
    now = now or datetime.now()
    days = _REVIEW_INTERVAL_DAYS.get(level, 1)
    return (now + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


class ProgressStore:
    """题目掌握度与复习调度的读写。"""

    def __init__(self, user_id: str = "local_user"):
        self.user_id = user_id
        self._data = _load_all(user_id)

    def get(self, question_id: str) -> Optional[QuestionProgress]:
        raw = self._data.get(question_id)
        if not raw:
            return None
        return QuestionProgress(**raw)

    def all(self) -> List[QuestionProgress]:
        return [QuestionProgress(**raw) for raw in self._data.values()]

    def review_queue(self, limit: int = 20) -> List[QuestionProgress]:
        """返回到期待复习的题目（next_review_at <= 当前时间）。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        due = [
            p
            for p in self.all()
            if p.next_review_at and p.next_review_at <= now
        ]
        due.sort(key=lambda p: p.next_review_at)
        return due[:limit]

    def record_attempt(
        self,
        question_id: str,
        overall_level: int,
        scores: Dict[str, int],
        missing_points: List[str],
        mastery_delta: float = 0.0,
    ) -> QuestionProgress:
        """记录一次作答，更新掌握度与下次复习时间。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        existing = self._data.get(question_id, {})

        attempts = int(existing.get("attempts", 0)) + 1
        best_level = max(int(existing.get("best_level", 0)), overall_level)

        # 掌握度平滑更新（新评分权重 0.5，旧掌握度权重 0.5，再叠加 delta）
        old_mastery = float(existing.get("mastery", 0.0))
        level_mastery = overall_level / 5.0
        mastery = round(max(0.0, min(1.0, old_mastery * 0.5 + level_mastery * 0.5 + mastery_delta)), 3)

        progress = {
            "user_id": self.user_id,
            "question_id": question_id,
            "attempts": attempts,
            "best_level": best_level,
            "last_scores": scores,
            "missing_points": missing_points,
            "last_reviewed_at": now,
            "next_review_at": _next_review_at(overall_level),
            "mastery": mastery,
        }
        self._data[question_id] = progress
        _save_all(self.user_id, self._data)
        return QuestionProgress(**progress)
