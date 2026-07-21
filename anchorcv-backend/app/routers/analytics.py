import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.deps.auth import get_current_user

router = APIRouter(prefix="/analytics", tags=["analytics"])
logger = logging.getLogger(__name__)

VALID_EVENTS = {
    "canvas_flow_started",
    "canvas_step_completed",
    "canvas_step_abandoned",
    "canvas_flow_completed",
    "canvas_error_shown",
}


class CanvasEventIn(BaseModel):
    event_name: str
    timestamp: datetime | None = None
    payload: Dict[str, Any] = Field(default_factory=dict)


@router.post("/canvas-event")
def ingest_canvas_event(
    event: CanvasEventIn,
    user: dict = Depends(get_current_user),
):
    if event.event_name not in VALID_EVENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported analytics event.",
        )

    record = {
        "event_name": event.event_name,
        "timestamp": (event.timestamp or datetime.now(timezone.utc)).isoformat(),
        "user_id": user.get("id"),
        "payload": event.payload,
    }
    logger.info("canvas_analytics %s", json.dumps(record, ensure_ascii=True))
    return {"ok": True}
