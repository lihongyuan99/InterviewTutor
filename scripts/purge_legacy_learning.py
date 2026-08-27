#!/usr/bin/env python3
"""Remove pre-goal learning tasks and their task-scoped local data.

The command is dry-run by default. Pass ``--apply`` to perform the purge.
Interview goals are identified explicitly by ``kind == \"interview_goal\"`` and
are never included in the removal set.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MEMORY_ROOT = PROJECT_ROOT / "memory"
TASK_INDEX = MEMORY_ROOT / "task_index" / "tasks.json"


def load_task_list(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def write_task_list(path: Path, tasks: list[dict[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.purge.tmp")
    temporary.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def discover_task_scoped_ids() -> set[str]:
    task_ids: set[str] = set()

    for path in (MEMORY_ROOT / "sessions").glob("task_*__*.json"):
        task_ids.add(path.name.split("__", 1)[0])
    for path in (MEMORY_ROOT / "notes" / "task").glob("task_*"):
        task_ids.add(path.stem)
    for path in (MEMORY_ROOT / "notes" / "daily").glob("task_*"):
        task_ids.add(path.name)
    for path in (MEMORY_ROOT / "kg_progress").glob("task_*.json"):
        task_ids.add(path.stem)
    for path in (MEMORY_ROOT / "vector_store").glob("task_*"):
        task_ids.add(path.name)

    return task_ids


def task_data_paths(task_ids: set[str]) -> list[Path]:
    paths: set[Path] = set()

    for path in (MEMORY_ROOT / "sessions").glob("task_*__*.json"):
        if path.name.split("__", 1)[0] in task_ids:
            paths.add(path)
    for path in (MEMORY_ROOT / "notes" / "task").glob("task_*"):
        if path.stem in task_ids:
            paths.add(path)
    for path in (MEMORY_ROOT / "notes" / "daily").glob("task_*"):
        if path.name in task_ids:
            paths.add(path)
    for path in (MEMORY_ROOT / "kg_progress").glob("task_*.json"):
        if path.stem in task_ids:
            paths.add(path)
    for path in (MEMORY_ROOT / "vector_store").glob("task_*"):
        if path.name in task_ids:
            paths.add(path)

    return sorted(paths)


def purge(apply: bool) -> None:
    tasks = load_task_list(TASK_INDEX)
    interview_goals = [item for item in tasks if item.get("kind") == "interview_goal"]
    goal_ids = {str(item.get("id")) for item in interview_goals if item.get("id")}
    legacy_tasks = [item for item in tasks if item.get("kind", "legacy_learning") == "legacy_learning"]
    legacy_ids = {str(item.get("id")) for item in legacy_tasks if item.get("id")}
    orphaned_old_ids = discover_task_scoped_ids() - goal_ids - legacy_ids
    obsolete_ids = legacy_ids | orphaned_old_ids
    data_paths = task_data_paths(obsolete_ids)

    print(f"Interview goals preserved: {len(interview_goals)}")
    print(f"Legacy task records removed: {len(legacy_tasks)}")
    print(f"Orphaned pre-goal task IDs removed: {len(orphaned_old_ids)}")
    print(f"Task-scoped files/directories removed: {len(data_paths)}")
    for item in legacy_tasks:
        print(f"  legacy {item.get('id')}  {item.get('title', '')}")
    for task_id in sorted(orphaned_old_ids):
        print(f"  orphan {task_id}")

    if not apply:
        print("Dry run only; pass --apply to delete these records and files.")
        return

    write_task_list(TASK_INDEX, interview_goals)

    backup_dir = MEMORY_ROOT / "task_index" / "backup"
    for path in backup_dir.glob("*.json"):
        backup_tasks = load_task_list(path)
        if backup_tasks:
            write_task_list(
                path,
                [item for item in backup_tasks if item.get("kind") == "interview_goal"],
            )

    for path in data_paths:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    print("Legacy learning data purge completed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform the irreversible purge")
    args = parser.parse_args()
    purge(apply=args.apply)


if __name__ == "__main__":
    main()
