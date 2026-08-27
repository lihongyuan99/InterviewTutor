"""简历持久化（store）的单元测试。

用 monkeypatch 把存储目录切到临时目录，验证落盘/读取/列表/删除闭环，
避免污染真实的 memory/ 数据。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.resume import store  # noqa: E402
from app.resume.models import Resume  # noqa: E402


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RESUME_DIR", str(tmp_path / "resumes"))
    monkeypatch.setattr(store, "UPLOAD_DIR", str(tmp_path / "uploads"))
    return tmp_path


def _make_resume(resume_id: str) -> Resume:
    return Resume(
        resume_id=resume_id,
        user_id="local_user",
        name="张三",
        source_type="md",
        projects=[{"name": "RAG 系统", "tech_stack": ["RAG"]}],
    )


def test_save_and_load_roundtrip(isolated_store):
    resume = _make_resume("resume_test_1")
    store.save_resume(resume)
    loaded = store.load_resume("resume_test_1")
    assert loaded is not None
    assert loaded.name == "张三"
    assert loaded.projects[0].name == "RAG 系统"


def test_load_missing_returns_none(isolated_store):
    assert store.load_resume("resume_nope") is None


def test_list_resumes_filters_user(isolated_store):
    store.save_resume(_make_resume("resume_a"))
    other = _make_resume("resume_b")
    other.user_id = "another_user"
    store.save_resume(other)

    mine = store.list_resumes("local_user")
    assert len(mine) == 1
    assert mine[0].resume_id == "resume_a"


def test_save_upload_writes_file(isolated_store):
    rel = store.save_upload(b"hello", "r.md", "resume_x")
    assert Path(rel).exists()
    assert Path(rel).read_bytes() == b"hello"


def test_delete_resume_cleans_json_and_upload(isolated_store):
    resume = _make_resume("resume_del")
    store.save_resume(resume)
    store.save_upload(b"x", "r.md", "resume_del")

    assert store.delete_resume("resume_del") is True
    assert store.load_resume("resume_del") is None


def test_delete_missing_returns_false(isolated_store):
    assert store.delete_resume("resume_ghost") is False
