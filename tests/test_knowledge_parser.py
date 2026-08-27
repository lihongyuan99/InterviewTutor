"""知识解析器的单元测试。

重点校验：题目总数、关键字段、稳定 ID、两类文件解析、
维度归一化、以及非题库目录被跳过。
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.knowledge import KnowledgeParser, parse_knowledge_dir  # noqa: E402
from app.knowledge.sync import question_hashes, sha256_file  # noqa: E402

KNOWLEDGE_ROOT = Path(__file__).resolve().parent.parent / "knowledge"


@pytest.fixture(scope="module")
def parsed():
    questions, warnings = parse_knowledge_dir(str(KNOWLEDGE_ROOT))
    return questions, warnings


def test_question_count_within_expected_range(parsed):
    """随包源文件的解析结果必须与 manifest 完全对齐。"""
    questions, warnings = parsed
    manifest = json.loads(
        (KNOWLEDGE_ROOT.parent / "data" / "knowledge_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(questions) == manifest["question_count"]
    assert len({question.dimension for question in questions}) == manifest["dimension_count"]
    assert len(warnings) == manifest["parse_warning_count"]


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


def test_single_question_file_parses_expert_answer(tmp_path):
    """单题 Markdown 能力由临时夹具覆盖，不再依赖本地补充题。"""
    dimension_dir = tmp_path / "01-architecture-design"
    dimension_dir.mkdir()
    fixture = dimension_dir / "single.md"
    fixture.write_text(
        """## Q：Agent 循环如何退出？

> 来源：腾讯 Agent 工程师

**新手答**：设一个次数。

**高手答**：结合成功条件、预算、超时和无进展检测。

**差距在哪**：需要可观测的多重退出条件。

## 考察点

- 资源预算
- 死循环检测
""",
        encoding="utf-8",
    )
    questions, warnings = parse_knowledge_dir(str(tmp_path))
    assert not warnings
    assert len(questions) == 1
    assert questions[0].expert_answer.startswith("结合成功条件")
    assert questions[0].key_points == ["资源预算", "死循环检测"]


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


def test_new_infrastructure_dimensions_are_normalized(parsed):
    questions, _ = parsed
    labels = {question.dimension: question.dimension_label for question in questions}
    assert labels["agent-infra"] == "Agent 基础设施"
    assert labels["ai-infra"] == "AI 基础设施"


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


def test_bundled_manifest_hashes_match_sources(parsed):
    questions, warnings = parsed
    manifest_path = KNOWLEDGE_ROOT.parent / "data" / "knowledge_manifest.json"
    db_path = KNOWLEDGE_ROOT.parent / "data" / "knowledge.db"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["source"]["commit_sha"] == "f7c2e45eacb18546dd879a589c12664ef82d2087"
    assert manifest["question_hashes"] == {
        question.id: question_hashes(question) for question in questions
    }
    assert manifest["parse_warning_count"] == len(warnings)
    assert manifest["database_sha256"] == sha256_file(db_path)
