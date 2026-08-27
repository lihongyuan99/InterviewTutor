from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import interview as interview_api
from app.api import knowledge as knowledge_api
from app.knowledge.snapshot import KnowledgeSnapshotManager, atomic_write_json


def test_knowledge_sync_api_is_accepted_and_idempotent(monkeypatch):
    calls = []

    async def start_sync(*, force=False, automatic=False):
        calls.append(force)
        return {"phase": "checking", "progress": {"completed": 0, "total": 0}}

    monkeypatch.setattr(knowledge_api.knowledge_sync_service, "start_sync", start_sync)
    app = FastAPI()
    app.include_router(knowledge_api.router, prefix="/knowledge")

    with TestClient(app) as client:
        first = client.post("/knowledge/sync", json={"force": False})
        second = client.post("/knowledge/sync", json={"force": False})

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["phase"] == "checking"
    assert calls == [False, False]


def test_knowledge_status_is_a_local_read(monkeypatch):
    expected = {
        "phase": "idle",
        "current": {"question_count": 592},
        "source_repository": "ranxi2001/zero2Agent",
    }
    monkeypatch.setattr(
        knowledge_api.knowledge_sync_service,
        "status",
        lambda: expected,
    )
    app = FastAPI()
    app.include_router(knowledge_api.router, prefix="/knowledge")

    with TestClient(app) as client:
        response = client.get("/knowledge/status")

    assert response.status_code == 200
    assert response.json() == expected


def test_rollback_conflict_returns_409(monkeypatch):
    def conflict():
        raise RuntimeError("没有可回滚的知识库版本")

    monkeypatch.setattr(knowledge_api.knowledge_sync_service, "rollback", conflict)
    app = FastAPI()
    app.include_router(knowledge_api.router, prefix="/knowledge")

    with TestClient(app) as client:
        response = client.post("/knowledge/rollback")

    assert response.status_code == 409
    assert "没有可回滚" in response.json()["detail"]


def test_source_endpoint_reads_the_requested_snapshot_only(tmp_path, monkeypatch):
    bundled_source = tmp_path / "bundled-source"
    bundled_file = bundled_source / "01-architecture-design" / "index.md"
    bundled_file.parent.mkdir(parents=True)
    bundled_file.write_text("### Q：内置题\n\n内置内容", encoding="utf-8")
    bundled_manifest = tmp_path / "bundled-manifest.json"
    bundled_manifest.write_text(json.dumps({"release_id": "bundled"}), encoding="utf-8")

    manager = KnowledgeSnapshotManager(
        runtime_dir=tmp_path / "runtime",
        bundled_db_path=tmp_path / "bundled.db",
        bundled_source_dir=bundled_source,
        bundled_manifest_path=bundled_manifest,
    )
    release = manager.releases_dir / "release-one"
    release_file = release / "source" / "01-architecture-design" / "index.md"
    release_file.parent.mkdir(parents=True)
    release_file.write_text("### Q：新版题\n\n新版内容", encoding="utf-8")
    (release / "knowledge.db").write_bytes(b"db")
    atomic_write_json(
        release / "manifest.json",
        {"release_id": "release-one", "source": {"commit_sha": "1" * 40}},
    )
    manager.activate("release-one")
    monkeypatch.setattr(interview_api, "snapshot_manager", manager)

    app = FastAPI()
    app.include_router(interview_api.router, prefix="/interview")
    params = {"source_file": "01-architecture-design/index.md"}
    with TestClient(app) as client:
        current = client.get("/interview/source", params=params)
        bundled = client.get(
            "/interview/source",
            params={**params, "snapshot_id": "bundled"},
        )
        traversal = client.get(
            "/interview/source",
            params={"source_file": "../secret.md", "snapshot_id": "release-one"},
        )
        missing = client.get(
            "/interview/source",
            params={**params, "snapshot_id": "missing"},
        )

    assert current.status_code == 200
    assert current.json()["snapshot_id"] == "release-one"
    assert "新版内容" in current.json()["content"]
    assert bundled.json()["snapshot_id"] == "bundled"
    assert "内置内容" in bundled.json()["content"]
    assert traversal.status_code == 403
    assert missing.status_code == 404
