"""Presence endpoints for body doubling.

  POST /presence/heartbeat?owner_id=N  body={status, current_task_id?}
    → the user is alive; explicit status update from the client.
  GET  /presence/partner?owner_id=N
    → the OTHER cofounder's effective presence (auto-stale to 'offline'
       if their last heartbeat is older than 5 min).

Start/done already mutate presence indirectly via app/routers/now.py
(status='focusing' on start, 'idle' on done), so this router is mostly for
the app to push idle/offline on background/foreground transitions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import User
from app.services import presence

router = APIRouter(tags=["presence"])


class HeartbeatRequest(BaseModel):
    status: str = Field(..., description=f"One of: {presence.ALL_STATUSES}")
    current_task_id: Optional[int] = None


class PresenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    user_name: str
    status: str
    current_task_id: Optional[int] = None
    current_task_title: Optional[str] = None
    updated_at: Optional[datetime] = None


@router.post("/presence/heartbeat", status_code=204)
def heartbeat(
    body: HeartbeatRequest,
    owner_id: int = Query(...),
    session: Session = Depends(get_session),
) -> None:
    user = session.get(User, owner_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"owner_id={owner_id} does not exist")
    try:
        presence.update_presence(
            session, owner_id, status=body.status, current_task_id=body.current_task_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    session.commit()


@router.get("/presence/partner", response_model=Optional[PresenceOut])
def get_partner_presence(
    owner_id: int = Query(...),
    session: Session = Depends(get_session),
) -> Optional[PresenceOut]:
    """Returns the other cofounder's presence, with current task title
    resolved server-side so the UI doesn't need a second fetch. None if
    no partner exists (solo team) or partner has never been online."""
    if session.get(User, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"owner_id={owner_id} does not exist")
    partner = presence.find_partner(session, owner_id)
    if partner is None:
        return None
    row = presence.get_effective_presence(session, partner.id)
    if row is None:
        return None
    current_task_title = None
    if row.status == "focusing" and row.current_task_id:
        from app.models import Task
        task = session.get(Task, row.current_task_id)
        if task is not None:
            current_task_title = task.title
    return PresenceOut(
        user_id=partner.id,
        user_name=partner.name,
        status=row.status,
        current_task_id=row.current_task_id,
        current_task_title=current_task_title,
        updated_at=row.updated_at,
    )
