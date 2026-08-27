"""简历 API 路由。

提供简历上传解析、查询、删除、深挖、匹配与优化建议（设计文档 §5）：

- POST   /resume/upload          上传并解析简历
- GET    /resume/list            简历列表
- GET    /resume/{resume_id}     读取结构化简历
- DELETE /resume/{resume_id}     删除简历（含文件与产物）
- POST   /resume/deep-dive       项目深挖（联动 project-deep-dive）
- POST   /resume/match           匹配度分析（联动 company-preferences）
- POST   /resume/suggest         优化建议
- POST   /resume/grill/start     深挖题「拷打」：开启会话
- POST   /resume/grill/answer    提交作答，现场评分 + 追问
- POST   /resume/grill/review    教练复盘
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.resume import analyzer, extract, grill, linker, matcher, store, suggester
from app.resume.extract import ExtractionError
from app.resume.parser import ResumeParseError, parse_resume

router = APIRouter()
logger = logging.getLogger(__name__)


class DeepDiveRequest(BaseModel):
    resume_id: str
    project_names: Optional[List[str]] = None
    limit: int = 3


class MatchRequest(BaseModel):
    resume_id: str
    target_role: str = ""
    target_company: str = ""


class SuggestRequest(BaseModel):
    resume_id: str
    target_role: str = ""


class GrillStartRequest(BaseModel):
    resume_id: str
    question: str
    source_name: str = ""
    source_type: str = "project"  # project / work
    goal_id: Optional[str] = None


class GrillAnswerRequest(BaseModel):
    session_id: str
    answer: str


class GrillReviewRequest(BaseModel):
    session_id: str


class UploadResponse(BaseModel):
    resume_id: str
    source_type: str
    source_file: str
    resume: dict


@router.post("/upload")
async def upload_resume(
    file: UploadFile,
    target_role: str = Form(""),
    target_companies: str = Form(""),
):
    """上传简历文件并解析为结构化 Resume。

    - 文件类型白名单：pdf / docx / md / txt
    - 大小上限 10MB
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(content) > extract.MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail="文件超过 10MB 上限")

    # 类型识别（白名单校验）
    try:
        source_type = extract.detect_source_type(file.filename)
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 抽取纯文本
    try:
        raw_text = extract.extract_text_from_bytes(content, source_type)
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # 结构化解析
    resume_id = store.make_resume_id()
    try:
        resume = await parse_resume(
            raw_text,
            resume_id=resume_id,
            source_file=file.filename,
            source_type=source_type,
        )
    except ResumeParseError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # 回填目标岗位/公司
    if target_role.strip():
        resume.target_role = target_role.strip()
    if target_companies.strip():
        resume.target_companies = [
            c.strip() for c in target_companies.replace("，", ",").split(",") if c.strip()
        ]

    # 落盘原始文件 + 结构化 JSON
    try:
        source_path = store.save_upload(content, file.filename, resume_id)
        resume.source_file = source_path
        store.save_resume(resume)
    except Exception as exc:  # noqa: BLE001
        logger.exception("简历落盘失败：%s", exc)
        raise HTTPException(status_code=500, detail=f"简历保存失败：{exc}") from exc

    return UploadResponse(
        resume_id=resume_id,
        source_type=source_type,
        source_file=source_path,
        resume=resume.model_dump(),
    )


@router.get("/list")
async def list_resumes_endpoint(user_id: str = "local_user"):
    return [r.model_dump() for r in store.list_resumes(user_id)]


@router.get("/{resume_id}")
async def get_resume(resume_id: str):
    resume = store.load_resume(resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="简历不存在")
    return resume.model_dump()


@router.delete("/{resume_id}")
async def delete_resume(resume_id: str):
    if not store.delete_resume(resume_id):
        raise HTTPException(status_code=404, detail="简历不存在")
    return {"status": "deleted", "resume_id": resume_id}


@router.post("/deep-dive")
async def deep_dive(request: DeepDiveRequest):
    resume = store.load_resume(request.resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="简历不存在")
    project_links = await linker.deep_dive_projects(
        resume, project_names=request.project_names, limit=request.limit
    )
    work_links = await linker.deep_dive_works(resume, limit=request.limit)
    return {
        "resume_id": request.resume_id,
        "project_questions": [l.model_dump() for l in project_links],
        "work_questions": [l.model_dump() for l in work_links],
    }


@router.post("/match")
async def match(request: MatchRequest):
    resume = store.load_resume(request.resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="简历不存在")
    result = await matcher.match_resume(
        resume, target_role=request.target_role, target_company=request.target_company
    )
    if result is None:
        raise HTTPException(
            status_code=422,
            detail=f"未找到目标公司「{request.target_company}」的面试偏好数据",
        )
    return result.model_dump()


@router.post("/suggest")
async def suggest(request: SuggestRequest):
    resume = store.load_resume(request.resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="简历不存在")
    suggestions = await suggester.suggest(resume, target_role=request.target_role)
    return {"resume_id": request.resume_id, "suggestions": [s.model_dump() for s in suggestions]}


def _build_grill_context(resume, source_name: str, source_type: str) -> str:
    """根据深挖题来源，构造该经历的上下文（供评分与复盘参考）。"""
    if source_type == "work":
        for w in resume.works:
            if w.company == source_name:
                parts = [f"实习/工作经历：{w.company} {w.role}".strip()]
                if w.start or w.end:
                    parts.append(f"时间：{w.start} - {w.end}")
                if w.description:
                    parts.append(f"工作内容：{w.description}")
                if w.tech_stack:
                    parts.append(f"技术栈：{'、'.join(w.tech_stack)}")
                if w.metrics:
                    parts.append(f"量化成果：{'、'.join(w.metrics)}")
                if w.highlights:
                    parts.append(f"亮点：{'、'.join(w.highlights)}")
                return "\n".join(parts)
    else:
        for p in resume.projects:
            if p.name == source_name:
                parts = [f"项目：{p.name}".strip()]
                if p.period:
                    parts.append(f"时间：{p.period}")
                if p.description:
                    parts.append(f"描述：{p.description}")
                if p.tech_stack:
                    parts.append(f"技术栈：{'、'.join(p.tech_stack)}")
                if p.metrics:
                    parts.append(f"量化成果：{'、'.join(p.metrics)}")
                if p.highlights:
                    parts.append(f"亮点：{'、'.join(p.highlights)}")
                return "\n".join(parts)
    # 找不到对应经历时，退回最简上下文
    return f"{source_name}（来源：{'实习/工作' if source_type == 'work' else '项目'}）"


@router.post("/grill/start")
async def grill_start(request: GrillStartRequest):
    resume = store.load_resume(request.resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="简历不存在")
    context = _build_grill_context(resume, request.source_name, request.source_type)
    return grill.start_grill(
        question=request.question,
        source_name=request.source_name,
        source_type=request.source_type,
        context=context,
        resume_id=request.resume_id,
        goal_id=request.goal_id,
    )


@router.post("/grill/answer")
async def grill_answer(request: GrillAnswerRequest):
    return await grill.answer_grill(request.session_id, request.answer)


@router.post("/grill/review")
async def grill_review(request: GrillReviewRequest):
    return await grill.review_grill(request.session_id)
