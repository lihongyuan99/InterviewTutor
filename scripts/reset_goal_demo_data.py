#!/usr/bin/env python3
"""Precisely remove generated content for the two known demo goal IDs.

The task records themselves are retained so the HTTP seeder can upsert them.
The default mode is a dry run; pass ``--apply`` to perform the reset.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MEMORY_ROOT = PROJECT_ROOT / "memory"
GOAL_IDS = {
    "task_demo_recent_ai_agent",
    "task_demo_archived_llm_platform",
}


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def matching_json_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return [
        path
        for path in folder.glob("*.json")
        if read_json(path).get("goal_id") in GOAL_IDS
    ]


def collect_files() -> list[Path]:
    files: set[Path] = set()
    sessions_dir = MEMORY_ROOT / "sessions"
    for goal_id in GOAL_IDS:
        files.update(sessions_dir.glob(f"{goal_id}__*.json"))
        files.add(MEMORY_ROOT / "notes" / "task" / f"{goal_id}.json")
        files.add(MEMORY_ROOT / "notes" / "task" / f"{goal_id}.md")
        daily_dir = MEMORY_ROOT / "notes" / "daily" / goal_id
        if daily_dir.exists():
            files.update(daily_dir.glob("*"))
    files.update(matching_json_files(MEMORY_ROOT / "interview_sessions"))
    files.update(matching_json_files(MEMORY_ROOT / "interview_reports"))
    return sorted(path for path in files if path.is_file())


def reset_progress(apply: bool) -> list[str]:
    path = MEMORY_ROOT / "interview_goal_progress" / "local_user.json"
    document = read_json(path)
    goals = document.get("goals")
    if not isinstance(goals, dict):
        return []
    found = sorted(goal_id for goal_id in GOAL_IDS if goal_id in goals)
    if apply and found:
        for goal_id in found:
            goals.pop(goal_id, None)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    files = collect_files()
    progress_keys = reset_progress(apply=False)
    action = "Removing" if args.apply else "Would remove"
    print(f"{action} {len(files)} files:")
    for path in files:
        print(f"  {path.relative_to(PROJECT_ROOT)}")
    print(f"{action} {len(progress_keys)} progress goal keys:")
    for goal_id in progress_keys:
        print(f"  {goal_id}")

    if args.apply:
        for path in files:
            path.unlink()
        reset_progress(apply=True)
        for goal_id in GOAL_IDS:
            daily_dir = MEMORY_ROOT / "notes" / "daily" / goal_id
            if daily_dir.exists() and not any(daily_dir.iterdir()):
                daily_dir.rmdir()
        print("Reset complete. Task metadata was retained.")
    else:
        print("Dry run only. Re-run with --apply to perform this exact reset.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
