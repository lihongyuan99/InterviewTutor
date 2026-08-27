from __future__ import annotations

import io
import json
import re
import shutil
import tarfile
from pathlib import Path

import pytest

from app.core.config import settings
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.schema import InterviewQuestion
from app.knowledge.snapshot import KnowledgeSnapshotManager, atomic_write_json
from app.knowledge.sync import (
    GitHubKnowledgeClient,
    KnowledgeSyncError,
    KnowledgeSyncService,
    _ProcessLease,
    safe_extract_markdown,
)


def _question(index: int, *, expert_suffix: str = "") -> InterviewQuestion:
    return InterviewQuestion(
        id=f"architecture-question-{index}",
        dimension="architecture",
        dimension_label="架构选型",
        title=f"测试题 {index}",
        question=f"测试题 {index} 唯一词{index:03d}",
        source="腾讯 Agent 工程师",
        novice_answer="不清楚",
        expert_answer=f"唯一词{index:03d} 的工程答案{expert_suffix}",
        gap_analysis="需要补充边界、指标和权衡。",
        key_points=["边界", "指标"],
        source_file="01-architecture-design/index.md",
        source_heading=f"测试题 {index}",
    )


def _manager(tmp_path: Path) -> KnowledgeSnapshotManager:
    bundled_source = tmp_path / "bundled-source"
    bundled_source.mkdir()
    bundled_db = tmp_path / "bundled.db"
    repo = KnowledgeRepository(str(bundled_db))
    repo.close()
    bundled_manifest = tmp_path / "bundled-manifest.json"
    atomic_write_json(
        bundled_manifest,
        {
            "release_id": "bundled",
            "question_count": 0,
            "dimension_count": 0,
            "source": {"commit_sha": ""},
        },
    )
    return KnowledgeSnapshotManager(
        runtime_dir=tmp_path / "runtime",
        bundled_db_path=bundled_db,
        bundled_source_dir=bundled_source,
        bundled_manifest_path=bundled_manifest,
    )


def _write_release(
    manager: KnowledgeSnapshotManager,
    release_id: str,
    source_sha: str,
    question: InterviewQuestion,
) -> Path:
    release = manager.releases_dir / release_id
    source = release / "source" / "01-architecture-design"
    source.mkdir(parents=True)
    (source / "index.md").write_text(
        f"### Q：{question.question}\n\n**高手答**：{question.expert_answer}\n",
        encoding="utf-8",
    )
    repo = KnowledgeRepository(str(release / "knowledge.db"))
    try:
        repo.replace_all([question], {question.id: [1.0, 0.0]})
    finally:
        repo.close()
    atomic_write_json(
        release / "manifest.json",
        {
            "release_id": release_id,
            "question_count": 1,
            "dimension_count": 1,
            "source": {"commit_sha": source_sha},
            "embedding": {"fingerprint": "test"},
        },
    )
    return release


def _write_tar(path: Path, files: dict[str, str], *, symlink: str = "") -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, content in files.items():
            payload = content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        if symlink:
            info = tarfile.TarInfo(symlink)
            info.type = tarfile.SYMTYPE
            info.linkname = "/tmp/escape"
            archive.addfile(info)


def _knowledge_markdown(count: int = 100, *, changed_index: int | None = None) -> str:
    blocks = []
    for index in range(count):
        suffix = "（新版增补）" if index == changed_index else ""
        blocks.append(
            f"""### Q：测试题 {index} 唯一词{index:03d}

> 来源：腾讯 Agent 工程师

**新手答**：不清楚。

**高手答**：唯一词{index:03d} 的工程答案{suffix}。

**差距在哪**：需要补充边界、指标和权衡。

---
"""
        )
    return "\n".join(blocks)


class _FakeEmbeddingClient:
    document_count = 0

    def __init__(self, *args, **kwargs):
        self.dim = settings.KNOWLEDGE_EMBEDDING_DIM
        self.model = settings.KNOWLEDGE_EMBEDDING_MODEL

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        match = re.search(r"唯一词(\d{3})", text)
        vector[int(match.group(1)) % self.dim if match else self.dim - 1] = 1.0
        return vector

    def embed(self, texts: list[str]) -> list[list[float]]:
        type(self).document_count += len(texts)
        return [self._vector(text) for text in texts]

    def embed_query(self, query: str) -> list[float]:
        return self._vector(query)


class _FakeGitHubClient:
    repository = "ranxi2001/zero2Agent"
    ref = "main"
    source_path = "learn-agent-interview"

    def __init__(self, archive_path: Path, source_sha: str):
        self.archive_path = archive_path
        self.source_sha = source_sha
        self.download_count = 0

    def check_latest(self, etag: str = ""):
        return (
            {"sha": self.source_sha, "date": "2026-08-26T00:00:00Z", "message": "test"},
            f'"{self.source_sha[:8]}"',
            False,
        )

    def download_archive(self, source_sha: str, destination: Path, progress=None):
        self.download_count += 1
        shutil.copyfile(self.archive_path, destination)
        if progress:
            size = destination.stat().st_size
            progress(size, size)
        return "archive-sha256"


def test_safe_extract_accepts_only_markdown_subtree(tmp_path):
    archive = tmp_path / "valid.tar.gz"
    _write_tar(
        archive,
        {
            "owner-repo-sha/learn-agent-interview/01-architecture-design/index.md": "# ok",
            "owner-repo-sha/learn-agent-interview/ignored.json": "{}",
            "owner-repo-sha/README.md": "outside",
        },
    )
    destination = tmp_path / "source"
    count, size = safe_extract_markdown(
        archive, destination, "learn-agent-interview"
    )
    assert count == 1
    assert size == len("# ok".encode())
    assert (destination / "01-architecture-design" / "index.md").read_text() == "# ok"
    assert not (destination / "ignored.json").exists()


@pytest.mark.parametrize(
    "member",
    [
        "../learn-agent-interview/escape.md",
        "/learn-agent-interview/escape.md",
    ],
)
def test_safe_extract_rejects_path_traversal(tmp_path, member):
    archive = tmp_path / "bad.tar.gz"
    _write_tar(archive, {member: "bad"})
    with pytest.raises(KnowledgeSyncError, match="非法路径"):
        safe_extract_markdown(archive, tmp_path / "source", "learn-agent-interview")


def test_safe_extract_rejects_symlink(tmp_path):
    archive = tmp_path / "link.tar.gz"
    _write_tar(
        archive,
        {
            "owner/learn-agent-interview/01-architecture-design/index.md": "# ok"
        },
        symlink="owner/learn-agent-interview/01-architecture-design/linked.md",
    )
    with pytest.raises(KnowledgeSyncError, match="链接或设备文件"):
        safe_extract_markdown(archive, tmp_path / "source", "learn-agent-interview")


def test_safe_extract_rejects_corrupted_archive(tmp_path):
    archive = tmp_path / "corrupt.tar.gz"
    archive.write_bytes(b"not a tar archive")
    with pytest.raises(KnowledgeSyncError, match="压缩包无效"):
        safe_extract_markdown(archive, tmp_path / "source", "learn-agent-interview")


def test_github_client_uses_etag_and_handles_304():
    class Response:
        status_code = 304
        headers = {"ETag": '"new-etag"'}

    class Session:
        def get(self, url, **kwargs):
            assert kwargs["headers"]["If-None-Match"] == '"old-etag"'
            assert kwargs["params"]["path"] == "learn-agent-interview"
            return Response()

    client = GitHubKnowledgeClient()
    client._session = Session()
    latest, etag, not_modified = client.check_latest('"old-etag"')
    assert latest is None
    assert etag == '"new-etag"'
    assert not_modified is True


def test_github_client_respects_retry_after():
    class Response:
        status_code = 429
        headers = {"Retry-After": "120"}

    with pytest.raises(KnowledgeSyncError) as raised:
        GitHubKnowledgeClient._raise_for_rate_limit(Response())
    assert raised.value.retry_after_seconds == 120


def test_process_lease_deduplicates_builds(tmp_path):
    first = _ProcessLease(tmp_path / "sync.lock")
    second = _ProcessLease(tmp_path / "sync.lock")
    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()


def test_snapshot_activation_old_connection_and_rollback(tmp_path):
    manager = _manager(tmp_path)
    manager.ensure_runtime_dirs()
    q1 = _question(1)
    q2 = _question(2)
    r1 = _write_release(manager, "release-one", "1" * 40, q1)
    _write_release(manager, "release-two", "2" * 40, q2)

    manager.activate("release-one")
    old_repo = KnowledgeRepository(str(r1 / "knowledge.db"))
    manager.activate("release-two")
    try:
        assert manager.resolve().snapshot_id == "release-two"
        assert old_repo.get(q1.id).question == q1.question
    finally:
        old_repo.close()

    reverted, target = manager.rollback()
    assert reverted.snapshot_id == "release-two"
    assert target.snapshot_id == "release-one"
    assert manager.read_pointer()["suppressed_sha"] == "2" * 40


def test_snapshot_retains_current_and_two_previous_releases(tmp_path):
    manager = _manager(tmp_path)
    manager.ensure_runtime_dirs()
    for index in range(4):
        release_id = f"release-{index}"
        _write_release(manager, release_id, str(index) * 40, _question(index))
        manager.activate(release_id)
    manager.prune_releases()
    assert {path.name for path in manager.releases_dir.iterdir()} == {
        "release-1",
        "release-2",
        "release-3",
    }


def test_validation_rejects_duplicate_ids_and_large_drop(tmp_path):
    service = KnowledgeSyncService(manager=_manager(tmp_path))
    duplicated = [_question(index) for index in range(99)] + [_question(1)]
    with pytest.raises(KnowledgeSyncError, match="重复题目 ID"):
        service._validate_questions(duplicated, [], previous_count=0)
    questions = [_question(index) for index in range(100)]
    with pytest.raises(KnowledgeSyncError, match="20%"):
        service._validate_questions(questions, [], previous_count=200)


def test_cleanup_removes_crashed_staging(tmp_path):
    manager = _manager(tmp_path)
    manager.ensure_runtime_dirs()
    crashed = manager.staging_dir / "crashed" / "nested"
    crashed.mkdir(parents=True)
    (crashed / "partial.db").write_bytes(b"partial")
    KnowledgeSyncService(manager=manager)._cleanup_staging()
    assert list(manager.staging_dir.iterdir()) == []


def test_successful_sync_and_incremental_embedding_reuse(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "KNOWLEDGE_EMBEDDING_DIM", 128)
    monkeypatch.setattr(
        "app.core.embedding_client.Qwen3EmbeddingClient", _FakeEmbeddingClient
    )
    _FakeEmbeddingClient.document_count = 0

    first_archive = tmp_path / "first.tar.gz"
    _write_tar(
        first_archive,
        {
            "owner-repo-a/learn-agent-interview/01-architecture-design/index.md": _knowledge_markdown()
        },
    )
    client = _FakeGitHubClient(first_archive, "a" * 40)
    manager = _manager(tmp_path)
    manager.ensure_runtime_dirs()
    service = KnowledgeSyncService(manager=manager, client_factory=lambda: client)

    service._run_sync(False, False)
    first_status = service.status()
    assert first_status["phase"] == "idle"
    assert first_status["current"]["source_sha"] == "a" * 40
    assert first_status["current"]["question_count"] == 100
    assert _FakeEmbeddingClient.document_count == 100
    assert client.download_count == 1

    # 同一 SHA 只检查不重复下载或构建。
    service._run_sync(False, False)
    assert client.download_count == 1

    second_archive = tmp_path / "second.tar.gz"
    _write_tar(
        second_archive,
        {
            "owner-repo-b/learn-agent-interview/01-architecture-design/index.md": _knowledge_markdown(
                changed_index=42
            )
        },
    )
    client.archive_path = second_archive
    client.source_sha = "b" * 40
    _FakeEmbeddingClient.document_count = 0

    service._run_sync(False, False)
    current = manager.resolve()
    assert current.manifest["source"]["commit_sha"] == "b" * 40
    assert current.manifest["embedding"]["reused"] == 99
    assert current.manifest["embedding"]["generated"] == 1
    assert _FakeEmbeddingClient.document_count == 1

    reverted = service.rollback()
    assert reverted["current"]["source_sha"] == "a" * 40
    assert reverted["suppressed_sha"] == "b" * 40

    # 自动任务抑制被回滚的同一 SHA；手动 force 可重新启用。
    service._run_sync(False, True)
    assert manager.resolve().manifest["source"]["commit_sha"] == "a" * 40
    service._run_sync(True, False)
    assert manager.resolve().manifest["source"]["commit_sha"] == "b" * 40
    assert manager.read_pointer()["suppressed_sha"] == ""


def test_embedding_failure_keeps_bundled_snapshot(tmp_path, monkeypatch):
    class FailingEmbedding(_FakeEmbeddingClient):
        def embed(self, texts):
            raise RuntimeError("embedding unavailable")

    monkeypatch.setattr(settings, "KNOWLEDGE_EMBEDDING_DIM", 128)
    monkeypatch.setattr(
        "app.core.embedding_client.Qwen3EmbeddingClient", FailingEmbedding
    )
    archive = tmp_path / "failure.tar.gz"
    _write_tar(
        archive,
        {
            "owner-repo-c/learn-agent-interview/01-architecture-design/index.md": _knowledge_markdown()
        },
    )
    client = _FakeGitHubClient(archive, "c" * 40)
    manager = _manager(tmp_path)
    manager.ensure_runtime_dirs()
    service = KnowledgeSyncService(manager=manager, client_factory=lambda: client)

    service._run_sync(False, False)
    status = service.status()
    assert status["phase"] == "failed"
    assert "embedding unavailable" in status["last_error"]
    assert status["current"]["snapshot_id"] == "bundled"
    assert list(manager.releases_dir.iterdir()) == []
