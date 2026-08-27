"""简历深挖联动（linker）的单元测试。

重点覆盖纯函数：查询构造。深挖的检索/LLM 部分通过 monkeypatch
验证：无经历时返回空、LLM 生成的定制追问被正确组装、来源区分正确。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.resume.linker import _build_query  # noqa: E402
from app.resume.models import Resume, ResumeProject, ResumeWork  # noqa: E402


def test_build_query_prioritizes_tech_stack():
    q = _build_query(["LangGraph", "FAISS"], "企业级知识库问答")
    assert "LangGraph" in q
    assert "FAISS" in q
    assert "企业级知识库问答" in q


def test_build_query_empty():
    assert _build_query([], "") == ""


def test_build_query_falls_back_to_name():
    assert _build_query([], "", "仅有项目名") == "仅有项目名"


def test_deep_dive_projects_no_projects_returns_empty():
    from app.resume import linker
    import asyncio

    resume = Resume(resume_id="r2", projects=[])
    assert asyncio.run(linker.deep_dive_projects(resume)) == []


def test_deep_dive_works_no_works_returns_empty():
    from app.resume import linker
    import asyncio

    resume = Resume(resume_id="r2", works=[])
    assert asyncio.run(linker.deep_dive_works(resume)) == []


def test_select_questions_builds_custom_questions(monkeypatch):
    """_deep_dive_experience 应把 LLM 生成的定制追问组装为 ProjectQuestionLink。"""
    from app.resume import linker
    import asyncio

    candidates = [{"question_id": "q1", "question": "参考题", "score": 0.9}]

    class FakeRaw:
        pass

    class FakeModel:
        async def ainvoke(self, messages):
            raw = FakeRaw()
            raw.content = (
                '[{"question": "你的 RAG 项目为什么选 LangGraph 而不是别的编排框架？", "reason": "项目用了 LangGraph"}, '
                '{"question": "", "reason": "空问题应被跳过"}, '
                '{"question": "检索准确率提升 30% 是怎么做到的？", "reason": "量化成果"}]'
            )
            return raw

    monkeypatch.setattr(linker, "create_chat_model", lambda **kw: FakeModel())

    result = asyncio.run(
        linker._deep_dive_experience(
            name="项目A",
            role="",
            description="RAG 系统",
            tech_stack=["RAG", "LangGraph"],
            metrics=["准确率提升 30%"],
            source_type="project",
            candidates=candidates,
        )
    )
    # 空 question 被跳过，剩余 2 条
    assert len(result) == 2
    assert result[0].question.startswith("你的 RAG 项目为什么选 LangGraph")
    assert result[0].project_name == "项目A"
    assert result[0].reason == "项目用了 LangGraph"
    assert result[0].source_type == "project"
    # LLM 定制题无固定题库 ID
    assert result[0].question_id == ""


def test_deep_dive_experience_work_source_type(monkeypatch):
    """工作经历深挖应标记 source_type=work。"""
    from app.resume import linker
    import asyncio

    class FakeRaw:
        pass

    class FakeModel:
        async def ainvoke(self, messages):
            raw = FakeRaw()
            raw.content = '[{"question": "在腾讯实习时做的推荐系统为什么用双塔？", "reason": "实习项目"}]'
            return raw

    monkeypatch.setattr(linker, "create_chat_model", lambda **kw: FakeModel())

    result = asyncio.run(
        linker._deep_dive_experience(
            name="腾讯",
            role="算法实习生",
            description="推荐系统召回",
            tech_stack=["双塔"],
            metrics=[],
            source_type="work",
            candidates=[],
        )
    )
    assert len(result) == 1
    assert result[0].source_type == "work"
    assert result[0].project_name == "腾讯"
