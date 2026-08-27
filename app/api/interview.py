"""面试训练 API 路由。

提供刷题训练闭环的接口（Handoff §12）：
- POST /interview/start    开始训练，返回题目（不含答案）
- POST /interview/answer   提交作答，返回结构化评分 + 追问
- POST /interview/review   展示高手答与复盘反馈
- POST /interview/ask      学习模式（RAG 问答，带引用）
- GET  /interview/progress 查看学习进度与复习队列
"""

import json
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.interview.models import AnswerRequest, StartRequest
from app.interview import learn, workflow
from app.interview.report_store import get_report, list_reports
from app.knowledge.snapshot import snapshot_manager

router = APIRouter()

@router.post("/start")
async def start(request: StartRequest):
    return await workflow.start_session(request)


@router.post("/answer")
async def answer(request: AnswerRequest):
    return await workflow.submit_answer(request)


@router.post("/review")
async def review(request: dict):
    session_id = request.get("session_id", "")
    return await workflow.review(session_id)


@router.get("/session/{session_id}")
async def get_session(session_id: str):
    result = workflow.get_session_view(session_id)
    if not result:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    return result


@router.post("/session/end")
async def end_session(request: dict):
    session_id = str(request.get("session_id") or "")
    if not session_id:
        raise HTTPException(status_code=400, detail="缺少 session_id")
    return workflow.end_session(session_id)


@router.post("/ask")
async def ask(request: dict):
    query = request.get("query", "")
    dimension = request.get("dimension")
    return await learn.ask(query, dimension=dimension)


@router.post("/ask/stream")
async def ask_stream(request: dict):
    """学习模式问答流式接口（SSE）。

    事件序列：stage(retrieving) -> stage(generating) -> token* -> done。
    前端据此区分「检索中」与「生成中」两个阶段。
    """
    query = request.get("query", "")
    dimension = request.get("dimension")

    async def event_stream():
        try:
            async for event in learn.ask_stream(query, dimension=dimension):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/source")
async def read_source(
    source_file: str,
    question: str = "",
    snapshot_id: str = "",
):
    """读取学习模式引用来源对应的知识文件完整内容（Markdown）。

    仅允许读取知识库目录内的 .md 文件，防止路径穿越。
    可选传入 ``question``（题目文本），用于定位该题目在文件中的位置，
    返回 ``heading``（匹配到的标题文本）与 ``heading_index``（第几道题，从 0 开始）。
    """
    if not source_file:
        raise HTTPException(status_code=400, detail="缺少 source_file 参数")

    try:
        snapshot = snapshot_manager.resolve(snapshot_id or None)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # 拼接并归一化路径，确保落在该快照的知识目录内。
    root = snapshot.source_dir.resolve()
    target = (root / source_file).resolve()
    if not str(target).startswith(str(root) + os.sep) and target != root:
        raise HTTPException(status_code=403, detail="非法的来源文件路径")

    if not target.is_file() or target.suffix.lower() != ".md":
        raise HTTPException(status_code=404, detail="来源文件不存在")

    try:
        content = target.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取来源文件失败：{str(e)}")

    # 定位目标题目在文件中的位置（用于前端滚动定位）
    import re as _re
    _q_title_re = _re.compile(r"^(#{2,3})\s+Q[：:]\s*(.*)$")
    heading = ""
    heading_index = -1
    if question:
        q = question.strip()
        idx = 0
        for line in content.splitlines():
            m = _q_title_re.match(line.strip())
            if m:
                title_text = m.group(2).strip()
                if title_text and (title_text == q or q.startswith(title_text) or title_text.startswith(q)):
                    heading = line.strip()
                    heading_index = idx
                    break
                idx += 1

    return {
        "source_file": source_file,
        "snapshot_id": snapshot.snapshot_id,
        "content": content,
        "heading": heading,
        "heading_index": heading_index,
    }


@router.get("/progress")
async def progress(
    user_id: str = "local_user",
    limit: int = 20,
    goal_id: str | None = None,
):
    return workflow.get_progress(user_id=user_id, limit=limit, goal_id=goal_id)


@router.get("/reports")
async def reports(user_id: str = "local_user", goal_id: str | None = None):
    return {
        "goal_id": goal_id,
        "reports": [item.model_dump() for item in list_reports(user_id=user_id, goal_id=goal_id)],
    }


@router.get("/reports/{report_id}")
async def report(report_id: str):
    result = get_report(report_id)
    if not result:
        raise HTTPException(status_code=404, detail="面试报告不存在")
    return result.model_dump()
