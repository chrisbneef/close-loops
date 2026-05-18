from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import gamification, ingest, now, oauth, reports, schedule, users
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

# CORS — the Expo web/dev target serves from a different origin (typically
# http://localhost:8081 or an exp:// URL), so the browser blocks API calls
# without these headers. Wide-open for dev; tighten for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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
