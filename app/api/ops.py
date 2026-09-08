"""Ops snapshots — service-key only (never a browser JWT)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.security import require_service_key_only
from app.core.tokens import QuePrincipal
from app.obs.metrics import snapshot

router = APIRouter(prefix="/v1/ops", tags=["ops"])

Principal = Annotated[QuePrincipal, Depends(require_service_key_only)]


@router.get("/metrics")
async def ops_metrics(_principal: Principal) -> dict:
    """In-process P50/P95/P99, cost, and alert windows. No Grafana."""
    return snapshot()
