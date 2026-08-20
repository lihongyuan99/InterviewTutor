from fastapi import APIRouter, HTTPException

from app.core.llm_settings import (
    LLMSettings,
    load_llm_settings,
    public_settings,
    save_llm_settings,
)
from app.core.cache import generation_cache


router = APIRouter()


@router.get("/settings/llm")
async def get_llm_settings():
    try:
        return public_settings(load_llm_settings())
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/settings/llm")
async def update_llm_settings(payload: LLMSettings):
    try:
        saved = save_llm_settings(payload)
        generation_cache.clear()
        return public_settings(saved)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
