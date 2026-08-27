"""简历持久化与上传文件管理。

提供简历原始文件落盘、结构化 Resume JSON 的读写与删除。
存储目录遵循设计文档 §3.3，与题库（``data/``）和对话记忆
（``memory/vector_store/``）物理隔离。

文件采用原子写（复用 ``app/utils/file_io``），删除时同时清理
原始文件、JSON 与（后续的）索引/分析产物。
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import List, Optional

from app.resume.models import Resume
from app.utils import file_io

# 存储根目录（相对项目根）
RESUME_DIR = "memory/resumes"
UPLOAD_DIR = "memory/uploads"


def _ensure_dirs() -> None:
    os.makedirs(RESUME_DIR, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def make_resume_id() -> str:
    """生成简历 ID（含时间戳，唯一）。"""
    return f"resume_{time.strftime('%Y%m%d_%H%M%S')}"


def _resume_path(resume_id: str) -> str:
    return os.path.join(RESUME_DIR, f"{resume_id}.json")


def save_upload(content: bytes, filename: str, resume_id: str) -> str:
    """保存上传的原始文件，返回相对路径。"""
    _ensure_dirs()
    suffix = Path(filename).suffix.lower() or ".bin"
    rel_path = os.path.join(UPLOAD_DIR, f"{resume_id}{suffix}")
    abs_path = os.path.abspath(rel_path)
    file_io.ensure_directory(abs_path)
    with open(abs_path, "wb") as f:
        f.write(content)
    return rel_path


def save_resume(resume: Resume) -> str:
    """保存结构化简历（原子写），返回 JSON 绝对路径。"""
    _ensure_dirs()
    resume.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    if not resume.created_at:
        resume.created_at = resume.updated_at
    return file_io.save_json(
        resume.model_dump(), _resume_path(resume.resume_id)
    )


def load_resume(resume_id: str) -> Optional[Resume]:
    """按 ID 加载结构化简历；不存在返回 None。"""
    path = _resume_path(resume_id)
    if not os.path.exists(path):
        return None
    data = file_io.load_json(path)
    return Resume.model_validate(data)


def list_resumes(user_id: str = "local_user") -> List[Resume]:
    """列出某用户的所有简历（按更新时间倒序）。"""
    _ensure_dirs()
    resumes: List[Resume] = []
    for f in sorted(os.listdir(RESUME_DIR)):
        if not f.endswith(".json"):
            continue
        try:
            r = Resume.model_validate(file_io.load_json(os.path.join(RESUME_DIR, f)))
        except Exception:  # noqa: BLE001 - 跳过损坏文件
            continue
        if r.user_id == user_id:
            resumes.append(r)
    resumes.sort(key=lambda r: r.updated_at, reverse=True)
    return resumes


def delete_resume(resume_id: str) -> bool:
    """删除简历：JSON + 原始上传文件（若存在）。返回是否删除成功。"""
    deleted = False
    json_path = _resume_path(resume_id)
    if os.path.exists(json_path):
        os.remove(json_path)
        deleted = True
    # 清理该 resume_id 对应的原始上传文件（任意后缀）
    for f in os.listdir(UPLOAD_DIR) if os.path.isdir(UPLOAD_DIR) else []:
        if f.startswith(resume_id):
            try:
                os.remove(os.path.join(UPLOAD_DIR, f))
            except OSError:
                pass
    # 清理该 resume 的分析产物目录（若后续实现）
    analysis_dir = os.path.join("memory", "resume_analysis", resume_id)
    if os.path.isdir(analysis_dir):
        shutil.rmtree(analysis_dir, ignore_errors=True)
    return deleted
