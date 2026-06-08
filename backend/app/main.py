from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import (
    auth, briefing, day, gamification, ingest, now, oauth, presence, reports,
    schedule, slack, subtasks, tasks, timing, users,
)
from app.security import get_current_user
from app.services import reminder_loop, scheduler_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler_loop.start()
    reminder_loop.start()
    try:
        yield
    finally:
        reminder_loop.stop()
        scheduler_loop.stop()


app = FastAPI(title="Cadence Brain", version="0.5.0", lifespan=lifespan)

# CORS — the Expo web/dashboard/widget surfaces serve from a different origin
# (dev: http://localhost:8081; the Tauri widget: tauri://localhost; prod: the
# deployed web origin). Configurable via CORS_ALLOW_ORIGINS (comma-separated);
# defaults to "*" for dev. Credentials are only allowed when origins are
# explicitly listed — the CORS spec forbids "*" + credentials together.
_cors_origins = settings.cors_origins_list
_allow_all = _cors_origins == ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=not _allow_all,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Public routers — no user token required:
#   auth   — issues the token in the first place
#   oauth  — browser redirect flow, authenticated by the HMAC-signed state
#   slack  — inbound slash command, verified by the Slack signing secret
app.include_router(auth.router)
app.include_router(oauth.router)
app.include_router(slack.router)

# Protected routers — require a valid session token (Depends(get_current_user)).
# The dependency gates access for the whole two-person team; handlers still take
# owner_id where the shared board / partner features need it.
_auth = [Depends(get_current_user)]
app.include_router(ingest.router, dependencies=_auth)
app.include_router(schedule.router, dependencies=_auth)
app.include_router(now.router, dependencies=_auth)
app.include_router(reports.router, dependencies=_auth)
app.include_router(gamification.router, dependencies=_auth)
app.include_router(users.router, dependencies=_auth)
app.include_router(briefing.router, dependencies=_auth)
app.include_router(presence.router, dependencies=_auth)
app.include_router(subtasks.router, dependencies=_auth)
app.include_router(tasks.router, dependencies=_auth)
app.include_router(timing.router, dependencies=_auth)
app.include_router(day.router, dependencies=_auth)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "cadence-brain"}


@app.post("/admin/tick", dependencies=[Depends(get_current_user)])
def admin_tick() -> dict[str, object]:
    """Force a scheduler tick on demand. Useful in dev for testing without
    waiting on the APScheduler interval."""
    from app.db import SessionLocal
    from app.services import scheduler_tick

    session = SessionLocal()
    try:
        counts = scheduler_tick.tick(session)
        return {"counts": counts}
    finally:
        session.close()
