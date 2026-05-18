from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routers import ingest, oauth, schedule
from app.services import scheduler_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler_loop.start()
    try:
        yield
    finally:
        scheduler_loop.stop()


app = FastAPI(title="Cadence Brain", version="0.4.0", lifespan=lifespan)
app.include_router(ingest.router)
app.include_router(schedule.router)
app.include_router(oauth.router)


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
