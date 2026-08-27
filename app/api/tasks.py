from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core import memory

router = APIRouter()


class TaskItem(BaseModel):
    id: str
    title: str
    icon: str
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    kind: Literal["interview_goal", "legacy_learning"] = "legacy_learning"
    target_role: Optional[str] = None
    target_companies: List[str] = Field(default_factory=list)
    interview_date: Optional[str] = None
    experience_level: Optional[Literal["beginner", "intermediate", "advanced"]] = None
    resume_id: Optional[str] = None


class TaskListResponse(BaseModel):
    tasks: List[TaskItem]


class TaskUpsertRequest(BaseModel):
    task_id: str
    title: Optional[str] = None
    icon: Optional[str] = None
    status: Optional[str] = "active"
    kind: Literal["interview_goal", "legacy_learning"] = "legacy_learning"
    target_role: Optional[str] = None
    target_companies: List[str] = Field(default_factory=list)
    interview_date: Optional[str] = None
    experience_level: Optional[Literal["beginner", "intermediate", "advanced"]] = None
    resume_id: Optional[str] = None


class TaskStatusRequest(BaseModel):
    status: str


class TaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    icon: Optional[str] = None
    target_role: Optional[str] = None
    target_companies: Optional[List[str]] = None
    interview_date: Optional[str] = None
    experience_level: Optional[Literal["beginner", "intermediate", "advanced"]] = None
    resume_id: Optional[str] = None


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(status: Optional[str] = None, kind: Optional[str] = None):
    tasks = memory.list_tasks(status=status, kind=kind)
    return TaskListResponse(tasks=tasks)


@router.get("/tasks/{task_id}", response_model=TaskItem)
async def get_task(task_id: str):
    task = memory.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskItem(**task)


@router.post("/tasks", response_model=TaskItem)
async def upsert_task(request: TaskUpsertRequest):
    if not request.task_id:
        raise HTTPException(status_code=400, detail="task_id is required")
    role = (request.target_role or "").strip()
    companies = [item.strip() for item in request.target_companies if item.strip()]
    if request.kind == "interview_goal" and not role:
        raise HTTPException(status_code=400, detail="target_role is required for interview goals")
    title = (request.title or "").strip()
    if request.kind == "interview_goal":
        title = f"{companies[0]} · {role}" if companies else role
    elif not title:
        raise HTTPException(status_code=400, detail="title is required")
    status = request.status or "active"
    task = memory.upsert_task(
        task_id=request.task_id,
        title=title,
        icon=request.icon or ("🎯" if request.kind == "interview_goal" else "✨"),
        status=status,
        kind=request.kind,
        target_role=role or None,
        target_companies=companies,
        interview_date=request.interview_date,
        experience_level=request.experience_level,
        resume_id=request.resume_id,
    )
    return TaskItem(**task)


@router.patch("/tasks/{task_id}", response_model=TaskItem)
async def update_task(task_id: str, request: TaskUpdateRequest):
    """更新任务的名称和/或图标"""
    existing = memory.get_task(task_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Task not found")
    updates = request.model_dump(exclude_unset=True)
    if "target_role" in updates:
        updates["target_role"] = (updates["target_role"] or "").strip() or None
    if "target_companies" in updates:
        updates["target_companies"] = [
            item.strip() for item in (updates["target_companies"] or []) if item.strip()
        ]
    if existing.get("kind") == "interview_goal":
        role = updates.get("target_role", existing.get("target_role"))
        companies = updates.get("target_companies", existing.get("target_companies") or [])
        if not role:
            raise HTTPException(status_code=400, detail="target_role is required for interview goals")
        updates["title"] = f"{companies[0]} · {role}" if companies else role
    if not updates:
        raise HTTPException(status_code=400, detail="At least one field must be provided")

    task = memory.update_task_fields(task_id, updates)
    return TaskItem(**task)


@router.patch("/tasks/{task_id}/status", response_model=TaskItem)
async def update_task_status(task_id: str, request: TaskStatusRequest):
    """更新任务的状态（归档/恢复）"""
    task = memory.update_task_status(task_id, request.status)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskItem(**task)


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    deleted = memory.delete_task(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"deleted": True}
