from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import (
    briefing, gamification, ingest, now, oauth, presence, reports, schedule,
    slack, subtasks, tasks, users,
)
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

app.include_router(ingest.router)
app.include_router(schedule.router)
app.include_router(oauth.router)
app.include_router(now.router)
app.include_router(reports.router)
app.include_router(gamification.router)
app.include_router(users.router)
app.include_router(briefing.router)
app.include_router(presence.router)
app.include_router(subtasks.router)
app.include_router(tasks.router)
app.include_router(slack.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "cadence-brain"}


@app.post("/admin/tick")
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
