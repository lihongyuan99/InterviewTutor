"""学习模式（真正的 RAG 问答）。

数据流：用户自由提问 → 知识库双通道召回相关题目 → 拼接专家答案作为上下文
→ Tutor 基于召回内容生成讲解，并标注引用来源。

这是区别于「刷题模式」的 RAG 流程：无标准答案、依赖语义召回、带引用。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm_factory import create_chat_model, message_text
from app.knowledge import get_question, search
from app.knowledge.schema import SearchResult

logger = logging.getLogger(__name__)

# 召回时过滤低相关结果的最低分数。
# 依据 50 条黄金查询评测：正样本命中最低分约 0.65，负样本最高分约 0.44，
# 取 0.5 作为安全分界，既能召回全部正样本，又能拦截负样本误召回。
_SIMILARITY_THRESHOLD = 0.5
# 召回的 Top-K
_TOP_K = 4


LEARN_SYSTEM_PROMPT = """你是面试知识库的学习导师（Tutor）。

系统已经为你从面试知识库中检索到若干相关的「面试题 + 专家回答」作为参考材料。

你的任务：
1. 基于参考材料，用清晰、结构化、有工程视角的方式解答用户的问题。
2. 回答必须**基于参考材料**，不要凭空编造知识库之外的内容。
3. 在回答中引用参考材料，用 [1]、[2] 这样的编号标注你引用了哪份材料。
4. 如果参考材料不足以回答用户问题，请如实说明，并给出建议方向。

输出格式要求（务必遵守）：
- 使用标准 Markdown，表格、列表、标题之间用空行分隔。
- 表格必须按 GFM 规范换行：表头、分隔行、每个数据行各自独占一行，严禁把整张表压缩成一行或用空格替代换行。
- 列表项（有序/无序）每个占一行，列表前后各留一个空行。
- 标题（## / ###）与正文之间留空行。

参考材料：
{context}
"""

LEARN_USER_PROMPT = """用户问题：
{question}
"""


def _retrieve(query: str, dimension: Optional[str] = None) -> List[SearchResult]:
    """同步执行知识库检索（可放入线程池，避免阻塞事件循环）。

    内部包含：关键词通道 + Embedding 向量通道（含 Embedding 网络调用）。
    """
    return search(
        query,
        dimension=dimension,
        limit=_TOP_K,
        threshold=_SIMILARITY_THRESHOLD,
    )


def _build_context(results: List[SearchResult]) -> str:
    """将检索结果拼接为带编号的参考材料上下文。"""
    blocks = []
    for i, r in enumerate(results, 1):
        full = get_question(r.question_id)
        if not full:
            continue
        parts = [f"### [{i}] 面试题：{full.question}"]
        if full.expert_answer:
            parts.append(f"专家回答：{full.expert_answer}")
        if full.gap_analysis:
            parts.append(f"差距分析：{full.gap_analysis}")
        parts.append(f"维度：{full.dimension_label}｜来源：{full.source_file}")
        blocks.append("\n".join(parts))
    return "\n\n".join(blocks)


async def ask(query: str, dimension: Optional[str] = None) -> dict:
    """学习模式问答：检索 + 生成带引用回答。

    返回 {answer, citations, question_ids, timings}。
    """
    t0 = time.perf_counter()

    # 检索阶段（阻塞的 Embedding 网络请求 + 全量余弦计算，放到线程池避免阻塞事件循环）
    results = await asyncio.to_thread(_retrieve, query, dimension)
    t_retrieve = time.perf_counter() - t0

    if not results:
        logger.info("learn.ask: 检索耗时 %.3fs，未命中", t_retrieve)
        return {
            "answer": "抱歉，我在知识库中没有找到与你的问题足够相关的内容。"
            "你可以换个问法，或者到「刷题」里针对具体维度练习。",
            "citations": [],
            "question_ids": [],
            "timings": {"retrieve": round(t_retrieve, 3)},
        }

    context = _build_context(results)
    system_prompt = LEARN_SYSTEM_PROMPT.format(context=context)
    user_prompt = LEARN_USER_PROMPT.format(question=query)

    model = create_chat_model(temperature=0.3)
    t1 = time.perf_counter()
    response = await model.ainvoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    t_generate = time.perf_counter() - t1
    answer = message_text(response)

    # 组装引用信息（前端可跳转/展开）
    citations = []
    question_ids = []
    for r in results:
        full = get_question(r.question_id)
        if not full:
            continue
        citations.append(
            {
                "question_id": r.question_id,
                "question": full.question,
                "dimension": full.dimension,
                "dimension_label": full.dimension_label,
                "source_file": full.source_file,
                "score": round(r.score, 4),
            }
        )
        question_ids.append(r.question_id)

    total = time.perf_counter() - t0
    logger.info(
        "learn.ask: 检索 %.3fs / 生成 %.3fs / 总 %.3fs",
        t_retrieve,
        t_generate,
        total,
    )

    return {
        "answer": answer,
        "citations": citations,
        "question_ids": question_ids,
        "timings": {
            "retrieve": round(t_retrieve, 3),
            "generate": round(t_generate, 3),
            "total": round(total, 3),
        },
    }


async def ask_stream(
    query: str, dimension: Optional[str] = None
) -> AsyncIterator[dict]:
    """学习模式问答的流式版本：先检索，再逐块产出生成内容。

    每个事件为 dict，包含 type 字段：
    - {"type": "stage", "stage": "retrieving" | "generating"}
    - {"type": "token", "content": "..."}
    - {"type": "done", "answer": "...", "citations": [...], "question_ids": [...], "timings": {...}}
    - {"type": "error", "message": "..."}
    """
    t0 = time.perf_counter()
    yield {"type": "stage", "stage": "retrieving"}

    results = await asyncio.to_thread(_retrieve, query, dimension)
    t_retrieve = time.perf_counter() - t0

    if not results:
        logger.info("learn.ask_stream: 检索耗时 %.3fs，未命中", t_retrieve)
        yield {
            "type": "done",
            "answer": "抱歉，我在知识库中没有找到与你的问题足够相关的内容。"
            "你可以换个问法，或者到「刷题」里针对具体维度练习。",
            "citations": [],
            "question_ids": [],
            "timings": {"retrieve": round(t_retrieve, 3)},
        }
        return

    context = _build_context(results)
    system_prompt = LEARN_SYSTEM_PROMPT.format(context=context)
    user_prompt = LEARN_USER_PROMPT.format(question=query)

    model = create_chat_model(temperature=0.3)
    t1 = time.perf_counter()
    yield {"type": "stage", "stage": "generating"}

    # 流式生成：逐块产出 token
    chunks: List[str] = []
    async for chunk in model.astream(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    ):
        text = message_text(chunk)
        if text:
            chunks.append(text)
            yield {"type": "token", "content": text}

    t_generate = time.perf_counter() - t1
    answer = "".join(chunks)

    citations = []
    question_ids = []
    for r in results:
        full = get_question(r.question_id)
        if not full:
            continue
        citations.append(
            {
                "question_id": r.question_id,
                "question": full.question,
                "dimension": full.dimension,
                "dimension_label": full.dimension_label,
                "source_file": full.source_file,
                "score": round(r.score, 4),
            }
        )
        question_ids.append(r.question_id)

    total = time.perf_counter() - t0
    logger.info(
        "learn.ask_stream: 检索 %.3fs / 生成 %.3fs / 总 %.3fs",
        t_retrieve,
        t_generate,
        total,
    )

    yield {
        "type": "done",
        "answer": answer,
        "citations": citations,
        "question_ids": question_ids,
        "timings": {
            "retrieve": round(t_retrieve, 3),
            "generate": round(t_generate, 3),
            "total": round(total, 3),
        },
    }
