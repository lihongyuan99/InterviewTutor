"""Dynamic knowledge synchronization API."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.knowledge.repository import KnowledgeRepository
from app.knowledge.sync import knowledge_sync_service


router = APIRouter()


class KnowledgeSyncRequest(BaseModel):
    force: bool = False


@router.get("/dimensions")
async def list_dimensions():
    """Return the training dimensions available in the current knowledge snapshot.

    Derived dynamically from the activated snapshot so that targeted practice
    always reflects the latest knowledge base content after an update.
    """

    def _load():
        repo = KnowledgeRepository()
        try:
            return repo.list_dimensions()
        finally:
            repo.close()

    return await asyncio.to_thread(_load)


@router.get("/status")
async def get_knowledge_status():
    """Return cached local status without contacting GitHub."""
    return await asyncio.to_thread(knowledge_sync_service.status)


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync_knowledge(request: KnowledgeSyncRequest):
    """Start an idempotent background check/build/activation job."""
    return await knowledge_sync_service.start_sync(force=request.force)


@router.post("/rollback")
async def rollback_knowledge():
    try:
        return await asyncio.to_thread(knowledge_sync_service.rollback)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
