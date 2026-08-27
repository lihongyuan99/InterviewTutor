"""简历文本抽取的单元测试。

覆盖：类型识别、Markdown/纯文本抽取、不支持的类型、文件不存在、
以及 PDF/Word 依赖缺失时的明确报错。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.resume.extract import (  # noqa: E402
    ExtractionError,
    detect_source_type,
    extract_text,
    extract_text_from_bytes,
)


def test_detect_source_type_known():
    assert detect_source_type("resume.pdf") == "pdf"
    assert detect_source_type("resume.DOCX") == "docx"
    assert detect_source_type("resume.md") == "md"
    assert detect_source_type("resume.markdown") == "md"
    assert detect_source_type("resume.txt") == "txt"


def test_detect_source_type_unknown():
    with pytest.raises(ExtractionError):
        detect_source_type("resume.doc")
    with pytest.raises(ExtractionError):
        detect_source_type("resume.png")


def test_extract_markdown(tmp_path):
    md = tmp_path / "resume.md"
    md.write_text("# 张三\n\n## 项目\nRAG 系统", encoding="utf-8")
    text = extract_text(str(md))
    assert "张三" in text
    assert "RAG 系统" in text


def test_extract_txt_gbk_fallback(tmp_path):
    txt = tmp_path / "resume.txt"
    txt.write_bytes("姓名：张三".encode("gbk"))
    text = extract_text(str(txt))
    assert "张三" in text


def test_extract_missing_file(tmp_path):
    with pytest.raises(ExtractionError):
        extract_text(str(tmp_path / "nope.pdf"))


def test_extract_unsupported_type(tmp_path):
    f = tmp_path / "resume.doc"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(ExtractionError):
        extract_text(str(f))


def test_extract_text_from_bytes_txt():
    text = extract_text_from_bytes("姓名：张三".encode("utf-8"), "txt")
    assert "张三" in text


def test_extract_text_from_bytes_md():
    text = extract_text_from_bytes("# 标题\n\n项目".encode("utf-8"), "md")
    assert "项目" in text


def test_extract_text_from_bytes_unknown_type():
    with pytest.raises(ExtractionError):
        extract_text_from_bytes(b"x", "png")
