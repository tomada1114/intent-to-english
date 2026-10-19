"""The selected process mode, without credentials or provider configuration."""

from __future__ import annotations

from fastapi import APIRouter

from intent_to_english.api.dependencies import ModelModeDep
from intent_to_english.api.schemas import MetaResponse

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("")
async def get_meta(model_mode: ModelModeDep) -> MetaResponse:
    """Report the mode selected by the application's container."""
    return MetaResponse(model_mode=model_mode)
