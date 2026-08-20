"""知识解析器的单元测试。

重点校验：题目总数、关键字段、稳定 ID、两类文件解析、
维度归一化、以及非题库目录被跳过。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.knowledge import KnowledgeParser, parse_knowledge_dir  # noqa: E402

KNOWLEDGE_ROOT = Path(__file__).resolve().parent.parent / "knowledge"


@pytest.fixture(scope="module")
def parsed():
    questions, warnings = parse_knowledge_dir(str(KNOWLEDGE_ROOT))
    return questions, warnings


def test_question_count_within_expected_range(parsed):
    """题目总数应接近 Handoff 文档提到的约 486 道，且不能为空。"""
    questions, _ = parsed
    assert len(questions) > 0
    # Handoff 文档 §3 提到约 486 个 Q 段落，允许一定偏差但不应静默丢失
    assert 400 <= len(questions) <= 600, f"题目数量异常：{len(questions)}"


def test_key_fields_present(parsed):
    questions, _ = parsed
    for q in questions:
        assert q.id, f"题目缺少 id：{q.source_file}"
        assert q.dimension, f"题目缺少 dimension：{q.source_file}"
        assert q.question, f"题目缺少 question：{q.source_file}"
        assert q.source_file, f"题目缺少 source_file"


def test_stable_id_is_reproducible(parsed):
    """同一道题两次解析应得到相同 ID。"""
    questions, _ = parsed
    q1, _ = parse_knowledge_dir(str(KNOWLEDGE_ROOT))
    ids_a = {q.id for q in questions}
    ids_b = {q.id for q in q1}
    assert ids_a == ids_b, "两次解析的 ID 集合不一致"


def test_ids_are_unique(parsed):
    questions, _ = parsed
    ids = [q.id for q in questions]
    assert len(ids) == len(set(ids)), "存在重复题目 ID"


def test_no_questions_from_coaching_methodology(parsed):
    """coaching-methodology 是非题库目录，不应被解析。"""
    questions, _ = parsed
    for q in questions:
        assert "coaching-methodology" not in q.source_file


def test_dimension_normalization(parsed):
    """重叠目录应归一到同一维度。"""
    questions, _ = parsed
    dims = {q.dimension for q in questions}
    # 01-architecture 与 01-architecture-design 都应为 architecture
    arch_files = [q for q in questions if q.dimension == "architecture"]
    assert arch_files, "应存在 architecture 维度题目"
    # 04-rag 与 09-rag-retrieval 都应为 rag
    rag_files = [q for q in questions if q.dimension == "rag"]
    assert rag_files, "应存在 rag 维度题目"


def test_single_question_file_parses_expert_answer(parsed):
    """单题文件（01-architecture/react-loop.md）应能解析出高手答。"""
    questions, _ = parsed
    react = [q for q in questions if q.source_file.endswith("01-architecture/react-loop.md")]
    assert react, "未解析到 react-loop.md"
    assert any(q.expert_answer for q in react), "react-loop.md 缺少高手答"


def test_index_file_parses_multiple_questions(parsed):
    """index.md 应解析出多道题（而非只取第一道）。"""
    questions, _ = parsed
    arch_index = [
        q for q in questions
        if q.source_file.endswith("01-architecture-design/index.md")
    ]
    assert len(arch_index) > 1, "index.md 应解析出多道题"


def test_source_companies_extracted(parsed):
    """「来源」行中的公司应被提取。"""
    questions, _ = parsed
    with_company = [q for q in questions if q.companies]
    assert with_company, "未从来源中提取到任何公司"


def test_followups_extracted(parsed):
    """内嵌追问（**追问：xxx**）应被提取。"""
    questions, _ = parsed
    with_followup = [q for q in questions if q.followups]
    assert with_followup, "未解析到任何追问"


def test_single_file_key_points_section(parsed):
    """带独立「## 考察点」的单题文件应提取考察点。"""
    questions, _ = parsed
    tool_calling = [
        q for q in questions if q.source_file.endswith("01-architecture/tool-calling.md")
    ]
    assert tool_calling, "未解析到 tool-calling.md"
    assert any(q.key_points for q in tool_calling), "tool-calling.md 应包含考察点"


def test_gap_analysis_extracted(parsed):
    """「差距在哪」应被单独提取，而非混入高手答。"""
    questions, _ = parsed
    with_gap = [q for q in questions if q.gap_analysis]
    # 源文件约 475 处「差距在哪」，覆盖率应足够高
    assert len(with_gap) >= 400, f"gap_analysis 覆盖率过低：{len(with_gap)}"
    # 高手答不应再包含「差距在哪」标记
    for q in questions:
        assert "差距在哪" not in q.expert_answer, f"高手答混入差距分析：{q.source_file}"


def test_source_extracted(parsed):
    """来源（公司/岗位）应被提取。"""
    questions, _ = parsed
    with_source = [q for q in questions if q.source]
    assert len(with_source) == len(questions), "并非所有题目都有来源"


def test_dimension_label_present(parsed):
    """维度应有中文名。"""
    questions, _ = parsed
    for q in questions:
        assert q.dimension_label, f"缺少维度中文名：{q.dimension}"
