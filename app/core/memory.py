from __future__ import annotations

import os
import datetime
import hashlib
import json
from typing import Dict, Any, List, Optional
from langchain_core.messages import messages_to_dict, messages_from_dict, BaseMessage
from langchain_core.messages import HumanMessage, AIMessage

from app.core.models import AgentState
from app.utils import file_io

# Paths Configuration
MEMORY_DIR = "memory/sessions"
NOTES_DIR = "memory/notes"
TASK_INDEX_DIR = "memory/task_index"
TASK_INDEX_PATH = os.path.join(TASK_INDEX_DIR, "tasks.json")

# 防重复总结标记（内存级别）
_SUMMARIZING_SESSIONS = set()

# 任务自动命名：占位/未命名标题集合，命中则视为「尚未起名」
_PLACEHOLDER_TITLES = {"新的学习", "学习任务", "General Knowledge", ""}

# 触发自动命名的累计用户消息数阈值
AUTO_TITLE_MIN_USER_MSGS = 4

# 防重复自动命名标记（内存级别，避免同一任务并发/重复触发 LLM）
_AUTO_TITLING_TASKS = set()

# 异步调度用的锁，避免在事件循环中重复创建后台任务
import threading as _threading
_auto_title_lock = _threading.Lock()

# 会话快照、指标和后台摘要可能并发写同一个 JSON；按会话串行化写入，
# 避免共享 ``.tmp`` 文件互相覆盖。
_session_locks_guard = _threading.Lock()
_session_locks: Dict[str, _threading.RLock] = {}
_maintenance_lock = _threading.Lock()
_MAINTAINING_SESSIONS: set[str] = set()


def _get_session_lock(session_id: str) -> _threading.RLock:
    with _session_locks_guard:
        return _session_locks.setdefault(session_id, _threading.RLock())


def _get_daily_note_path(task_id: str, date: str) -> str:
    return os.path.join(NOTES_DIR, "daily", task_id, f"{date}.md")


def _get_task_note_path(task_id: str) -> str:
    return os.path.join(NOTES_DIR, "task", f"{task_id}.md")

def _get_task_plan_path(task_id: str) -> str:
    return os.path.join(NOTES_DIR, "task", f"{task_id}.json")


def _load_task_index() -> List[Dict[str, Any]]:
    if not os.path.exists(TASK_INDEX_PATH):
        return []
    try:
        data = file_io.load_json(TASK_INDEX_PATH)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _save_task_index(items: List[Dict[str, Any]]):
    _backup_task_index()
    file_io.save_json(items, TASK_INDEX_PATH)


def _backup_task_index(max_backups: int = 10):
    """写入前备份当前 tasks.json，防止意外清空后无法恢复。

    每次写入前，将现有文件复制为带时间戳的备份，保留最近 ``max_backups`` 份。
    仅当现有文件非空时才备份（空文件无备份价值）。
    """
    import shutil
    import time

    if not os.path.exists(TASK_INDEX_PATH):
        return
    try:
        data = file_io.load_json(TASK_INDEX_PATH)
    except Exception:
        return
    # 空列表无备份价值，跳过（避免备份污染）
    if not isinstance(data, list) or len(data) == 0:
        return

    backup_dir = os.path.join(TASK_INDEX_DIR, "backup")
    os.makedirs(backup_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"tasks_{ts}.json")
    try:
        shutil.copy2(TASK_INDEX_PATH, backup_path)
    except Exception:
        return

    # 清理超出数量的旧备份
    backups = sorted(
        (f for f in os.listdir(backup_dir) if f.startswith("tasks_") and f.endswith(".json")),
        reverse=True,
    )
    for old in backups[max_backups:]:
        try:
            os.remove(os.path.join(backup_dir, old))
        except Exception:
            pass


def _normalize_task_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Return the public task shape without rewriting legacy task data."""
    normalized = dict(item)
    normalized.setdefault("kind", "legacy_learning")
    normalized.setdefault("target_role", None)
    normalized.setdefault("target_companies", [])
    normalized.setdefault("interview_date", None)
    normalized.setdefault("experience_level", None)
    return normalized


def list_tasks(
    status: Optional[str] = None,
    kind: Optional[str] = None,
) -> List[Dict[str, Any]]:
    tasks = [_normalize_task_item(item) for item in _load_task_index()]
    if status:
        tasks = [item for item in tasks if item.get("status") == status]
    if kind:
        tasks = [item for item in tasks if item.get("kind") == kind]
    tasks.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return tasks


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    for item in _load_task_index():
        if item.get("id") == task_id:
            return _normalize_task_item(item)
    return None


def upsert_task(
    task_id: str,
    title: str,
    icon: str,
    status: str = "active",
    *,
    kind: Optional[str] = None,
    target_role: Optional[str] = None,
    target_companies: Optional[List[str]] = None,
    interview_date: Optional[str] = None,
    experience_level: Optional[str] = None,
    resume_id: Optional[str] = None,
) -> Dict[str, Any]:
    now = datetime.datetime.now().isoformat()
    tasks = _load_task_index()
    existing = None
    for item in tasks:
        if item.get("id") == task_id:
            existing = item
            break

    if existing is None:
        existing = {
            "id": task_id,
            "created_at": now,
        }
        tasks.insert(0, existing)

    existing.update({
        "title": title,
        "icon": icon,
        "status": status,
        "updated_at": now,
    })
    if kind is not None:
        existing["kind"] = kind
    if target_role is not None:
        existing["target_role"] = target_role
    if target_companies is not None:
        existing["target_companies"] = target_companies
    if interview_date is not None:
        existing["interview_date"] = interview_date
    if experience_level is not None:
        existing["experience_level"] = experience_level
    if resume_id is not None:
        existing["resume_id"] = resume_id
    _save_task_index(tasks)
    return _normalize_task_item(existing)


def update_task_status(task_id: str, status: str) -> Optional[Dict[str, Any]]:
    now = datetime.datetime.now().isoformat()
    tasks = _load_task_index()
    for item in tasks:
        if item.get("id") == task_id:
            item["status"] = status
            item["updated_at"] = now
            _save_task_index(tasks)
            return item
    return None


def update_task(task_id: str, title: Optional[str] = None, icon: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """更新任务的名称和/或图标"""
    now = datetime.datetime.now().isoformat()
    tasks = _load_task_index()
    for item in tasks:
        if item.get("id") == task_id:
            if title is not None:
                item["title"] = title
            if icon is not None:
                item["icon"] = icon
            item["updated_at"] = now
            _save_task_index(tasks)
            return _normalize_task_item(item)
    return None


def update_task_fields(task_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update explicitly supplied task fields, including nullable goal metadata."""
    allowed = {
        "title",
        "icon",
        "kind",
        "target_role",
        "target_companies",
        "interview_date",
        "experience_level",
        "resume_id",
    }
    payload = {key: value for key, value in updates.items() if key in allowed}
    if not payload:
        return None

    now = datetime.datetime.now().isoformat()
    tasks = _load_task_index()
    for item in tasks:
        if item.get("id") == task_id:
            item.update(payload)
            item["updated_at"] = now
            _save_task_index(tasks)
            return _normalize_task_item(item)
    return None


def delete_task(task_id: str) -> bool:
    tasks = _load_task_index()
    next_tasks = [item for item in tasks if item.get("id") != task_id]
    if len(next_tasks) == len(tasks):
        return False
    _save_task_index(next_tasks)
    return True


def _file_updated_at(path: str) -> str:
    if not os.path.exists(path):
        return ""
    ts = os.path.getmtime(path)
    return datetime.datetime.fromtimestamp(ts).isoformat()


def _date_from_session_meta(session: Dict[str, Any]) -> str:
    """
    从 session 元数据中提取日期。

    优先级：
    1. session_id 中的日期（创建日期）- 用于准确归类
    2. last_updated 中的日期（最后更新日期）- 兜底
    """
    # 优先从 session_id 提取日期（创建日期）
    session_id = session.get("session_id", "")
    parts = session_id.split("__")
    if len(parts) >= 2 and len(parts[1]) == 8 and parts[1].isdigit():
        raw = parts[1]
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"

    # 兜底：使用 last_updated
    last_updated = session.get("last_updated", "")
    if isinstance(last_updated, str) and len(last_updated) >= 10 and "-" in last_updated:
        return last_updated[:10]

    return datetime.datetime.now().strftime("%Y-%m-%d")


def _display_date(date_str: str) -> str:
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.month}月{dt.day}日"
    except Exception:
        return date_str


def _read_daily_note_sections(task_id: str, date: str) -> Dict[str, List[str]]:
    path = _get_daily_note_path(task_id, date)
    if not os.path.exists(path):
        return {"key_learnings": [], "review_areas": []}

    try:
        content = file_io.load_text(path)
    except Exception:
        return {"key_learnings": [], "review_areas": []}

    key_learnings: List[str] = []
    review_areas: List[str] = []
    section = ""
    for line in content.splitlines():
        txt = line.strip()
        if txt.startswith("##"):
            if "今日要点" in txt:
                section = "key"
            elif "待复习" in txt:
                section = "review"
            else:
                section = ""
            continue

        if txt.startswith("-"):
            item = txt[1:].strip()
            if not item:
                continue
            if section == "key":
                key_learnings.append(item)
            elif section == "review":
                review_areas.append(item)

    return {
        "key_learnings": key_learnings,
        "review_areas": review_areas,
    }

def _get_session_path(session_id: str) -> str:
    """Get the absolute path for a session JSON file."""
    if not session_id:
        raise ValueError("Session ID cannot be empty")
    return os.path.join(MEMORY_DIR, f"{session_id}.json")

def _get_note_path(session_id: str, topic: Optional[str] = None) -> str:
    """
    Get the absolute path for a markdown note file.
    If topic is provided, include it in the filename for better readability.
    """
    # Sanitize topic to be filename friendly if present
    filename = f"{session_id}"
    if topic:
        # Simple sanitization: replace spaces with _, remove non-alphanumeric chars
        safe_topic = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in topic)
        filename += f"_{safe_topic}"
    
    return os.path.join(NOTES_DIR, f"{filename}.md")

def save_session(state: AgentState, *, index_for_rag: bool = True) -> str:
    """
    Persist the current agent state to disk (Full Snapshot).

    1. Saves the raw session data (messages, metadata) to JSON.
    2. If a conclusion note exists (summary_output), saves it to Markdown.
    3. [RAG] Indexes conversation pairs into vector store (if enabled).

    Returns:
        The path to the saved JSON session file.
    """
    session_id = state.get("session_id")
    if not session_id:
        # If no session ID, we can't save. Ideally should generate one or error.
        # For now, let's assume session_id is always present in State as per logical flow.
        return ""

    # 1. Serialize Messages (LangChain -> List[Dict])
    # This handles HumanMessage, AIMessage, ToolMessage, etc. automatically.
    serialized_messages = messages_to_dict(state["messages"])

    # 2. Construct Session Storage Object
    session_data = {
        "session_id": session_id,
        "task_id": state.get("task_id"),
        "last_updated": datetime.datetime.now().isoformat(),
        "topic": state.get("current_topic", "General"),
        "conversation_summary": state.get("conversation_summary"), # The Compressed Context (B)
        "summarized_msg_count": state.get("summarized_msg_count", 0),
        "messages": serialized_messages # The Full Log (A)
    }

    # 3. Save Session JSON (Overwrite Mode)
    json_path = _get_session_path(session_id)
    with _get_session_lock(session_id):
        file_io.save_json(session_data, json_path)

    # 4. Save Markdown Note (if applicable)
    # Only save note if we are in a concluding state and actually have a note generated
    if state.get("should_exit") and state.get("summary_output"):
        note_content = state["summary_output"]

        # Add metadata header to the note
        header = f"""---
source_session: {session_id}
date: {datetime.datetime.now().strftime("%Y-%m-%d")}
topic: {state.get("current_topic", "General")}
---

"""
        full_note = header + note_content

        note_path = _get_note_path(session_id, state.get("current_topic"))
        file_io.save_text(full_note, note_path)

    # 5. [RAG] Index conversation into vector store (if enabled)
    if index_for_rag:
        _index_session_for_rag(
            session_id=session_id,
            task_id=state.get("task_id"),
            messages=serialized_messages,
            topic=state.get("current_topic", "General")
        )

    # 6. 任务自动命名：会话累计足够用户消息且标题仍为占位时，异步生成标题回写
    maybe_auto_title_task(state.get("task_id"), serialized_messages)

    return json_path


def _message_prefix_digest(messages: List[Dict[str, Any]], end: int) -> str:
    payload = json.dumps(
        messages[:end],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _commit_session_summary(
    session_id: str,
    *,
    expected_cursor: int,
    expected_prefix_digest: str,
    new_summary: str,
    new_cursor: int,
) -> bool:
    """Apply a background summary without replacing newer chat messages."""

    path = _get_session_path(session_id)
    with _get_session_lock(session_id):
        try:
            current = file_io.load_json(path)
        except (FileNotFoundError, TypeError, ValueError):
            return False
        messages = current.get("messages")
        if not isinstance(messages, list) or len(messages) < new_cursor:
            return False
        if int(current.get("summarized_msg_count", 0) or 0) != expected_cursor:
            return False
        if _message_prefix_digest(messages, new_cursor) != expected_prefix_digest:
            return False
        current["conversation_summary"] = new_summary
        current["summarized_msg_count"] = new_cursor
        file_io.save_json(current, path)
        return True


def _update_learning_profile_from_messages(
    messages: List[BaseMessage],
    *,
    user_id: str,
) -> None:
    from app.core import learning_profile, profile_store

    assistant_index = None
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], AIMessage):
            assistant_index = index
            break
    if assistant_index is None:
        return

    user_text = ""
    for index in range(assistant_index - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            user_text = messages[index].content or ""
            break
    assistant_text = messages[assistant_index].content or ""
    cards = learning_profile.extract_learning_facts(
        user_text=user_text,
        assistant_text=assistant_text,
        source=user_id,
    )
    if not cards:
        return
    profile = profile_store.load_profile(user_id)
    profile = learning_profile.upsert_cards(profile, cards)
    profile_store.save_profile(profile)


def run_session_maintenance(
    session_id: str,
    *,
    user_id: str = "local_user",
) -> bool:
    """Compress, index and profile a saved reply outside the response path."""

    with _maintenance_lock:
        if session_id in _MAINTAINING_SESSIONS:
            return False
        _MAINTAINING_SESSIONS.add(session_id)

    try:
        path = _get_session_path(session_id)
        try:
            raw = file_io.load_json(path)
        except (FileNotFoundError, TypeError, ValueError):
            return False

        serialized_messages = raw.get("messages")
        if not isinstance(serialized_messages, list):
            return False
        messages = messages_from_dict(serialized_messages)
        expected_cursor = int(raw.get("summarized_msg_count", 0) or 0)
        state = {
            "messages": messages,
            "task_id": raw.get("task_id"),
            "session_id": raw.get("session_id", session_id),
            "current_topic": raw.get("topic", "General"),
            "conversation_summary": raw.get("conversation_summary") or "",
            "summarized_msg_count": expected_cursor,
        }

        from app.core import context_rag

        new_summary, new_cursor = context_rag.manage_memory(state)
        if new_cursor > expected_cursor and new_summary != state["conversation_summary"]:
            prefix_digest = _message_prefix_digest(serialized_messages, new_cursor)
            if _commit_session_summary(
                session_id,
                expected_cursor=expected_cursor,
                expected_prefix_digest=prefix_digest,
                new_summary=new_summary or "",
                new_cursor=new_cursor,
            ):
                print(
                    f"🧠 Memory Compressed! New summary length: {len(new_summary or '')}, "
                    f"Cursor: {new_cursor}"
                )

        # Reload so indexing never misses messages appended while compression ran.
        try:
            latest = file_io.load_json(path)
        except (FileNotFoundError, TypeError, ValueError):
            return False
        latest_serialized = latest.get("messages")
        if not isinstance(latest_serialized, list):
            return False
        _index_session_for_rag(
            session_id=latest.get("session_id", session_id),
            task_id=latest.get("task_id"),
            messages=latest_serialized,
            topic=latest.get("topic", "General"),
        )
        _update_learning_profile_from_messages(
            messages_from_dict(latest_serialized),
            user_id=user_id,
        )
        return True
    except Exception as exc:
        print(f"⚠️ 会话后台维护失败（{session_id}）：{exc}")
        return False
    finally:
        with _maintenance_lock:
            _MAINTAINING_SESSIONS.discard(session_id)


def _index_session_for_rag(
    session_id: str,
    task_id: Optional[str],
    messages: List[Dict[str, Any]],
    topic: str = "General"
):
    """
    Index session messages into vector store for RAG retrieval.

    This is a non-blocking operation that gracefully handles errors.
    Set RAG_ENABLED=False to disable this feature.

    Args:
        session_id: Session identifier
        task_id: Task identifier for vector store isolation
        messages: Serialized message list
        topic: Conversation topic
    """
    # Check if RAG is enabled via config
    try:
        from app.core.config import settings
        if not settings.RAG_ENABLED:
            return
    except ImportError:
        return

    if not task_id or not messages:
        return

    try:
        from app.core.vector_store import index_session

        # Convert serialized messages to simple format.
        # messages_to_dict 输出为 {type, data: {content}} 嵌套结构，
        # 需从 data.content 取内容（兼容扁平格式）。
        simple_messages = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            msg_type = msg.get("type", "")
            content = msg.get("content")
            if content is None and isinstance(msg.get("data"), dict):
                content = msg["data"].get("content")
            if isinstance(content, list):
                # 多模态/分块内容，仅拼接文本块
                content = "".join(
                    str(c.get("text", "")) if isinstance(c, dict) else str(c)
                    for c in content
                )
            content = content or ""
            if msg_type == "human":
                simple_messages.append({"role": "user", "content": content})
            elif msg_type == "ai":
                simple_messages.append({"role": "assistant", "content": content})

        # Index into vector store
        index_session(
            session_id=session_id,
            task_id=task_id,
            messages=simple_messages,
            topic=topic
        )

    except ImportError as e:
        # RAG dependencies not installed, skip silently
        print(f"[RAG] Vector store not available: {e}")
    except Exception as e:
        # Don't fail the save operation if RAG indexing fails
        print(f"[RAG] Failed to index session: {e}")


def _count_user_messages(messages: List[Dict[str, Any]]) -> int:
    """统计序列化消息里的用户消息数。

    兼容两种格式：
    - messages_to_dict 输出：{type: "human"/"ai", data: {content: ...}}
    - 扁平格式：{type/role: ..., content: ...}
    """
    count = 0
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        msg_type = m.get("type") or m.get("role")
        if msg_type not in ("human", "user"):
            continue
        content = m.get("content")
        if content is None and isinstance(m.get("data"), dict):
            content = m["data"].get("content")
        if isinstance(content, list):
            # 多模态/分块内容，视为非空即可
            has_text = any(
                str(c.get("text", "")).strip() if isinstance(c, dict) else str(c).strip()
                for c in content
            )
            if has_text:
                count += 1
        elif content and str(content).strip():
            count += 1
    return count


def _task_has_placeholder_title(task_id: str) -> bool:
    """判断任务标题是否仍为占位/未命名状态。"""
    for item in _load_task_index():
        if item.get("id") == task_id:
            return item.get("title") in _PLACEHOLDER_TITLES
    # 任务尚未入索引（纯草稿阶段），视为占位，允许后续自动命名
    return True


def _auto_title_worker(task_id: str) -> None:
    """后台线程执行：读取会话、生成标题、回写任务索引。"""
    try:
        from app.core.summary.generator import summary_generator

        # 汇总该任务下所有会话的用户消息作为标题依据
        sessions = list_task_sessions(task_id)
        all_messages: List[Dict[str, str]] = []
        for s in sessions:
            msgs = get_session_messages(s.get("session_id", ""))
            if not msgs:
                continue
            all_messages.extend(msgs.get("messages", []))

        title = summary_generator.generate_task_title(all_messages)
        if title and title not in _PLACEHOLDER_TITLES:
            # 仅当标题仍为占位时才回写，避免覆盖用户手动命名
            if _task_has_placeholder_title(task_id):
                update_task(task_id, title=title)
                print(f"✨ 已自动为任务 {task_id} 命名：{title}")
    except Exception as e:
        print(f"⚠️ 任务自动命名失败（{task_id}）：{e}")
    finally:
        _AUTO_TITLING_TASKS.discard(task_id)


def maybe_auto_title_task(task_id: Optional[str], messages: List[Dict[str, Any]]) -> None:
    """触发任务自动命名（幂等、异步、不阻塞主流程）。

    条件：
    1. 有 task_id 且标题仍为占位；
    2. 累计用户消息数达到阈值；
    3. 该任务当前没有正在进行的自动命名任务。

    通过线程池后台执行，绝不阻塞对话主流程。
    """
    if not task_id:
        return
    if _count_user_messages(messages or []) < AUTO_TITLE_MIN_USER_MSGS:
        return
    if task_id in _AUTO_TITLING_TASKS:
        return

    with _auto_title_lock:
        # 双重检查，防止并发进入
        if task_id in _AUTO_TITLING_TASKS:
            return
        if not _task_has_placeholder_title(task_id):
            return
        _AUTO_TITLING_TASKS.add(task_id)

    try:
        import concurrent.futures
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        executor.submit(_auto_title_worker, task_id)
    except Exception as e:
        _AUTO_TITLING_TASKS.discard(task_id)
        print(f"⚠️ 任务自动命名调度失败（{task_id}）：{e}")


# ==================== 防重复总结标记 ====================

def set_session_summarizing(session_id: str, is_summarizing: bool = True):
    """设置会话的总结中状态"""
    global _SUMMARIZING_SESSIONS
    if is_summarizing:
        _SUMMARIZING_SESSIONS.add(session_id)
    else:
        _SUMMARIZING_SESSIONS.discard(session_id)


def is_session_summarizing(session_id: str) -> bool:
    """检查会话是否正在生成总结中"""
    return session_id in _SUMMARIZING_SESSIONS


def load_session(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Load a session from disk and reconstruct the AgentState.
    """
    json_path = _get_session_path(session_id)
    
    try:
        data = file_io.load_json(json_path)
    except FileNotFoundError:
        return None
        
    # Reconstruct Messages (List[Dict] -> List[BaseMessage])
    messages = messages_from_dict(data.get("messages", []))
    
    # Reconstruct Partial State
    # Note: We don't restore everything (like 'plan' or 'tutor_output'), 
    # just the persistent memory parts.
    return {
        "messages": messages,
        "task_id": data.get("task_id"),
        "session_id": data.get("session_id"),
        "current_topic": data.get("topic"),
        "conversation_summary": data.get("conversation_summary"),
        "summarized_msg_count": data.get("summarized_msg_count", 0),
        # created_at/updated_at can be handled by the caller or added here if needed
    }


def _infer_task_id(task_id: Optional[str], session_id: str) -> str:
    if task_id:
        return task_id
    if "__" in session_id:
        return session_id.split("__")[0]
    return "task_default"


def list_task_sessions(task_id: str) -> List[Dict[str, Any]]:
    """
    列出某个 task_id 下的所有会话元信息，按更新时间倒序。
    """
    if not os.path.exists(MEMORY_DIR):
        return []

    results: List[Dict[str, Any]] = []
    for filename in os.listdir(MEMORY_DIR):
        if not filename.endswith(".json"):
            continue
        session_id = filename[:-5]
        path = os.path.join(MEMORY_DIR, filename)
        try:
            data = file_io.load_json(path)
        except Exception:
            continue

        file_task_id = _infer_task_id(data.get("task_id"), data.get("session_id", session_id))
        if file_task_id != task_id:
            continue

        msgs = data.get("messages", [])
        results.append({
            "session_id": data.get("session_id", session_id),
            "task_id": file_task_id,
            "topic": data.get("topic", "General"),
            "last_updated": data.get("last_updated", ""),
            "message_count": len(msgs),
        })

    results.sort(key=lambda item: item.get("last_updated", ""), reverse=True)
    return results


def get_session_messages(session_id: str) -> Optional[Dict[str, Any]]:
    """
    返回某个 session 的消息列表（前端友好格式）。
    """
    path = _get_session_path(session_id)
    try:
        data = file_io.load_json(path)
    except FileNotFoundError:
        return None

    raw_messages = messages_from_dict(data.get("messages", []))
    normalized: List[Dict[str, Any]] = []

    for index, msg in enumerate(raw_messages):
        if isinstance(msg, HumanMessage):
            role = "user"
        elif isinstance(msg, AIMessage):
            role = "assistant"
        else:
            continue

        content = getattr(msg, "content", "") or ""
        ts = ""
        if isinstance(msg, BaseMessage):
            ts = (
                getattr(msg, "additional_kwargs", {}).get("timestamp")
                or data.get("last_updated", "")
                or ""
            )

        additional_kwargs = getattr(msg, "additional_kwargs", {}) or {}
        reply_metrics = additional_kwargs.get("reply_metrics")
        if not isinstance(reply_metrics, dict):
            reply_metrics = None

        normalized.append({
            "message_id": f"{session_id}-{index}",
            "role": role,
            "content": content,
            "timestamp": ts,
            "metrics": reply_metrics,
        })

    resolved_session_id = data.get("session_id", session_id)
    resolved_task_id = _infer_task_id(data.get("task_id"), resolved_session_id)
    return {
        "session_id": resolved_session_id,
        "task_id": resolved_task_id,
        "topic": data.get("topic", "General"),
        "last_updated": data.get("last_updated", ""),
        "messages": normalized,
    }


def attach_reply_metrics(session_id: str, metrics: Dict[str, Any]) -> bool:
    """Persist metrics on the latest assistant message without re-saving state."""

    path = _get_session_path(session_id)
    with _get_session_lock(session_id):
        try:
            data = file_io.load_json(path)
        except (FileNotFoundError, TypeError, ValueError):
            return False

        messages = data.get("messages")
        if not isinstance(messages, list):
            return False

        normalized_metrics = {
            key: max(0, int(metrics.get(key, 0) or 0))
            for key in (
                "elapsed_ms",
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "llm_calls",
            )
        }
        for raw_message in reversed(messages):
            if not isinstance(raw_message, dict) or raw_message.get("type") != "ai":
                continue
            message_data = raw_message.get("data")
            if not isinstance(message_data, dict):
                return False
            additional_kwargs = message_data.get("additional_kwargs")
            if not isinstance(additional_kwargs, dict):
                additional_kwargs = {}
                message_data["additional_kwargs"] = additional_kwargs
            additional_kwargs["reply_metrics"] = normalized_metrics
            file_io.save_json(data, path)
            return True
        return False


def get_daily_note(task_id: str, date: str) -> Dict[str, Any]:
    path = _get_daily_note_path(task_id, date)
    if not os.path.exists(path):
        return {
            "task_id": task_id,
            "date": date,
            "content": "",
            "updated_at": "",
        }
    return {
        "task_id": task_id,
        "date": date,
        "content": file_io.load_text(path),
        "updated_at": _file_updated_at(path),
    }


def save_daily_note(task_id: str, date: str, content: str) -> Dict[str, Any]:
    path = _get_daily_note_path(task_id, date)
    file_io.save_text(content, path)
    return {
        "task_id": task_id,
        "date": date,
        "content": content,
        "updated_at": _file_updated_at(path),
    }

def _load_task_plan(task_id: str) -> Dict[str, Any]:
    path = _get_task_plan_path(task_id)
    if not os.path.exists(path):
        return {}
    try:
        data = file_io.load_json(path)
        if isinstance(data, dict):
            if "plan" not in data and "nextSteps" in data:
                data["plan"] = data.get("nextSteps")
            data.pop("nextSteps", None)
            return data
        return {}
    except Exception:
        return {}


def _resolve_task_note_updated_at(plan_path: str, note_path: str) -> str:
    plan_ts = _file_updated_at(plan_path) if os.path.exists(plan_path) else ""
    note_ts = _file_updated_at(note_path) if os.path.exists(note_path) else ""
    return max(plan_ts, note_ts)

def get_task_plan_data(task_id: str) -> Dict[str, Any]:
    return _load_task_plan(task_id)

def has_task_plan(task_id: str) -> bool:
    plan = _load_task_plan(task_id)
    if not plan:
        return False
    for key in (
        "taskTitle",
        "overallSummary",
        "coreKnowledge",
        "masteryLevel",
        "milestones",
        "plan",
    ):
        value = plan.get(key)
        if isinstance(value, list) and value:
            return True
        if isinstance(value, str) and value.strip():
            return True
    return False


def get_task_note(task_id: str) -> Dict[str, Any]:
    note_path = _get_task_note_path(task_id)
    plan_path = _get_task_plan_path(task_id)
    plan_data = _load_task_plan(task_id)
    plan_data.pop("nextSteps", None)

    # 优先从 task_note.txt 文件读取用户笔记内容
    # 这样用户的个人笔记不会被计划数据覆盖
    content = ""
    if os.path.exists(note_path):
        content = file_io.load_text(note_path)
    elif "userNotes" in plan_data:
        content = plan_data.get("userNotes") or ""

    response = {
        "task_id": task_id,
        "content": content,
        "userNotes": content,
        "updated_at": _resolve_task_note_updated_at(plan_path, note_path),
    }
    response.update(plan_data)
    response["task_id"] = task_id
    return response


def save_task_note(task_id: str, content: str) -> Dict[str, Any]:
    note_path = _get_task_note_path(task_id)
    plan_path = _get_task_plan_path(task_id)
    plan_data = _load_task_plan(task_id)

    plan_data["task_id"] = task_id
    plan_data["userNotes"] = content
    plan_data.pop("nextSteps", None)
    file_io.save_text(content, note_path)
    file_io.save_json(plan_data, plan_path)
    title = plan_data.get("taskTitle")
    icon = plan_data.get("taskIcon")
    if title or icon:
        update_task(task_id, title=title, icon=icon)
    return get_task_note(task_id)


def save_task_plan(task_id: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    note_path = _get_task_note_path(task_id)
    plan_path = _get_task_plan_path(task_id)
    plan_data = _load_task_plan(task_id)

    plan_data.update(plan)
    plan_data["task_id"] = task_id
    plan_data.pop("nextSteps", None)
    if "userNotes" in plan_data:
        file_io.save_text(plan_data.get("userNotes") or "", note_path)
    file_io.save_json(plan_data, plan_path)
    title = plan_data.get("taskTitle")
    icon = plan_data.get("taskIcon")
    if title or icon:
        update_task(task_id, title=title, icon=icon)
    return get_task_note(task_id)


def list_task_timeline(task_id: str) -> List[Dict[str, Any]]:
    """
    按 task_id 聚合出“按天”的时间线数据。
    """
    sessions = list_task_sessions(task_id)
    grouped: Dict[str, Dict[str, Any]] = {}

    for session in sessions:
        date_key = _date_from_session_meta(session)
        bucket = grouped.setdefault(
            date_key,
            {
                "date": date_key,
                "session_count": 0,
                "message_count": 0,
                "last_updated": "",
            },
        )
        bucket["session_count"] += 1
        bucket["message_count"] += int(session.get("message_count", 0))
        current_latest = bucket.get("last_updated", "")
        this_updated = session.get("last_updated", "")
        if this_updated > current_latest:
            bucket["last_updated"] = this_updated

    timeline: List[Dict[str, Any]] = []
    for index, date_key in enumerate(sorted(grouped.keys(), reverse=True), start=1):
        bucket = grouped[date_key]
        note_sections = _read_daily_note_sections(task_id, date_key)
        key_learnings = note_sections.get("key_learnings", [])
        review_areas = note_sections.get("review_areas", [])

        if not key_learnings:
            key_learnings = [
                f"当日共 {bucket['session_count']} 个会话",
                f"累计 {bucket['message_count']} 条消息",
            ]

        timeline.append(
            {
                "id": str(index),
                "date": date_key,
                "display_date": _display_date(date_key),
                "key_learnings": key_learnings,
                "review_areas": review_areas,
                "session_count": bucket["session_count"],
                "message_count": bucket["message_count"],
                "last_updated": bucket.get("last_updated", ""),
            }
        )

    return timeline
