"""造一批新任务，追加到 tasks.json（进行中的任务列表）。

任务 ID 遵循前端 makeTaskId() 规则：task_ + base36 时间戳。
生成后写入 memory/task_index/tasks.json，状态为 active，会显示在「进行中的任务」。
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TASKS_FILE = "memory/task_index/tasks.json"

# 新任务：主题 + 图标（图标取自前端 COMMON_ICONS）
NEW_TASKS = [
    {"title": "向量数据库选型", "icon": "🧮"},
    {"title": "多Agent协作", "icon": "🔗"},
    {"title": "LLM评估体系", "icon": "📊"},
    {"title": "函数调用与工具设计", "icon": "🛠️"},
    {"title": "模型微调与RAG取舍", "icon": "🎯"},
    {"title": "推理与规划", "icon": "🧠"},
]


def make_task_id(existing_ids: set[str]) -> str:
    """生成不冲突的 task_id（base36 时间戳，与前端一致）。"""
    while True:
        tid = f"task_{int(time.time() * 1000):x}"
        # 前端是 toString(36)，Python 用 hex 更贴近，但都是 base36 风格字符串即可，
        # 只要唯一且不冲突即可；这里直接用 base36 编码
        tid = f"task_{_to_base36(int(time.time() * 1000))}"
        if tid not in existing_ids:
            return tid


def _to_base36(n: int) -> str:
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    if n == 0:
        return "0"
    s = ""
    while n:
        s = chars[n % 36] + s
        n //= 36
    return s


def main() -> None:
    if not os.path.exists(TASKS_FILE):
        print(f"找不到 {TASKS_FILE}")
        sys.exit(1)

    with open(TASKS_FILE, "r", encoding="utf-8") as f:
        tasks = json.load(f)

    existing_ids = {t["id"] for t in tasks}
    now = datetime.now()

    added = []
    for i, spec in enumerate(NEW_TASKS):
        tid = make_task_id(existing_ids)
        existing_ids.add(tid)
        # 错开时间，让列表顺序稳定（倒序展示时新任务靠前）
        ts = (now - timedelta(seconds=i)).isoformat()
        task = {
            "id": tid,
            "created_at": ts,
            "title": spec["title"],
            "icon": spec["icon"],
            "status": "active",
            "updated_at": ts,
        }
        tasks.append(task)
        added.append(task)
        print(f"  + {tid}  {spec['icon']}  {spec['title']}")

    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)

    print(f"\n完成，共新增 {len(added)} 个任务（状态 active）。")
    print("刷新前端任务侧边栏即可看到（或触发 tasks-updated 事件）。")


if __name__ == "__main__":
    main()
