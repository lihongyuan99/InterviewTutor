"""简历结构化解析的单元测试。

用 monkeypatch 替换 ``create_chat_model``，避免真实 LLM 调用，
只校验 parser 的组装逻辑与边界处理。
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.resume.models import Resume  # noqa: E402
from app.resume.parser import ResumeParseError, parse_resume  # noqa: E402


class _FakeStructured:
    """模拟 ``with_structured_output`` 返回的可调用对象。"""

    def __init__(self, result):
        self._result = result

    async def ainvoke(self, messages):
        return self._result


class _FakeModel:
    def with_structured_output(self, schema):
        return _FakeStructured(self._result)

    def set_result(self, result):
        self._result = result


@pytest.fixture
def fake_model(monkeypatch):
    fake = _FakeModel()
    # 替换 create_chat_model：注意 parser 里调用时带 role 参数
    def _create(**kwargs):
        return fake

    import app.resume.parser as parser_mod

    monkeypatch.setattr(parser_mod, "create_chat_model", _create)
    return fake


SAMPLE_RAW = """
张三
手机：13800000000  邮箱：zhangsan@example.com

个人简介
五年 AI Agent 工程经验，熟悉 LangGraph、RAG。

教育经历
北京大学 硕士 计算机 2016-2019

项目经历
项目A：企业级 RAG 问答系统
- 使用 LangGraph 编排多智能体
- QPS 提升 30%

技能
Python 精通
LangGraph 掌握
"""


def _fake_resume_dict():
    return {
        "name": "张三",
        "contact": "（已脱敏）",
        "target_role": "",
        "target_companies": [],
        "summary": "五年 AI Agent 工程经验",
        "educations": [
            {"school": "北京大学", "degree": "硕士", "major": "计算机",
             "start": "2016", "end": "2019", "highlights": []}
        ],
        "works": [],
        "projects": [
            {"name": "企业级 RAG 问答系统", "role": "", "period": "",
             "description": "使用 LangGraph 编排多智能体",
             "tech_stack": ["LangGraph", "RAG"],
             "metrics": ["QPS 提升 30%"], "highlights": []}
        ],
        "skills": [
            {"name": "Python", "level": "精通", "category": "编程语言"},
            {"name": "LangGraph", "level": "掌握", "category": "框架"},
        ],
        "honors": [],
    }


def test_parse_resume_returns_resume(fake_model):
    fake_model.set_result(_fake_resume_dict())
    resume = asyncio.run(
        parse_resume(
            SAMPLE_RAW, resume_id="r1", source_file="r.pdf", source_type="pdf"
        )
    )
    assert isinstance(resume, Resume)
    assert resume.name == "张三"
    assert resume.resume_id == "r1"
    assert resume.source_type == "pdf"
    assert resume.source_file == "r.pdf"
    assert len(resume.projects) == 1
    assert resume.projects[0].tech_stack == ["LangGraph", "RAG"]
    assert resume.projects[0].metrics == ["QPS 提升 30%"]
    assert len(resume.skills) == 2


def test_parse_resume_empty_raw(fake_model):
    with pytest.raises(ResumeParseError):
        asyncio.run(parse_resume("   "))


def test_parse_resume_none_result(fake_model):
    fake_model.set_result(None)
    with pytest.raises(ResumeParseError):
        asyncio.run(parse_resume(SAMPLE_RAW))


def test_parse_resume_missing_fields_defaulted(fake_model):
    # 模型只返回部分字段，其余应回退为默认值
    fake_model.set_result({"name": "李四"})
    resume = asyncio.run(parse_resume(SAMPLE_RAW, resume_id="r2"))
    assert resume.name == "李四"
    assert resume.resume_id == "r2"
    assert resume.projects == []
    assert resume.skills == []
    assert resume.educations == []
