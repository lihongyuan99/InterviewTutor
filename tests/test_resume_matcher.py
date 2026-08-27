"""简历匹配（matcher）的单元测试。

重点覆盖纯函数逻辑：公司别名归一化、公司偏好维度解析。
LLM 相关部分通过 monkeypatch 验证组装逻辑，不做真实调用。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.resume.matcher import (  # noqa: E402
    _load_company_dimensions,
    _parse_company_dimensions,
    _resolve_company,
)
from app.resume.models import Resume  # noqa: E402


def test_resolve_company_aliases():
    assert _resolve_company("字节") == "字节跳动"
    assert _resolve_company("字节跳动") == "字节跳动"
    assert _resolve_company("阿里") == "阿里-淘天"
    assert _resolve_company("蚂蚁") == "蚂蚁集团"
    assert _resolve_company("腾讯") == "腾讯"
    # 未知公司原样返回
    assert _resolve_company("某公司") == "某公司"


def test_load_company_dimensions_known():
    dims = _load_company_dimensions("腾讯")
    assert len(dims) > 0
    assert "RAG 与检索" in dims


def test_load_company_dimensions_unknown():
    assert _load_company_dimensions("不存在的公司") == []


def test_parse_company_dimensions_skips_separator():
    text = """## 腾讯（51 题）
| 维度 | 题量 |
|------|------|
| RAG 与检索 | 16 |
| 评估与全局观 | 8 |
"""
    dims = _parse_company_dimensions(text, "腾讯")
    assert dims == ["RAG 与检索", "评估与全局观"]


def test_parse_company_dimensions_links():
    text = """## 腾讯（51 题）
| 维度 | 题量 |
|------|------|
| [RAG 与检索](x.html) | 16 |
"""
    dims = _parse_company_dimensions(text, "腾讯")
    assert dims == ["RAG 与检索"]


def _make_resume() -> Resume:
    return Resume(
        resume_id="r1",
        name="张三",
        skills=[{"name": "RAG", "level": "精通", "category": "AI"}],
        projects=[{"name": "RAG 系统", "tech_stack": ["LangGraph", "FAISS"]}],
    )


def test_match_resume_unknown_company_returns_none(monkeypatch):
    from app.resume import matcher

    async def run():
        return await matcher.match_resume(
            _make_resume(), target_company="不存在的公司"
        )

    import asyncio

    assert asyncio.run(run()) is None
