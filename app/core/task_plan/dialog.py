"""
Task Plan Agent - Dialog Manager
"""
import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from app.core.task_plan.prompts import (
    DEFAULT_INIT_QUESTIONS,
    DEFAULT_TIME_QUESTION,
    DEFAULT_UPDATE_QUESTIONS,
    TIME_KEYWORDS,
    CONTENT_KEYWORDS,
    DEPTH_KEYWORDS,
    INTENSITY_KEYWORDS,
    PLAN_INTENT_KEYWORDS,
    LEARN_INTENT_KEYWORDS,
    YES_KEYWORDS,
    NO_KEYWORDS,
    EXIT_PLAN_KEYWORDS,
)
from app.core.task_plan.utils import _extract_plan_hints


def _contains_keywords(text: str, keywords: List[str]) -> bool:
    return any(k in text for k in keywords)


_REPLY_SPLIT_RE = re.compile(r"[，,。.!！?？；;：:\n]")
_REPLY_EDGE_CHARS = " \t\r\n，,。.!！?？；;：:\"'“”‘’"


def _reply_candidates(text: str) -> set[str]:
    """Normalize the full text and complete clauses of a short command.

    Matching complete clauses prevents words such as ``行列式`` and
    ``生成式`` from being mistaken for the replies ``行`` and ``生成``.
    """
    if not text:
        return set()
    stripped = text.strip()
    clauses = _REPLY_SPLIT_RE.split(stripped)
    candidates = set()
    for value in (stripped, *clauses):
        normalized = "".join(value.split()).strip(_REPLY_EDGE_CHARS)
        if normalized:
            candidates.add(normalized)
    return candidates


def _is_yes(text: str) -> bool:
    candidates = _reply_candidates(text)
    if not candidates:
        return False
    no_replies = {"".join(item.split()) for item in NO_KEYWORDS}
    if candidates & no_replies:
        return False
    yes_replies = {"".join(item.split()) for item in YES_KEYWORDS}
    yes_replies.update({"好", "好啊", "可以的", "需要的", "没问题"})
    return bool(candidates & yes_replies)


def _is_no(text: str) -> bool:
    candidates = _reply_candidates(text)
    no_replies = {"".join(item.split()) for item in NO_KEYWORDS}
    no_replies.update({"不了", "不必", "不需要了"})
    return bool(candidates & no_replies)


def _is_resume_plan_intent(text: str) -> bool:
    candidates = _reply_candidates(text)
    return bool(
        candidates
        & {
            "继续",
            "继续计划",
            "继续调整计划",
            "继续制定计划",
            "恢复计划",
            "恢复调整计划",
            "继续规划",
            "继续调整",
        }
    )


def _is_plan_confirm_intent(text: str) -> bool:
    candidates = _reply_candidates(text)
    return bool(
        candidates
        & {
            "确认",
            "确认计划",
            "保存",
            "保存计划",
            "就这样",
            "按这个执行",
            "开始执行",
            "计划没问题",
            "没问题",
            "可以",
            "好的",
        }
    )


def _is_exit_intent(text: str) -> bool:
    """检测用户是否有退出计划流程的意图"""
    if not text:
        return False
    trimmed = text.strip()
    if _is_resume_plan_intent(trimmed):
        return False
    if _reply_candidates(trimmed) & {"不结束", "不退出", "继续", "先继续"}:
        return False
    # 如果明确在提更新/时间细节，不视为退出
    if _has_update_points(trimmed):
        return False
    explicit_plan_exits = (keyword for keyword in EXIT_PLAN_KEYWORDS if "计划" in keyword)
    if any(keyword in trimmed for keyword in explicit_plan_exits):
        return True
    return bool(
        _reply_candidates(trimmed)
        & {
            "先不弄了",
            "算了",
            "算了吧",
            "停一停",
            "停一停吧",
            "先不",
            "不调整了",
            "先不调整了",
        }
    )


def _is_update_intent(text: str) -> bool:
    if not text:
        return False
    return _contains_keywords(text, PLAN_INTENT_KEYWORDS)


def _is_learn_intent(text: str) -> bool:
    if not text:
        return False
    return _contains_keywords(text, LEARN_INTENT_KEYWORDS)


def _detect_plan_intent(text: str, has_plan: bool) -> str:
    # 优先检测退出意图，避免用户说"退出计划"时重新进入计划流程
    if _is_exit_intent(text):
        return "none"
    if _is_update_intent(text):
        return "update" if has_plan else "init"
    if _is_learn_intent(text):
        return "learn"
    return "none"


def _build_plan_dialogue_text(plan_session: Dict[str, Any]) -> str:
    parts: List[str] = []
    for item in plan_session.get("messages", []):
        role = item.get("role")
        content = item.get("content") or ""
        if not content:
            continue
        tag = "User" if role == "user" else "Assistant"
        parts.append(f"{tag}: {content}")
    return "\n".join(parts)


def _build_plan_user_text(plan_session: Dict[str, Any]) -> str:
    """Combine user-authored plan context for deterministic slot checks."""
    parts: List[str] = []
    for key in ("context_messages", "messages"):
        for item in plan_session.get(key, []) or []:
            if item.get("role") != "user":
                continue
            content = (item.get("content") or "").strip()
            if content:
                parts.append(content)
    return "\n".join(parts)


def _extract_recent_dialogue(history_messages: Optional[List[Any]], limit: int = 12) -> List[Dict[str, str]]:
    if not history_messages:
        return []
    items: List[Dict[str, str]] = []
    for msg in reversed(history_messages):
        if isinstance(msg, HumanMessage):
            content = (msg.content or "").strip()
            if content:
                items.append({"role": "user", "content": content})
        elif isinstance(msg, AIMessage):
            content = (msg.content or "").strip()
            if content:
                items.append({"role": "assistant", "content": content})
        if len(items) >= limit:
            break
    return list(reversed(items))


def _has_time_signal(text: str) -> bool:
    hints = _extract_plan_hints(text)
    if hints.get("target_days") or hints.get("daily_hours"):
        return True
    if any(phrase in text for phrase in ("每天", "每周", "每月", "时长", "周期", "多久")):
        return True
    # Bare characters and domain terms such as “今天 / 周围 / 时间复杂度”
    # are not schedule constraints. “时间” only counts with a nearby
    # planning qualifier.
    return bool(
        re.search(
            r"(?:(?:学习|可用|空闲|投入|安排|调整|规划|限制|有|没).{0,4}时间"
            r"|时间.{0,4}(?:安排|投入|有限|充足|紧|约束|限制|不变|调整|改))",
            text,
        )
    )


def _has_depth_or_goal(text: str) -> bool:
    if _contains_keywords(text, DEPTH_KEYWORDS):
        return True
    if "目标" in text or "打算" in text or "想" in text:
        return True
    return False


def _has_update_points(text: str) -> bool:
    return (
        _has_time_signal(text)
        or _contains_keywords(text, CONTENT_KEYWORDS)
        or _contains_keywords(text, DEPTH_KEYWORDS)
        or _contains_keywords(text, INTENSITY_KEYWORDS)
    )


def _has_enough_info(text: str, mode: str) -> bool:
    hints = _extract_plan_hints(text)
    if mode == "update":
        return _has_update_points(text)
    has_goal = (
        _has_depth_or_goal(text)
        or _is_learn_intent(text)
        or _contains_keywords(text, CONTENT_KEYWORDS)
    )
    has_duration = hints.get("target_days") is not None
    has_effort = hints.get("daily_hours") is not None or bool(
        re.search(r"每周\s*\d+\s*(?:天|次)", text)
    )
    return has_goal and has_duration and has_effort


def _next_default_question(mode: str, turns: int) -> str:
    if mode == "update":
        idx = min(turns, len(DEFAULT_UPDATE_QUESTIONS) - 1)
        return DEFAULT_UPDATE_QUESTIONS[idx]
    idx = min(turns, len(DEFAULT_INIT_QUESTIONS) - 1)
    return DEFAULT_INIT_QUESTIONS[idx]


def _build_suggested_replies(question: str, mode: str) -> List[str]:
    text = (question or "").strip()
    has_time = _contains_keywords(text, TIME_KEYWORDS) or any(k in text for k in ["时间", "多久", "每天", "每周", "周期", "小时", "天", "周", "月"])
    has_content = _contains_keywords(text, CONTENT_KEYWORDS) or any(k in text for k in ["主题", "重点", "范围", "章节"])
    has_depth = _contains_keywords(text, DEPTH_KEYWORDS) or any(k in text for k in ["程度", "目标", "达到"])
    has_intensity = _contains_keywords(text, INTENSITY_KEYWORDS) or any(k in text for k in ["强度", "节奏", "进度"])

    signals = sum([has_time, has_content, has_depth, has_intensity])
    if mode == "update":
        if signals > 1:
            return ["调整时间安排", "增加实战项目", "降低学习强度"]
        if has_time:
            return ["把周期改成4周，每天1小时", "每周学习3天，每次2小时", "时间不变，想调整内容"]
        if has_content:
            return ["增加实战项目，减少理论", "重点放在面试相关内容", "想把某些章节删掉"]
        if has_intensity:
            return ["节奏放慢一点", "进度加快一些", "保持当前强度"]
        return ["调整时间安排", "增加实战项目", "降低学习强度"]

    if signals > 1:
        return ["想入门，能看懂基础概念", "计划学4周，每天1小时", "目前没有特别限制"]
    if has_time:
        return ["计划学4周，每天1小时", "两个月，每周4天，每次1.5小时", "时间比较紧，每天30分钟"]
    if has_depth:
        return ["想入门，能看懂基础概念", "想系统掌握，能独立做项目", "准备面试，需要深入理解"]
    if has_content:
        return ["重点想学核心原理和基础概念", "更关注实战项目和案例", "希望覆盖从入门到进阶的主要模块"]
    if has_intensity:
        return ["强度适中，保证持续学习", "希望进度快一些", "希望节奏慢一点"]
    return ["想入门，能看懂基础概念", "计划学4周，每天1小时", "目前没有特别限制"]


def _pick_init_first_question(user_message: str) -> str:
    text = (user_message or "").strip()
    if not text:
        return _next_default_question("init", 0)
    if _has_time_signal(text):
        return _next_default_question("init", 2)
    if _is_learn_intent(text) or _contains_keywords(text, CONTENT_KEYWORDS):
        return DEFAULT_TIME_QUESTION
    return _next_default_question("init", 0)


def _normalize_plan_session(plan_session: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    base = dict(plan_session or {})
    # 兼容旧状态
    if base.get("status") == "offer_shown":
        base["status"] = "await_offer"
    base.setdefault("status", "idle")  # idle | await_offer | await_confirm | collecting | await_plan_confirm | await_exit_confirm
    base.setdefault("mode", "")
    base.setdefault("turns", 0)
    base.setdefault("max_turns", 0)
    base.setdefault("messages", [])
    base.setdefault("pending_mode", "")
    base.setdefault("draft_plan", None)
    base.setdefault("exit_from", "")
    base.setdefault("paused_from", "")
    base.setdefault("context_messages", [])
    return base


class PlanReadinessDecision(BaseModel):
    ready: bool = False


def _is_exit_confirm_yes(text: str) -> bool:
    candidates = _reply_candidates(text)
    return bool(
        candidates
        & {"结束", "退出", "是的", "确认", "确认结束", "确定", "确定结束"}
    )


def _is_exit_confirm_no(text: str) -> bool:
    candidates = _reply_candidates(text)
    return bool(
        candidates
        & {"继续", "不结束", "不退出", "继续调整", "继续计划", "先继续", "取消退出"}
    )


def _should_exit_plan_by_keywords(user_message: str) -> bool:
    return _is_exit_intent(user_message)


async def _generate_followup_question(
    mode: str,
    turns: int,
    plan_session: Dict[str, Any],
    has_plan: bool,
    existing_plan: Optional[Dict[str, Any]] = None,
    require_time: bool = False,
) -> str:
    if require_time:
        return DEFAULT_TIME_QUESTION
    try:
        from app.core.task_plan.generator import _get_chat_model

        model = _get_chat_model()
        base_plan = existing_plan or {}
        if isinstance(plan_session.get("draft_plan"), dict):
            base_plan = plan_session.get("draft_plan") or base_plan

        summary = json.dumps(base_plan, ensure_ascii=False, sort_keys=True) if base_plan else ""
        dialogue = _build_plan_dialogue_text(plan_session)
        sys_prompt = (
            "你是学习计划助手，需要用最简洁的一个问题继续收集计划信息。"
            "只请一个问题，不要列表，不要多个问号，中文回答。"
            "收集要点：学习目标/范围、时间周期、日常投入、重点主题或约束。"
            "如果当前模式是 init，请先用 1-2 句简单的入门解释帮助用户对主题有初步了解，然后提一个问题。"
            "如果当前模式是 update，直接提问。"
            f"\n当前模式：{mode}."
            f"\n是否已有计划：{str(has_plan)}."
        )
        user_prompt = f"当前对话:\n{dialogue}\n\n原计划:\n{summary}"
        _t0 = time.perf_counter()
        response = await model.ainvoke(
            [
                SystemMessage(content=sys_prompt),
                HumanMessage(content=user_prompt),
            ]
        )
        logger.info(
            "[计时] _generate_followup_question 生成追问 LLM 耗时 %.2fs (mode=%s)",
            time.perf_counter() - _t0,
            mode,
        )
        content = getattr(response, "content", "") or ""
        content = content.strip()
        if content:
            return content
    except Exception:
        pass
    return _next_default_question(mode, turns)


async def handle_plan_chat(
    task_id: str,
    user_message: str,
    existing_plan: Optional[Dict[str, Any]],
    plan_session: Optional[Dict[str, Any]],
    has_plan: bool,
    conversation_summary: str = "",
    history_messages: Optional[List[Any]] = None,
    seed_user_message: Optional[str] = None,
) -> Dict[str, Any]:
    _t0 = time.perf_counter()
    session = _normalize_plan_session(plan_session)
    status = session.get("status", "idle")
    mode = session.get("mode", "")
    logger.info(
        "[计时] handle_plan_chat 进入，status=%s mode=%s，用户消息前30字=%.30s",
        status, mode, (user_message or ""),
    )

    # Awaiting exit confirmation
    if status == "await_exit_confirm":
        if _is_exit_confirm_no(user_message):
            session["status"] = session.get("exit_from") or "collecting"
            session["exit_from"] = ""
            return {
                "handled": True,
                "reply": "好的，我们继续调整学习计划。请告诉我你想修改哪些内容。",
                "plan_proposal": None,
                "plan_session": session,
            }
        if _is_exit_confirm_yes(user_message):
            session.update({"status": "idle", "mode": "", "turns": 0, "pending_mode": "", "messages": [], "exit_from": ""})
            return {
                "handled": True,
                "reply": "好的，已结束学习计划规划。需要时随时告诉我。",
                "plan_proposal": None,
                "plan_session": session,
            }
        return {
            "handled": True,
            "reply": "是否结束学习计划规划？回复“结束”或“继续”。",
            "plan_proposal": None,
            "plan_session": session,
        }

    # A paused plan remains resumable from natural language as well as the UI.
    if status == "paused":
        if _is_resume_plan_intent(user_message):
            restored_status = session.get("paused_from") or "collecting"
            session["status"] = restored_status
            session["paused_from"] = ""
            return {
                "handled": True,
                "reply": "好的，已恢复学习计划规划。请继续补充或调整计划信息。",
                "plan_proposal": None,
                "plan_session": session,
            }
        if _is_exit_intent(user_message):
            session.update(
                {
                    "status": "idle",
                    "mode": "",
                    "turns": 0,
                    "pending_mode": "",
                    "messages": [],
                    "paused_from": "",
                }
            )
            return {
                "handled": True,
                "reply": "好的，已结束学习计划规划。需要时随时告诉我。",
                "plan_proposal": None,
                "plan_session": session,
            }
        return {
            "handled": False,
            "plan_proposal": None,
            "plan_session": session,
        }

    # Awaiting user response to a soft plan offer
    if status == "await_offer":
        if _is_yes(user_message):
            mode = "update" if has_plan else "init"
            session["context_messages"] = _extract_recent_dialogue(history_messages, 12)
            session.update(
                {
                    "status": "collecting",
                    "mode": mode,
                    "turns": 0,
                    "max_turns": 5 if mode == "init" else 3,
                    "pending_mode": "",
                    "messages": [],
                }
            )
            seed_text = (seed_user_message or "").strip()
            if not seed_text and history_messages:
                last_user = None
                prior_user = None
                for msg in reversed(history_messages):
                    if isinstance(msg, HumanMessage):
                        content = (msg.content or "").strip()
                        if not content:
                            continue
                        if last_user is None:
                            last_user = content
                        else:
                            prior_user = content
                            break
                seed_text = (prior_user or "").strip()
            if seed_text:
                session["messages"].append({"role": "user", "content": seed_text})
            current_text = (user_message or "").strip()
            if current_text:
                if not session["messages"] or session["messages"][-1].get("content") != current_text:
                    session["messages"].append({"role": "user", "content": current_text})
            question = await _generate_followup_question(mode, 0, session, has_plan, existing_plan)
            session["messages"].append({"role": "assistant", "content": question})
            return {
                "handled": True,
                "reply": question,
                "plan_proposal": None,
                "plan_session": session,
                "suggested_replies": _build_suggested_replies(question, mode),
            }
        # 软引导阶段交给 Analyzer 判断是否进入计划流程
        session.update({"status": "idle", "mode": "", "turns": 0, "pending_mode": "", "messages": []})
        return {
            "handled": False,
            "plan_proposal": None,
            "plan_session": session,
        }

    # Awaiting plan confirmation prompt
    if status == "await_confirm":
        if _is_exit_intent(user_message) or _should_exit_plan_by_keywords(user_message):
            session["exit_from"] = status
            session["status"] = "await_exit_confirm"
            return {
                "handled": True,
                "reply": "是否结束学习计划规划？回复“结束”或“继续”。",
                "plan_proposal": None,
                "plan_session": session,
            }
        pending_mode = session.get("pending_mode") or ("update" if has_plan else "init")
        if _is_yes(user_message):
            mode = pending_mode
            session.update(
                {
                    "status": "collecting",
                    "mode": mode,
                    "turns": 0,
                    "max_turns": 5 if mode == "init" else 3,
                    "pending_mode": "",
                    "messages": [],
                }
            )
            question = await _generate_followup_question(mode, 0, session, has_plan, existing_plan)
            session["messages"].append({"role": "assistant", "content": question})
            return {
                "handled": True,
                "reply": question,
                "plan_proposal": None,
                "plan_session": session,
                "suggested_replies": _build_suggested_replies(question, mode),
            }
        if _is_no(user_message):
            session.update({"status": "idle", "mode": "", "turns": 0, "pending_mode": "", "messages": []})
            return {
                "handled": True,
                "reply": "好的，如果需要学习计划，随时告诉我。",
                "plan_proposal": None,
                "plan_session": session,
            }
        return {
            "handled": True,
            "reply": "你是否需要我为你生成/调整学习计划？回复'需要'或'不需要'即可。",
            "plan_proposal": None,
            "plan_session": session,
        }

    # Awaiting user confirmation after plan proposal
    if status == "await_plan_confirm":
        if _is_exit_intent(user_message) or _should_exit_plan_by_keywords(user_message):
            session["exit_from"] = status
            session["status"] = "await_exit_confirm"
            return {
                "handled": True,
                "reply": "是否结束学习计划规划？回复“结束”或“继续”。",
                "plan_proposal": None,
                "plan_session": session,
            }
        if _is_plan_confirm_intent(user_message) and not _has_update_points(user_message):
            confirmed_plan = session.get("draft_plan")
            if not isinstance(confirmed_plan, dict):
                return {
                    "handled": True,
                    "reply": "当前没有可确认的计划草案，请先生成或调整计划。",
                    "plan_proposal": None,
                    "plan_session": session,
                }
            session.update(
                {
                    "status": "idle",
                    "mode": "",
                    "turns": 0,
                    "pending_mode": "",
                    "messages": [],
                    "draft_plan": None,
                }
            )
            return {
                "handled": True,
                "reply": "学习计划已确认并保存，可以按计划开始执行了。",
                "plan_proposal": None,
                "plan_session": session,
                "confirmed_plan": confirmed_plan,
            }
        # If user 提出新诉求，回到更新流程
        if _is_update_intent(user_message) or _is_learn_intent(user_message) or _has_update_points(user_message):
            session.update(
                {
                    "status": "collecting",
                    "mode": "update",
                    "turns": 0,
                    "max_turns": 3,
                    "messages": [],
                }
            )
            session["messages"].append({"role": "user", "content": user_message})
            question = await _generate_followup_question("update", 0, session, True, existing_plan)
            session["messages"].append({"role": "assistant", "content": question})
            return {
                "handled": True,
                "reply": question,
                "plan_proposal": None,
                "plan_session": session,
                "suggested_replies": _build_suggested_replies(question, "update"),
            }
        return {
            "handled": True,
            "reply": "你可以回复“确认”保存计划，或直接告诉我想调整哪些内容。",
            "plan_proposal": None,
            "plan_session": session,
        }

    # Active collection flow
    if status == "collecting":
        # 检测用户是否想退出（需要二次确认）
        if _is_exit_intent(user_message) or _should_exit_plan_by_keywords(user_message):
            session["exit_from"] = status
            session["status"] = "await_exit_confirm"
            return {
                "handled": True,
                "reply": "是否结束学习计划规划？回复“结束”或“继续”。",
                "plan_proposal": None,
                "plan_session": session,
            }

        session["messages"].append({"role": "user", "content": user_message})
        session["turns"] = int(session.get("turns", 0)) + 1
        mode = session.get("mode") or "init"
        session["mode"] = mode
        if session.get("max_turns", 0) <= 0:
            session["max_turns"] = 5 if mode == "init" else 3

        async def _should_generate_plan_llm(text: str) -> bool:
            try:
                from app.core.task_plan.generator import _get_chat_model
                model = _get_chat_model()
                readiness_model = model.with_structured_output(PlanReadinessDecision)
                sys_prompt = (
                    "你是学习计划信息判断器。"
                    "判断当前对话是否已经足够生成完整学习计划。"
                    "关注目标/范围、时间周期、日常投入、重点主题或约束。"
                    "只有目标与时间投入足以形成可执行计划时，ready 才为 true。"
                )
                user_prompt = f"用户已经明确提供的信息（不要把缺失项当作已提供）:\n{text}"
                _t0 = time.perf_counter()
                decision = await readiness_model.ainvoke(
                    [SystemMessage(content=sys_prompt), HumanMessage(content=user_prompt)]
                )
                logger.info(
                    "[计时] _should_generate_plan_llm 信息判断 LLM 耗时 %.2fs",
                    time.perf_counter() - _t0,
                )
                if isinstance(decision, dict):
                    return bool(decision.get("ready", False))
                return bool(getattr(decision, "ready", False))
            except Exception:
                return False

        # 先用纯规则快速判断信息是否已足够，避免每轮都调用一次 LLM 判断。
        # 规则认为够了就直接生成；规则不确定时才回退到 LLM 判断。
        user_plan_text = _build_plan_user_text(session)
        rule_says_enough = _has_enough_info(user_plan_text, mode)
        if rule_says_enough:
            should_generate = True
        else:
            should_generate = await _should_generate_plan_llm(user_plan_text)
        should_generate = should_generate or session["turns"] >= session["max_turns"]

        if should_generate:
            base_plan = existing_plan or {}
            if isinstance(session.get("draft_plan"), dict):
                base_plan = session.get("draft_plan") or base_plan

            plan_query = ""
            messages_for_plan = list(history_messages or [])
            if user_message:
                messages_for_plan.append(HumanMessage(content=user_message))
            plan_state = {
                "messages": messages_for_plan,
                "conversation_summary": conversation_summary or "",
                "task_id": task_id,
                "session_id": "",
            }
            from app.core.task_plan.generator import generate_task_plan_from_state, _get_chat_model

            _t0 = time.perf_counter()
            plan = await asyncio.to_thread(
                generate_task_plan_from_state,
                plan_state,
                plan_query,
                base_plan,
                _get_chat_model(),
            )
            logger.info(
                "[计时] generate_task_plan_from_state 生成计划耗时 %.2fs",
                time.perf_counter() - _t0,
            )
            # 生成计划后自动退出计划模块
            session.update(
                {
                    "status": "await_plan_confirm",
                    "mode": "",
                    "turns": 0,
                    "messages": [],
                    "pending_mode": "",
                    "draft_plan": plan,
                }
            )
            reply = "学习计划已生成！如果需要调整，请告诉我你想改哪些内容。"
            return {
                "handled": True,
                "reply": reply,
                "plan_proposal": plan,
                "plan_session": session,
            }

        time_missing = mode == "init" and not _has_time_signal(user_plan_text)
        require_time = time_missing and session["turns"] >= (session["max_turns"] - 1)
        question = await _generate_followup_question(
            mode,
            session["turns"],
            session,
            has_plan,
            existing_plan,
            require_time=require_time,
        )
        session["messages"].append({"role": "assistant", "content": question})
        return {
            "handled": True,
            "reply": question,
            "plan_proposal": None,
            "plan_session": session,
            "suggested_replies": _build_suggested_replies(question, mode),
        }

    # Idle: detect intent
    # 由 Analyzer 决定进入 plan 节点后，直接按是否已有计划选择 init/update
    mode = "update" if has_plan else "init"
    session["context_messages"] = _extract_recent_dialogue(history_messages, 12)
    session.update(
        {
            "status": "collecting",
            "mode": mode,
            "turns": 0,
            "max_turns": 5 if mode == "init" else 3,
            "messages": [],
        }
    )
    if seed_user_message and seed_user_message.strip() and seed_user_message.strip() != (user_message or "").strip():
        session["messages"].append({"role": "user", "content": seed_user_message.strip()})
    if mode == "init":
        question = _pick_init_first_question(user_message)
    else:
        question = await _generate_followup_question(mode, 0, session, has_plan, existing_plan)
    session["messages"].append({"role": "assistant", "content": question})
    return {
        "handled": True,
        "reply": question,
        "plan_proposal": None,
        "plan_session": session,
        "suggested_replies": _build_suggested_replies(question, mode),
    }

    return {"handled": False}
