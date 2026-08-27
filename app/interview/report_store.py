"""Persistent diagnostic and mock-interview reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from app.interview.models import InterviewReport


REPORT_DIR = "memory/interview_reports"


def _report_file(report_id: str) -> Path:
    return Path(REPORT_DIR) / f"{report_id}.json"


def save_report(report: InterviewReport) -> InterviewReport:
    path = _report_file(report.report_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def get_report(report_id: str) -> Optional[InterviewReport]:
    path = _report_file(report_id)
    if not path.exists():
        return None
    try:
        return InterviewReport(**json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def list_reports(
    *,
    user_id: str = "local_user",
    goal_id: Optional[str] = None,
) -> List[InterviewReport]:
    root = Path(REPORT_DIR)
    if not root.exists():
        return []
    reports: List[InterviewReport] = []
    for path in root.glob("*.json"):
        report = get_report(path.stem)
        if not report or report.user_id != user_id:
            continue
        if goal_id is not None and report.goal_id != goal_id:
            continue
        reports.append(report)
    reports.sort(key=lambda item: item.created_at, reverse=True)
    return reports
