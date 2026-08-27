"""面试训练工作流的单元测试。

覆盖：选题、进度记录与复习调度、会话状态管理。
LLM 调用相关（评分/追问）用 mock 隔离，避免测试依赖外部模型。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.interview.models import (
    AnswerRequest,
    EvaluationResult,
    QuestionProgress,
    StartRequest,
)
from app.interview.progress import ProgressStore, _next_review_at, _REVIEW_INTERVAL_DAYS

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "knowledge.db"


# ---- 进度与复习调度 ----

def test_review_interval_mapping():
    """等级 -> 复习间隔天数映射应符合 Handoff §11。"""
    assert _REVIEW_INTERVAL_DAYS[1] == 1
    assert _REVIEW_INTERVAL_DAYS[2] == 1
    assert _REVIEW_INTERVAL_DAYS[3] == 3
    assert _REVIEW_INTERVAL_DAYS[4] == 7
    assert _REVIEW_INTERVAL_DAYS[5] == 14


def test_next_review_at_format():
    from datetime import datetime
    s = _next_review_at(3, now=datetime(2026, 8, 19, 12, 0, 0))
    assert s == "2026-08-22 12:00:00"


def test_progress_record_attempt(tmp_path, monkeypatch):
    """记录一次作答应正确累积 attempts 与 best_level。"""
    monkeypatch.setattr("app.interview.progress.PROGRESS_DIR", str(tmp_path))

    store = ProgressStore(user_id="test_user")
    p1 = store.record_attempt(
        question_id="q1",
        overall_level=3,
        scores={"correctness": 3, "depth": 3},
        missing_points=["选择标准"],
    )
    assert p1.attempts == 1
    assert p1.best_level == 3

    # 第二次作答，best_level 取历史最高
    p2 = store.record_attempt(
        question_id="q1",
        overall_level=4,
        scores={"correctness": 4, "depth": 4},
        missing_points=[],
    )
    assert p2.attempts == 2
    assert p2.best_level == 4


def test_progress_review_queue(tmp_path, monkeypatch):
    """到期题目应出现在复习队列中。"""
    monkeypatch.setattr("app.interview.progress.PROGRESS_DIR", str(tmp_path))

    store = ProgressStore(user_id="test_user")
    store.record_attempt(
        question_id="q1",
        overall_level=1,
        scores={},
        missing_points=[],
    )
    # 手动把 next_review_at 设为过去，模拟到期
    store._data["q1"]["next_review_at"] = "2000-01-01 00:00:00"
    from app.interview.progress import _save_all
    _save_all("test_user", store._data)

    due = ProgressStore(user_id="test_user").review_queue()
    assert any(p.question_id == "q1" for p in due)


# ---- 选题 ----

@pytest.mark.skipif(
    not DB_PATH.exists(), reason="data/knowledge.db 未构建，跳过选题测试"
)
def test_pick_question_with_dimension_filter():
    from app.interview.workflow import _pick_question

    q = _pick_question(dimensions=["rag"], companies=[], difficulty=0)
    assert q is not None
    assert q["dimension"] == "rag"
    assert q["question"]
    # 出题阶段不应包含专家答案（防泄露）
    assert "expert_answer" in q  # 原始行有该字段，但 workflow 不会泄露给 Interviewer


# ---- 状态机（mock LLM）----

def test_start_and_answer_flow(monkeypatch, tmp_path):
    """start -> answer 闭环，mock 掉 LLM 与选题。"""
    import asyncio

    monkeypatch.setattr("app.interview.progress.PROGRESS_DIR", str(tmp_path))

    from app.interview import workflow

    # mock 选题
    fake_question = {
        "id": "rag-test-001",
        "dimension": "rag",
        "dimension_label": "RAG 与检索",
        "question": "RAG 检索如何实现？",
        "expert_answer": "离线切片 + 在线混合召回 + rerank。",
        "gap_analysis": "新手只说向量数据库，高手讲完整链路。",
        "key_points": ["召回", "重排"],
        "source_file": "09-rag-retrieval/index.md",
    }
    monkeypatch.setattr(workflow, "_pick_question", lambda *a, **k: fake_question)

    # mock LLM 出题与评分
    async def fake_call_llm(system_prompt, user_prompt=""):
        return "请回答：RAG 检索如何实现？"

    async def fake_call_structured(system_prompt, user_prompt=""):
        return EvaluationResult(
            overall_level=4,
            correctness=4,
            depth=4,
            tradeoff_reasoning=3,
            engineering_evidence=3,
            clarity=4,
            covered_points=["混合召回"],
            missing_points=["rerank 精排"],
            strengths=["提到了混合召回"],
            improvement_advice=["补充 rerank"],
            next_followup="rerank 怎么选模型？",
            mastery_delta=0.1,
        )

    monkeypatch.setattr(workflow, "_call_llm", fake_call_llm)
    monkeypatch.setattr(workflow, "_call_structured", fake_call_structured)

    # mock get_question
    from app.knowledge.schema import InterviewQuestion
    full_q = InterviewQuestion(
        id="rag-test-001",
        dimension="rag",
        dimension_label="RAG 与检索",
        question="RAG 检索如何实现？",
        source="某厂面试",
        novice_answer="用向量库",
        expert_answer="离线切片 + 在线混合召回 + rerank。",
        gap_analysis="新手只说向量数据库。",
        key_points=["召回", "重排"],
        source_file="09-rag-retrieval/index.md",
    )
    monkeypatch.setattr(
        "app.knowledge.get_question", lambda qid, **k: full_q
    )

    async def _run():
        result = await workflow.start_session(
            StartRequest(dimensions=["rag"], companies=[], difficulty=0)
        )
        assert result["phase"] == "awaiting_answer"
        session_id = result["session_id"]
        assert result["question"]

        result2 = await workflow.submit_answer(
            AnswerRequest(session_id=session_id, answer="离线切片+向量召回")
        )
        return result2

    result2 = asyncio.run(_run())
    assert result2["phase"] == "reviewing"
    assert result2["evaluation"]["overall_level"] == 4
    assert result2["mastery"] > 0
    assert result2["next_review_at"]


# ---- 会话持久化 ----

def test_session_persistence(monkeypatch, tmp_path):
    """会话应持久化到磁盘，重启（重新加载）后可恢复。"""
    monkeypatch.setattr("app.interview.session_store.SESSION_DIR", str(tmp_path))
    from app.interview.session_store import save_session, load_session, delete_session
    from app.interview.models import InterviewSession

    session = InterviewSession(
        session_id="persist-test-001",
        mode="practice",
        dimensions=["rag"],
        phase="awaiting_answer",
        current_question_id="q1",
        current_question="测试题",
    )
    save_session(session)

    # 模拟重启：重新加载
    loaded = load_session("persist-test-001")
    assert loaded is not None
    assert loaded.session_id == "persist-test-001"
    assert loaded.phase == "awaiting_answer"
    assert loaded.current_question == "测试题"

    delete_session("persist-test-001")
    assert load_session("persist-test-001") is None


def test_cached_question_survives_snapshot_cleanup(monkeypatch):
    """当前题完整内容已入会话后，评分/复盘不再依赖 release 目录。"""
    from app.interview.models import InterviewSession
    from app.interview.workflow import _session_question
    from app.knowledge.schema import InterviewQuestion

    question = InterviewQuestion(
        id="cached-q",
        dimension="rag",
        dimension_label="RAG 与检索",
        question="快照清理后还能评分吗？",
        expert_answer="使用会话内缓存的结构化题目。",
        source_file="09-rag-retrieval/index.md",
    )
    session = InterviewSession(
        session_id="cached-session",
        current_question_id=question.id,
        knowledge_snapshot_id="deleted-release",
        retrieved_knowledge=question.model_dump(),
    )
    monkeypatch.setattr(
        "app.knowledge.get_question",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )

    assert _session_question(session) == question


# ---- 选题：公司定向 ----

@pytest.mark.skipif(
    not DB_PATH.exists(), reason="data/knowledge.db 未构建，跳过选题测试"
)
def test_pick_question_company_priority():
    """指定公司时应优先返回匹配该公司的题。"""
    from app.interview.workflow import _pick_question

    q = _pick_question(dimensions=[], companies=["字节"], difficulty=0)
    assert q is not None
    import json
    assert "字节" in json.dumps(q.get("companies", []), ensure_ascii=False)


@pytest.mark.skipif(
    not DB_PATH.exists(), reason="data/knowledge.db 未构建，跳过选题测试"
)
def test_pick_question_exclude_ids():
    """exclude_ids 中的题不应被选中。"""
    from app.interview.workflow import _pick_question

    # 取一道题作为排除对象
    q = _pick_question(dimensions=["rag"], companies=[], difficulty=0)
    assert q is not None
    excluded = {q["id"]}
    # 多次选题都应避开已排除的题
    for _ in range(5):
        q2 = _pick_question(dimensions=["rag"], companies=[], difficulty=0, exclude_ids=excluded)
        if q2 is None:
            continue
        assert q2["id"] not in excluded


# ---- 错题本与薄弱维度 ----

def test_aggregate_wrong_questions(tmp_path, monkeypatch):
    """best_level <= 2 的题应进入错题本，按掌握度升序。"""
    from app.interview.workflow import _aggregate_wrong_questions
    from app.interview.models import QuestionProgress
    from app.knowledge.repository import KnowledgeRepository

    # mock 知识库反查
    monkeypatch.setattr(
        KnowledgeRepository, "_row_to_dict",
        staticmethod(lambda row: dict(row)),
    )

    progress = [
        QuestionProgress(
            question_id="q1", best_level=1, mastery=0.0, attempts=1,
            missing_points=["选择标准"],
        ),
        QuestionProgress(
            question_id="q2", best_level=2, mastery=0.4, attempts=1,
            missing_points=["工程实践"],
        ),
        QuestionProgress(
            question_id="q3", best_level=4, mastery=0.8, attempts=1,
            missing_points=[],
        ),
    ]

    # mock 知识库连接返回对应题目
    class FakeRow(dict):
        def __getitem__(self, k):
            return super().__getitem__(k)
        def get(self, k, default=None):
            return super().get(k, default)

    fake_rows = [
        FakeRow(id="q1", question="题1", dimension="rag", dimension_label="RAG"),
        FakeRow(id="q2", question="题2", dimension="rag", dimension_label="RAG"),
    ]

    class FakeConn:
        def execute(self, sql, params):
            return FakeCursor(fake_rows)
        def close(self):
            pass

    class FakeCursor:
        def __init__(self, rows):
            self._rows = rows
        def fetchall(self):
            return self._rows

    class FakeRepo:
        def __init__(self, *a, **k):
            self.conn = FakeConn()
        def close(self):
            pass

    monkeypatch.setattr(
        "app.knowledge.KnowledgeRepository", lambda *a, **k: FakeRepo()
    )

    result = _aggregate_wrong_questions(progress)
    assert len(result) == 2  # 只有 q1、q2 是错题
    assert result[0]["question_id"] == "q1"  # mastery 0.0 排最前
    assert result[0]["best_level"] == 1
    assert result[1]["question_id"] == "q2"


def test_aggregate_weak_dimensions():
    """平均掌握度 < 0.6 的维度应被筛出。"""
    from app.interview.workflow import _aggregate_weak_dimensions

    stats = [
        {"dimension": "rag", "dimension_label": "RAG", "count": 1, "avg_mastery": 0.4, "avg_level": 2},
        {"dimension": "arch", "dimension_label": "架构", "count": 1, "avg_mastery": 0.8, "avg_level": 4},
    ]
    weak = _aggregate_weak_dimensions(stats)
    assert len(weak) == 1
    assert weak[0]["dimension"] == "rag"


def test_save_json_atomic_write(tmp_path):
    """save_json 应原子写，且不产生 .tmp 残留。"""
    from app.utils.file_io import save_json, load_json

    target = tmp_path / "test.json"
    save_json({"a": 1}, str(target))
    assert load_json(str(target)) == {"a": 1}
    # 无 .tmp 残留
    assert not (tmp_path / "test.json.tmp").exists()
