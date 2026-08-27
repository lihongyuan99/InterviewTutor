"""GitHub-backed dynamic synchronization for the interview knowledge base."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import shutil
import sqlite3
import tarfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Optional

from app.knowledge.indexer import KnowledgeIndexer, build_embedding_text
from app.knowledge.parser import parse_knowledge_dir
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.retriever import KnowledgeRetriever
from app.knowledge.schema import InterviewQuestion
from app.knowledge.snapshot import (
    KnowledgeSnapshot,
    KnowledgeSnapshotManager,
    atomic_write_json,
    snapshot_manager,
)


logger = logging.getLogger(__name__)

PIPELINE_VERSION = 1
BUSY_PHASES = {
    "checking",
    "downloading",
    "parsing",
    "embedding",
    "validating",
    "activating",
}
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_EXTRACTED_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_FILES = 1000
MIN_QUESTION_COUNT = 100


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime] = None) -> str:
    return (value or _utcnow()).isoformat()


def _parse_datetime(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_tree(root: Path) -> None:
    """Flush staged release files and directories before the atomic rename."""
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_file():
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
        elif path.is_dir():
            try:
                descriptor = os.open(str(path), os.O_RDONLY)
            except OSError:
                continue
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def embedding_fingerprint(model: str, dimension: int) -> str:
    return _sha256_text(f"{PIPELINE_VERSION}\0{model}\0{dimension}")


def question_hashes(question: InterviewQuestion) -> dict:
    canonical = json.dumps(
        question.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    embedding_input = build_embedding_text(question)
    return {
        "content_hash": _sha256_text(canonical),
        "embedding_hash": _sha256_text(
            f"{PIPELINE_VERSION}\0{embedding_input}"
        ),
    }


class KnowledgeSyncError(RuntimeError):
    def __init__(self, message: str, *, retry_after_seconds: Optional[int] = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class _KnowledgeSyncCancelled(KnowledgeSyncError):
    pass


class _ProcessLease:
    """Small dependency-free inter-process lock with stale-owner recovery."""

    def __init__(self, path: Path, stale_after_seconds: int = 6 * 60 * 60):
        self.path = path
        self.stale_after_seconds = stale_after_seconds
        self.owned = False

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except (PermissionError, OSError):
            return True

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(
                    str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                )
            except FileExistsError:
                try:
                    payload = json.loads(self.path.read_text(encoding="utf-8"))
                    pid = int(payload.get("pid", 0))
                    created_at = float(payload.get("created_at", 0))
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    pid, created_at = 0, 0
                stale = time.time() - created_at > self.stale_after_seconds
                if stale or not self._pid_alive(pid):
                    try:
                        self.path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                return False
            else:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(
                        {"pid": os.getpid(), "created_at": time.time()}, handle
                    )
                    handle.flush()
                    os.fsync(handle.fileno())
                self.owned = True
                return True
        return False

    def release(self) -> None:
        if not self.owned:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        self.owned = False


class GitHubKnowledgeClient:
    def __init__(self) -> None:
        from app.core.config import settings

        self.repository = settings.KNOWLEDGE_SOURCE_REPOSITORY.strip("/")
        self.ref = settings.KNOWLEDGE_SOURCE_REF
        self.source_path = settings.KNOWLEDGE_SOURCE_PATH.strip("/")
        self.token = settings.KNOWLEDGE_GITHUB_TOKEN.strip()
        self._session = None

    def _get_session(self):
        import requests

        if self._session is None:
            self._session = requests.Session()
        return self._session

    def _headers(self) -> dict:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "InterviewTutor-KnowledgeSync/1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    @staticmethod
    def _raise_for_rate_limit(response) -> None:
        if response.status_code not in {403, 429}:
            response.raise_for_status()
            return
        retry_after = response.headers.get("Retry-After")
        retry_seconds: Optional[int] = None
        if retry_after and retry_after.isdigit():
            retry_seconds = int(retry_after)
        elif response.headers.get("X-RateLimit-Remaining") == "0":
            reset = response.headers.get("X-RateLimit-Reset", "")
            if reset.isdigit():
                retry_seconds = max(60, int(reset) - int(time.time()))
        raise KnowledgeSyncError(
            "GitHub API 请求受限，请稍后重试",
            retry_after_seconds=retry_seconds,
        )

    def check_latest(self, etag: str = "") -> tuple[Optional[dict], str, bool]:
        url = f"https://api.github.com/repos/{self.repository}/commits"
        headers = self._headers()
        if etag:
            headers["If-None-Match"] = etag
        response = self._get_session().get(
            url,
            params={"sha": self.ref, "path": self.source_path, "per_page": 1},
            headers=headers,
            timeout=(10, 60),
        )
        if response.status_code == 304:
            return None, response.headers.get("ETag", etag), True
        self._raise_for_rate_limit(response)
        payload = response.json()
        if not isinstance(payload, list) or not payload:
            raise KnowledgeSyncError("GitHub 未返回知识库提交")
        item = payload[0]
        sha = str(item.get("sha") or "")
        if len(sha) != 40 or any(ch not in "0123456789abcdef" for ch in sha.lower()):
            raise KnowledgeSyncError("GitHub 返回的提交 SHA 无效")
        commit = item.get("commit") or {}
        committer = commit.get("committer") or {}
        return (
            {
                "sha": sha,
                "date": str(committer.get("date") or ""),
                "message": str(commit.get("message") or "").splitlines()[0][:200],
            },
            response.headers.get("ETag", ""),
            False,
        )

    def download_archive(
        self,
        source_sha: str,
        destination: Path,
        progress: Optional[Callable[[int, int], None]] = None,
    ) -> str:
        url = f"https://api.github.com/repos/{self.repository}/tarball/{source_sha}"
        response = self._get_session().get(
            url,
            headers=self._headers(),
            timeout=(10, 120),
            stream=True,
            allow_redirects=True,
        )
        self._raise_for_rate_limit(response)
        expected = int(response.headers.get("Content-Length") or 0)
        if expected > MAX_ARCHIVE_BYTES:
            raise KnowledgeSyncError("知识库压缩包超过 50 MB 安全限制")
        received = 0
        digest = hashlib.sha256()
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                received += len(chunk)
                if received > MAX_ARCHIVE_BYTES:
                    raise KnowledgeSyncError("知识库压缩包超过 50 MB 安全限制")
                digest.update(chunk)
                handle.write(chunk)
                if progress:
                    progress(received, expected)
            handle.flush()
            os.fsync(handle.fileno())
        return digest.hexdigest()


def safe_extract_markdown(
    archive_path: Path, destination: Path, source_path: str
) -> tuple[int, int]:
    """Extract only regular Markdown files from the configured subtree."""
    source_parts = PurePosixPath(source_path.strip("/")).parts
    destination.mkdir(parents=True, exist_ok=True)
    file_count = 0
    total_size = 0
    try:
        archive = tarfile.open(archive_path, mode="r:gz")
    except (tarfile.TarError, OSError) as exc:
        raise KnowledgeSyncError(f"知识库压缩包无效：{exc}") from exc

    with archive:
        archive_file_count = 0
        extracted_paths: set[PurePosixPath] = set()
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise KnowledgeSyncError("知识库压缩包包含非法路径")
            if not member.isdir():
                archive_file_count += 1
                if archive_file_count > MAX_ARCHIVE_FILES:
                    raise KnowledgeSyncError("知识库文件数量超过 1000 个安全限制")
            parts = path.parts
            # GitHub tarball 固定为 <repo-root>/<configured-subtree>/...
            subtree_index = 1 + len(source_parts)
            if tuple(parts[1:subtree_index]) != source_parts:
                continue
            relative_parts = parts[subtree_index:]
            if not relative_parts or member.isdir():
                continue
            if not member.isfile():
                raise KnowledgeSyncError("知识库目录包含不允许的链接或设备文件")
            relative = PurePosixPath(*relative_parts)
            if relative.suffix.lower() != ".md":
                continue
            if relative in extracted_paths:
                raise KnowledgeSyncError(f"知识库压缩包包含重复路径：{relative}")
            extracted_paths.add(relative)
            file_count += 1
            total_size += int(member.size)
            if file_count > MAX_ARCHIVE_FILES:
                raise KnowledgeSyncError("知识库文件数量超过 1000 个安全限制")
            if total_size > MAX_EXTRACTED_BYTES:
                raise KnowledgeSyncError("知识库解压内容超过 100 MB 安全限制")
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise KnowledgeSyncError(f"无法读取知识库文件：{relative}")
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
    if file_count == 0:
        raise KnowledgeSyncError("知识库压缩包中没有找到 Markdown 文件")
    return file_count, total_size


class KnowledgeSyncService:
    def __init__(
        self,
        manager: Optional[KnowledgeSnapshotManager] = None,
        client_factory: Callable[[], GitHubKnowledgeClient] = GitHubKnowledgeClient,
    ) -> None:
        self.manager = manager or snapshot_manager
        self.client_factory = client_factory
        self._state_lock = threading.RLock()
        self._run_lock = threading.Lock()
        self._task_lock = threading.Lock()
        self._job: Optional[asyncio.Task] = None
        self._loop_task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._cancel_event = threading.Event()

    def _default_state(self) -> dict:
        return {
            "schema_version": 1,
            "phase": "idle",
            "progress": {"completed": 0, "total": 0},
            "latest_source_sha": "",
            "latest_source_date": "",
            "etag": "",
            "last_checked_at": None,
            "last_success_at": None,
            "next_check_at": None,
            "last_error": "",
            "consecutive_failures": 0,
        }

    def _read_state(self) -> dict:
        try:
            payload = json.loads(self.manager.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            payload = {}
        state = self._default_state()
        if isinstance(payload, dict):
            state.update(payload)
        return state

    def _write_state(self, state: dict) -> None:
        with self._state_lock:
            atomic_write_json(self.manager.state_path, state)

    def _update_state(self, **updates) -> dict:
        with self._state_lock:
            state = self._read_state()
            state.update(updates)
            self._write_state(state)
            return state

    def _set_phase(
        self, phase: str, *, completed: int = 0, total: int = 0, **updates
    ) -> None:
        self._update_state(
            phase=phase,
            progress={"completed": int(completed), "total": int(total)},
            **updates,
        )

    @staticmethod
    def _question_count(snapshot: KnowledgeSnapshot) -> int:
        value = snapshot.manifest.get("question_count")
        if isinstance(value, int):
            return value
        try:
            with sqlite3.connect(str(snapshot.db_path)) as conn:
                row = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()
            return int(row[0]) if row else 0
        except (OSError, sqlite3.Error):
            return 0

    def _version_payload(self, snapshot: KnowledgeSnapshot) -> dict:
        manifest = snapshot.manifest
        source = manifest.get("source", {})
        embedding = manifest.get("embedding", {})
        return {
            "snapshot_id": snapshot.snapshot_id,
            "release_id": manifest.get("release_id", snapshot.snapshot_id),
            "bundled": snapshot.bundled,
            "source_sha": source.get("commit_sha", ""),
            "source_date": source.get("commit_date", ""),
            "built_at": manifest.get("built_at"),
            "question_count": self._question_count(snapshot),
            "dimension_count": int(manifest.get("dimension_count") or 0),
            "embedding_model": embedding.get("model", ""),
            "embedding_dimension": int(embedding.get("dimension") or 0),
        }

    def status(self) -> dict:
        state = self._read_state()
        current = self.manager.resolve()
        pointer = self.manager.read_pointer()
        current_sha = str(current.manifest.get("source", {}).get("commit_sha") or "")
        latest_sha = str(state.get("latest_source_sha") or "")
        suppressed = str(pointer.get("suppressed_sha") or "")
        return {
            "enabled": self._enabled(),
            "phase": state.get("phase", "idle"),
            "progress": state.get("progress", {"completed": 0, "total": 0}),
            "current": self._version_payload(current),
            "latest_source_sha": latest_sha,
            "latest_source_date": state.get("latest_source_date") or "",
            "update_available": bool(
                latest_sha and latest_sha != current_sha and latest_sha != suppressed
            ),
            "last_checked_at": state.get("last_checked_at"),
            "last_success_at": state.get("last_success_at"),
            "next_check_at": state.get("next_check_at"),
            "last_error": state.get("last_error") or "",
            "can_rollback": bool(pointer.get("history")),
            "suppressed_sha": suppressed,
            "interval_seconds": self._interval_seconds(),
            "source_repository": self._source_repository(),
            "source_ref": self._source_ref(),
            "source_path": self._source_path(),
        }

    @staticmethod
    def _enabled() -> bool:
        from app.core.config import settings

        return bool(settings.KNOWLEDGE_SYNC_ENABLED)

    @staticmethod
    def _interval_seconds() -> int:
        from app.core.config import settings

        return max(300, int(settings.KNOWLEDGE_SYNC_INTERVAL_SECONDS))

    @staticmethod
    def _source_repository() -> str:
        from app.core.config import settings

        return settings.KNOWLEDGE_SOURCE_REPOSITORY

    @staticmethod
    def _source_ref() -> str:
        from app.core.config import settings

        return settings.KNOWLEDGE_SOURCE_REF

    @staticmethod
    def _source_path() -> str:
        from app.core.config import settings

        return settings.KNOWLEDGE_SOURCE_PATH

    def is_busy(self) -> bool:
        with self._task_lock:
            return self._job is not None and not self._job.done()

    async def start_sync(self, *, force: bool = False, automatic: bool = False) -> dict:
        if not self._enabled() and automatic:
            return self.status()
        with self._task_lock:
            if self._job is not None and not self._job.done():
                return self.status()
            self.manager.ensure_runtime_dirs()
            self._cancel_event.clear()
            self._set_phase("checking", last_error="")
            self._job = asyncio.create_task(
                asyncio.to_thread(self._run_sync, force, automatic),
                name="knowledge-sync",
            )
        return self.status()

    def _success_state(self, **updates) -> None:
        next_check = _utcnow() + timedelta(seconds=self._interval_seconds())
        self._set_phase(
            "idle",
            last_error="",
            consecutive_failures=0,
            next_check_at=_iso(next_check),
            **updates,
        )

    def _failure_state(self, exc: Exception) -> None:
        state = self._read_state()
        failures = int(state.get("consecutive_failures") or 0) + 1
        backoffs = [15 * 60, 60 * 60, 6 * 60 * 60]
        retry = backoffs[min(failures - 1, len(backoffs) - 1)]
        if isinstance(exc, KnowledgeSyncError) and exc.retry_after_seconds:
            retry = max(retry, exc.retry_after_seconds)
        self._set_phase(
            "failed",
            last_error=str(exc)[:500],
            consecutive_failures=failures,
            next_check_at=_iso(_utcnow() + timedelta(seconds=retry)),
        )

    def _cleanup_staging(self) -> None:
        if not self.manager.staging_dir.is_dir():
            return
        for child in self.manager.staging_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except FileNotFoundError:
                    pass

    def _ensure_running(self) -> None:
        if self._cancel_event.is_set():
            raise _KnowledgeSyncCancelled("知识库更新因应用关闭而中断")

    def _validate_questions(
        self,
        questions: list[InterviewQuestion],
        warnings: list,
        previous_count: int,
    ) -> None:
        if len(questions) < MIN_QUESTION_COUNT:
            raise KnowledgeSyncError(
                f"解析题目数过少：{len(questions)}，最低要求 {MIN_QUESTION_COUNT}"
            )
        ids = [question.id for question in questions]
        if len(ids) != len(set(ids)):
            raise KnowledgeSyncError("知识库存在重复题目 ID")
        for question in questions:
            if not (
                question.id
                and question.dimension
                and question.question.strip()
                and question.source_file
            ):
                raise KnowledgeSyncError(f"题目关键字段缺失：{question.source_file}")
        max_warnings = max(5.0, len(questions) * 0.01)
        if len(warnings) > max_warnings:
            raise KnowledgeSyncError(
                f"解析警告过多：{len(warnings)}，允许最多 {max_warnings:g}"
            )
        if previous_count >= MIN_QUESTION_COUNT and len(questions) < previous_count * 0.8:
            raise KnowledgeSyncError(
                f"题目数从 {previous_count} 降至 {len(questions)}，超过 20% 安全阈值"
            )

    def _build_embeddings(
        self,
        questions: list[InterviewQuestion],
        hashes: dict,
        fingerprint: str,
    ) -> tuple[dict, int, int, object]:
        from app.core.embedding_client import Qwen3EmbeddingClient

        client = Qwen3EmbeddingClient()
        active = self.manager.resolve()
        previous_manifest = active.manifest
        previous_hashes = previous_manifest.get("question_hashes", {})
        may_reuse = (
            previous_manifest.get("embedding", {}).get("fingerprint") == fingerprint
        )
        old_vectors: dict = {}
        if may_reuse and active.db_path.is_file():
            repo = KnowledgeRepository(str(active.db_path))
            try:
                old_vectors = {
                    row["id"]: row["embedding"] for row in repo.list_with_embedding()
                }
            finally:
                repo.close()

        embeddings: dict = {}
        changed: list[InterviewQuestion] = []
        for question in questions:
            old_hash = previous_hashes.get(question.id, {})
            vector = old_vectors.get(question.id)
            if (
                may_reuse
                and old_hash.get("embedding_hash")
                == hashes[question.id]["embedding_hash"]
                and isinstance(vector, list)
                and len(vector) == client.dim
                and all(math.isfinite(float(value)) for value in vector)
            ):
                embeddings[question.id] = vector
            else:
                changed.append(question)

        total = len(changed)
        completed = 0
        self._set_phase("embedding", completed=0, total=total)
        indexer = KnowledgeIndexer(client=client, batch_size=32)
        for start in range(0, total, indexer.batch_size):
            self._ensure_running()
            batch_questions = changed[start : start + indexer.batch_size]
            texts = [build_embedding_text(question) for question in batch_questions]
            vectors = client.embed(texts)
            if len(vectors) != len(batch_questions):
                raise KnowledgeSyncError("Embedding 服务返回的向量数量不匹配")
            for question, vector in zip(batch_questions, vectors):
                if len(vector) != client.dim or not all(
                    math.isfinite(float(value)) for value in vector
                ):
                    raise KnowledgeSyncError(
                        f"题目 {question.id} 的 Embedding 维度或数值无效"
                    )
                embeddings[question.id] = vector
            completed += len(batch_questions)
            self._set_phase("embedding", completed=completed, total=total)
        return embeddings, len(questions) - total, total, client

    @staticmethod
    def _sample_questions(questions: list[InterviewQuestion], count: int = 10) -> list:
        ordered = sorted(questions, key=lambda item: item.id)
        if len(ordered) <= count:
            return ordered
        return [ordered[(index * len(ordered)) // count] for index in range(count)]

    def _validate_database(
        self,
        db_path: Path,
        questions: list[InterviewQuestion],
        client,
    ) -> dict:
        repo = KnowledgeRepository(str(db_path))
        try:
            quick = repo.conn.execute("PRAGMA quick_check").fetchone()
            if not quick or quick[0] != "ok":
                raise KnowledgeSyncError("SQLite quick_check 未通过")
            count = repo.count()
            with_embedding = repo.count_with_embedding()
            fts_count = int(
                repo.conn.execute("SELECT COUNT(*) FROM knowledge_fts").fetchone()[0]
            )
            if count != len(questions) or with_embedding != count or fts_count != count:
                raise KnowledgeSyncError(
                    "SQLite 知识表、向量或 FTS 记录数量不一致"
                )

            retriever = KnowledgeRetriever(repository=repo, client=client)
            sample = self._sample_questions(questions)
            hits = 0
            for question in sample:
                self._ensure_running()
                results = retriever.search(question.question, limit=5, threshold=0.0)
                if question.id in {item.question_id for item in results}:
                    hits += 1
            required = min(8, len(sample))
            if hits < required:
                raise KnowledgeSyncError(
                    f"原题检索冒烟测试仅通过 {hits}/{len(sample)}，最低要求 {required}"
                )
            return {
                "quick_check": "ok",
                "fts_count": fts_count,
                "smoke_hits": hits,
                "smoke_total": len(sample),
            }
        finally:
            repo.close()

    def _activate_existing(self, release_id: str, source_sha: str) -> None:
        self._set_phase("activating")
        pointer = self.manager.read_pointer()
        suppressed = pointer.get("suppressed_sha") or ""
        self.manager.activate(
            release_id,
            suppressed_sha="" if suppressed == source_sha else suppressed,
        )
        self.manager.prune_releases()
        self._success_state(last_success_at=_iso())

    def _run_sync(self, force: bool, automatic: bool) -> None:
        from app.core.config import settings

        self._run_lock.acquire()
        lease = _ProcessLease(self.manager.runtime_dir / ".sync.lock")
        stage_dir: Optional[Path] = None
        try:
            if not lease.acquire():
                # 共享的 sync_state.json 由持锁进程继续更新；这不是失败。
                logger.info("Knowledge sync already running in another process")
                return
            self._cleanup_staging()
            self._ensure_running()
            client = self.client_factory()
            state = self._read_state()
            latest, etag, not_modified = client.check_latest(
                "" if force else str(state.get("etag") or "")
            )
            checked_at = _iso()
            if latest is None:
                source_sha = str(state.get("latest_source_sha") or "")
                source_date = str(state.get("latest_source_date") or "")
                if not source_sha:
                    raise KnowledgeSyncError("GitHub 返回 304，但本地没有上游版本记录")
            else:
                source_sha = latest["sha"]
                source_date = latest.get("date", "")
            self._update_state(
                etag=etag,
                latest_source_sha=source_sha,
                latest_source_date=source_date,
                last_checked_at=checked_at,
            )
            self._ensure_running()

            active = self.manager.resolve()
            active_sha = str(active.manifest.get("source", {}).get("commit_sha") or "")
            suppressed = self.manager.read_pointer().get("suppressed_sha") or ""
            if source_sha == active_sha and not force:
                self._success_state()
                return
            if source_sha == suppressed and not force:
                self._success_state()
                return

            fingerprint = embedding_fingerprint(
                settings.KNOWLEDGE_EMBEDDING_MODEL,
                settings.KNOWLEDGE_EMBEDDING_DIM,
            )
            existing = self.manager.find_release(source_sha, fingerprint)
            if existing:
                self._activate_existing(existing, source_sha)
                return

            stage_dir = self.manager.staging_dir / uuid.uuid4().hex
            source_dir = stage_dir / "source"
            archive_path = stage_dir / "source.tar.gz"
            stage_dir.mkdir(parents=True, exist_ok=False)
            self._set_phase("downloading")

            def download_progress(completed: int, total: int) -> None:
                self._ensure_running()
                self._set_phase(
                    "downloading", completed=completed, total=total or completed
                )

            archive_sha256 = client.download_archive(
                source_sha, archive_path, progress=download_progress
            )
            safe_extract_markdown(archive_path, source_dir, client.source_path)
            archive_path.unlink(missing_ok=True)
            self._ensure_running()

            self._set_phase("parsing")
            questions, warnings = parse_knowledge_dir(str(source_dir))
            previous_count = int(active.manifest.get("question_count") or 0)
            self._validate_questions(questions, warnings, previous_count)
            hashes = {question.id: question_hashes(question) for question in questions}

            embeddings, reused, generated, embedding_client = self._build_embeddings(
                questions, hashes, fingerprint
            )
            db_path = stage_dir / "knowledge.db"
            repo = KnowledgeRepository(str(db_path))
            try:
                repo.replace_all(questions, embeddings)
            finally:
                repo.close()

            self._set_phase("validating")
            quality = self._validate_database(db_path, questions, embedding_client)
            self._ensure_running()
            built_at = _iso()
            release_id = (
                f"{source_sha[:12]}-{fingerprint[:12]}-v{PIPELINE_VERSION}"
            )
            manifest = {
                "schema_version": 1,
                "build_version": 1,
                "release_id": release_id,
                "source": {
                    "repository": client.repository,
                    "ref": client.ref,
                    "path": client.source_path,
                    "commit_sha": source_sha,
                    "commit_date": source_date,
                    "archive_sha256": archive_sha256,
                },
                "built_at": built_at,
                "question_count": len(questions),
                "dimension_count": len({question.dimension for question in questions}),
                "parse_warning_count": len(warnings),
                "embedding": {
                    "model": settings.KNOWLEDGE_EMBEDDING_MODEL,
                    "dimension": settings.KNOWLEDGE_EMBEDDING_DIM,
                    "pipeline_version": PIPELINE_VERSION,
                    "fingerprint": fingerprint,
                    "reused": reused,
                    "generated": generated,
                },
                "question_hashes": hashes,
                "database_sha256": sha256_file(db_path),
                "quality": quality,
            }
            atomic_write_json(stage_dir / "manifest.json", manifest)
            _fsync_tree(stage_dir)

            final_dir = self.manager.releases_dir / release_id
            self._set_phase("activating")
            if final_dir.exists():
                shutil.rmtree(stage_dir, ignore_errors=True)
                stage_dir = None
            else:
                os.replace(stage_dir, final_dir)
                _fsync_directory(self.manager.releases_dir)
                stage_dir = None
            self.manager.activate(release_id, suppressed_sha="")
            self.manager.prune_releases()
            self._success_state(last_success_at=built_at)
            logger.info(
                "Knowledge sync activated %s (%s questions, %s reused, %s embedded)",
                source_sha[:12],
                len(questions),
                reused,
                generated,
            )
        except _KnowledgeSyncCancelled as exc:
            logger.info("Knowledge sync cancelled before activation")
            self._set_phase(
                "idle",
                last_error=str(exc),
                next_check_at=_iso(_utcnow()),
            )
        except Exception as exc:  # noqa: BLE001 - preserve the active snapshot
            logger.warning("Knowledge sync failed; keeping active snapshot: %s", exc)
            self._failure_state(exc)
        finally:
            if stage_dir is not None:
                shutil.rmtree(stage_dir, ignore_errors=True)
            lease.release()
            self._run_lock.release()

    def rollback(self) -> dict:
        if self.is_busy() or not self._run_lock.acquire(blocking=False):
            raise RuntimeError("知识库正在更新，暂时无法回滚")
        lease = _ProcessLease(self.manager.runtime_dir / ".sync.lock")
        try:
            if not lease.acquire():
                raise RuntimeError("另一个进程正在更新知识库")
            reverted, target = self.manager.rollback()
            self._update_state(
                phase="idle",
                progress={"completed": 0, "total": 0},
                last_error="",
                last_success_at=_iso(),
                next_check_at=_iso(_utcnow() + timedelta(seconds=self._interval_seconds())),
            )
            logger.info(
                "Knowledge snapshot rolled back from %s to %s",
                reverted.snapshot_id,
                target.snapshot_id,
            )
            return self.status()
        finally:
            lease.release()
            self._run_lock.release()

    def _is_due(self) -> bool:
        state = self._read_state()
        next_check = _parse_datetime(state.get("next_check_at"))
        if next_check:
            return _utcnow() >= next_check
        last_checked = _parse_datetime(state.get("last_checked_at"))
        return not last_checked or (
            _utcnow() - last_checked
        ).total_seconds() >= self._interval_seconds()

    async def _background_loop(self) -> None:
        assert self._stop_event is not None
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=10)
            return
        except asyncio.TimeoutError:
            pass
        while not self._stop_event.is_set():
            if self._enabled() and self._is_due() and not self.is_busy():
                await self.start_sync(automatic=True)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                continue

    def start_background(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        state = self._read_state()
        if state.get("phase") in BUSY_PHASES:
            # 上次进程在发布完成前退出。原子指针仍指向旧版，
            # 将检查立即设为到期，启动 10 秒后清理 staging 并重试。
            self._set_phase(
                "failed",
                last_error="上次知识库更新被中断，将自动重试",
                next_check_at=_iso(_utcnow()),
            )
        self._cancel_event.clear()
        self._stop_event = asyncio.Event()
        self._loop_task = asyncio.create_task(
            self._background_loop(), name="knowledge-sync-scheduler"
        )

    async def stop_background(self) -> None:
        self._cancel_event.set()
        if self._stop_event:
            self._stop_event.set()
        if self._loop_task:
            try:
                await asyncio.wait_for(self._loop_task, timeout=2)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._loop_task.cancel()
        job = self._job
        if job and not job.done():
            try:
                await asyncio.wait_for(asyncio.shield(job), timeout=30)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass


knowledge_sync_service = KnowledgeSyncService()
