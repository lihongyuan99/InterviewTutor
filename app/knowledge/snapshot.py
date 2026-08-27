"""Versioned knowledge snapshots and atomic activation helpers.

The bundled ``knowledge/`` directory and ``data/knowledge.db`` remain the
offline fallback.  Successful remote builds live below
``data/knowledge_runtime/releases`` and are activated by atomically replacing
one small ``current.json`` pointer.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SAFE_RELEASE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_POINTER_VERSION = 1


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def atomic_write_json(path: Path, payload: Any) -> None:
    """Durably write JSON and atomically replace ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    try:
        directory_fd = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _resolve_project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True)
class KnowledgeSnapshot:
    snapshot_id: str
    db_path: Path
    source_dir: Path
    manifest: dict
    bundled: bool = False


class KnowledgeSnapshotManager:
    """Resolve, activate and roll back immutable knowledge releases."""

    def __init__(
        self,
        *,
        runtime_dir: Optional[Path] = None,
        bundled_db_path: Optional[Path] = None,
        bundled_source_dir: Optional[Path] = None,
        bundled_manifest_path: Optional[Path] = None,
    ) -> None:
        from app.core.config import settings

        self.runtime_dir = runtime_dir or _resolve_project_path(
            settings.KNOWLEDGE_SYNC_RUNTIME_DIR
        )
        self.releases_dir = self.runtime_dir / "releases"
        self.staging_dir = self.runtime_dir / ".staging"
        self.current_path = self.runtime_dir / "current.json"
        self.state_path = self.runtime_dir / "sync_state.json"
        self.bundled_db_path = bundled_db_path or _resolve_project_path(
            settings.KNOWLEDGE_DB_PATH
        )
        self.bundled_source_dir = bundled_source_dir or _resolve_project_path(
            os.getenv("KNOWLEDGE_DIR", "knowledge")
        )
        self.bundled_manifest_path = bundled_manifest_path or _resolve_project_path(
            settings.KNOWLEDGE_MANIFEST_PATH
        )
        self._lock = threading.RLock()

    def ensure_runtime_dirs(self) -> None:
        self.releases_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    def read_pointer(self) -> dict:
        pointer = _read_json(self.current_path, {})
        if not isinstance(pointer, dict):
            pointer = {}
        current = str(pointer.get("current_release_id") or "bundled")
        history = [
            str(item)
            for item in pointer.get("history", [])
            if isinstance(item, str) and item and item != current
        ]
        return {
            "schema_version": _POINTER_VERSION,
            "current_release_id": current,
            "history": history[:2],
            "suppressed_sha": str(pointer.get("suppressed_sha") or ""),
            "activated_at": pointer.get("activated_at"),
        }

    def _bundled_snapshot(self) -> KnowledgeSnapshot:
        manifest = _read_json(self.bundled_manifest_path, {})
        if not isinstance(manifest, dict):
            manifest = {}
        manifest.setdefault("release_id", "bundled")
        manifest.setdefault("source", {})
        return KnowledgeSnapshot(
            snapshot_id="bundled",
            db_path=self.bundled_db_path,
            source_dir=self.bundled_source_dir,
            manifest=manifest,
            bundled=True,
        )

    def resolve(self, snapshot_id: Optional[str] = None) -> KnowledgeSnapshot:
        with self._lock:
            requested = snapshot_id or self.read_pointer()["current_release_id"]
            if requested in {"", "bundled", "legacy"}:
                return self._bundled_snapshot()
            if not _SAFE_RELEASE_ID.fullmatch(requested):
                raise FileNotFoundError("知识库快照 ID 无效")
            release_dir = self.releases_dir / requested
            manifest_path = release_dir / "manifest.json"
            db_path = release_dir / "knowledge.db"
            source_dir = release_dir / "source"
            if not (manifest_path.is_file() and db_path.is_file() and source_dir.is_dir()):
                if snapshot_id is None:
                    return self._bundled_snapshot()
                raise FileNotFoundError(f"知识库快照不存在：{requested}")
            manifest = _read_json(manifest_path, {})
            if not isinstance(manifest, dict):
                raise FileNotFoundError(f"知识库快照清单无效：{requested}")
            return KnowledgeSnapshot(
                snapshot_id=requested,
                db_path=db_path,
                source_dir=source_dir,
                manifest=manifest,
            )

    def active_id(self) -> str:
        return self.resolve().snapshot_id

    def activate(self, release_id: str, *, suppressed_sha: str = "") -> dict:
        """Atomically make an already validated release active."""
        with self._lock:
            target = self.resolve(release_id)
            pointer = self.read_pointer()
            previous = pointer["current_release_id"]
            history = list(pointer["history"])
            if previous != release_id:
                history = [previous, *history]
            history = [item for item in history if item != release_id][:2]
            next_pointer = {
                "schema_version": _POINTER_VERSION,
                "current_release_id": target.snapshot_id,
                "history": history,
                "suppressed_sha": suppressed_sha,
                "activated_at": datetime.now(timezone.utc).isoformat(),
            }
            atomic_write_json(self.current_path, next_pointer)
            return next_pointer

    def rollback(self) -> tuple[KnowledgeSnapshot, KnowledgeSnapshot]:
        """Switch to the previous snapshot and suppress the reverted SHA."""
        with self._lock:
            pointer = self.read_pointer()
            history = list(pointer["history"])
            if not history:
                raise RuntimeError("没有可回滚的知识库版本")
            current = self.resolve(pointer["current_release_id"])
            target_id = history.pop(0)
            target = self.resolve(target_id)
            current_sha = str(current.manifest.get("source", {}).get("commit_sha") or "")
            next_pointer = {
                "schema_version": _POINTER_VERSION,
                "current_release_id": target.snapshot_id,
                "history": [current.snapshot_id, *history][:2],
                "suppressed_sha": current_sha,
                "activated_at": datetime.now(timezone.utc).isoformat(),
            }
            atomic_write_json(self.current_path, next_pointer)
            return current, target

    def find_release(self, source_sha: str, embedding_fingerprint: str) -> Optional[str]:
        if not self.releases_dir.is_dir():
            return None
        for manifest_path in self.releases_dir.glob("*/manifest.json"):
            manifest = _read_json(manifest_path, {})
            if not isinstance(manifest, dict):
                continue
            if (
                manifest.get("source", {}).get("commit_sha") == source_sha
                and manifest.get("embedding", {}).get("fingerprint")
                == embedding_fingerprint
            ):
                return manifest_path.parent.name
        return None

    def prune_releases(self) -> None:
        """Keep the active snapshot and at most two rollback candidates."""
        import shutil

        pointer = self.read_pointer()
        keep = {pointer["current_release_id"], *pointer["history"]}
        if not self.releases_dir.is_dir():
            return
        for release_dir in self.releases_dir.iterdir():
            if not release_dir.is_dir() or release_dir.name in keep:
                continue
            if _SAFE_RELEASE_ID.fullmatch(release_dir.name):
                shutil.rmtree(release_dir, ignore_errors=True)


snapshot_manager = KnowledgeSnapshotManager()


def get_active_snapshot() -> KnowledgeSnapshot:
    return snapshot_manager.resolve()
