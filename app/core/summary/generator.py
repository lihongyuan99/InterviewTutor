"""
总结生成器核心逻辑
"""
from typing import Dict, Any, List, Optional
from langchain_core.messages import SystemMessage, HumanMessage

from app.core.llm_factory import create_chat_model, message_text
from app.core.summary.prompts import (
    SUMMARIZER_REVIEW_PROMPT,
    SUMMARIZER_NOTE_PROMPT,
    DAILY_SUMMARY_PROMPT,
    TASK_SUMMARY_PROMPT,
    TASK_TITLE_PROMPT
)


class SummaryGenerator:
    """总结生成器"""

    def __init__(self):
        """总结模型在调用时创建，以便即时应用用户的新配置。"""

    def _model(self, *, maintenance: bool = False):
        return create_chat_model(role="maintenance" if maintenance else "summary")

    def generate_review_summary(
        self,
        conversation_history: List[Dict[str, str]],
        topic: str = "General"
    ) -> str:
        """
        生成临时回顾总结（用户在对话中要求的即时总结）

        Args:
            conversation_history: 对话历史列表，每项包含 {"role": "user/assistant", "content": "..."}
            topic: 当前话题

        Returns:
            总结文本
        """
        sys_msg = SystemMessage(content=SUMMARIZER_REVIEW_PROMPT)

        # 构造对话历史消息
        messages = [sys_msg]
        messages.append(SystemMessage(content=f"当前话题：{topic}"))

        # 添加对话历史
        for msg in conversation_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(SystemMessage(content=content))

        # 添加总结指令
        messages.append(HumanMessage(content="请总结我们刚才对话的核心要点。"))

        response = self._model().invoke(messages)
        return message_text(response)

    def generate_session_note(
        self,
        conversation_history: List[Dict[str, str]],
        topic: str = "General"
    ) -> str:
        """
        生成离场学习笔记（会话结束时的深度学习简报）

        Args:
            conversation_history: 对话历史列表
            topic: 当前话题

        Returns:
            学习笔记文本（Markdown 格式）
        """
        sys_msg = SystemMessage(content=SUMMARIZER_NOTE_PROMPT)

        messages = [sys_msg]
        messages.append(SystemMessage(content=f"当前话题：{topic}"))

        # 添加对话历史
        for msg in conversation_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(SystemMessage(content=content))

        messages.append(HumanMessage(content="请生成一份高密度的学习简报。"))

        response = self._model().invoke(messages)
        return message_text(response)

    def generate_daily_summary(
        self,
        sessions: List[Dict[str, Any]],
        task_id: str,
        date: str
    ) -> str:
        """
        生成每日学习总结

        Args:
            sessions: 当天所有会话列表，每项包含会话的完整信息
            task_id: 任务 ID
            date: 日期字符串 (YYYY-MM-DD)

        Returns:
            每日总结文本（Markdown 格式）
        """
        # 构造任务标题
        task_titles = {
            "task_1": "掌握随机森林算法",
            "task_2": "雅思口语备考",
            "task_3": "React Hooks 深入",
            "task_4": "机器学习数学基础",
        }
        task_title = task_titles.get(task_id, task_id)

        # 合并所有会话的对话历史
        all_messages = []
        for session in sessions:
            messages = session.get("messages", [])
            all_messages.extend(messages)

        # 构造 prompt
        prompt_text = DAILY_SUMMARY_PROMPT.format(
            date=date,
            task_title=task_title
        )

        sys_msg = SystemMessage(content=prompt_text)
        messages = [sys_msg]

        # 添加对话历史
        for msg in all_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(SystemMessage(content=content))

        messages.append(HumanMessage(content="请生成今日学习报告。"))

        response = self._model().invoke(messages)
        return message_text(response)

    def generate_task_summary(
        self,
        sessions: List[Dict[str, Any]],
        task_id: str
    ) -> str:
        """
        生成任务学习总结（对整个任务的所有对话生成总结）

        Args:
            sessions: 任务所有会话列表，每项包含会话的完整信息
            task_id: 任务 ID

        Returns:
            任务总结文本（Markdown 格式）
        """
        # 构造任务标题
        task_titles = {
            "task_1": "掌握随机森林算法",
            "task_2": "雅思口语备考",
            "task_3": "React Hooks 深入",
            "task_4": "机器学习数学基础",
        }
        task_title = task_titles.get(task_id, task_id)

        # 合并所有会话的对话历史
        all_messages = []
        for session in sessions:
            messages = session.get("messages", [])
            all_messages.extend(messages)

        # 构造 prompt
        prompt_text = TASK_SUMMARY_PROMPT.format(
            task_title=task_title
        )

        sys_msg = SystemMessage(content=prompt_text)
        messages = [sys_msg]

        # 添加对话历史
        for msg in all_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(SystemMessage(content=content))

        messages.append(HumanMessage(content="请生成任务学习总结。"))

        response = self._model().invoke(messages)
        return message_text(response)

    def generate_task_title(self, conversation_history: List[Dict[str, str]]) -> str:
        """根据对话内容自动生成任务标题（2-8 字）。

        只取用户发言作为依据（最能反映学习意图），做长度兜底清理。
        失败时返回空字符串，由调用方决定是否保留原标题。
        """
        # 仅拼接用户消息，避免助手冗长回复稀释主题信号
        user_texts = [
            str(msg.get("content", "")).strip()
            for msg in conversation_history
            if msg.get("role") == "user" and str(msg.get("content", "")).strip()
        ]
        conversation_text = "\n".join(user_texts)
        if not conversation_text:
            return ""

        prompt_text = TASK_TITLE_PROMPT.format(conversation_text=conversation_text[:2000])
        try:
            response = self._model(maintenance=True).invoke(
                [SystemMessage(content="你是简洁的中文标题生成器。"),
                 HumanMessage(content=prompt_text)]
            )
        except Exception:
            return ""

        title = message_text(response).strip()
        # 清理可能被模型带上的引号、标点与换行
        title = title.strip(" \t\r\n\"'“”‘’《》【】#*·-—")
        # 兜底：过短（如纯标点被清空）或过长则放弃
        if not title or len(title) > 16:
            return ""
        return title


# 全局单例
summary_generator = SummaryGenerator()
