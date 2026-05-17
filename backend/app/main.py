from fastapi import FastAPI

from app.routers import ingest, schedule

app = FastAPI(title="Cadence Brain", version="0.3.0")
app.include_router(ingest.router)
app.include_router(schedule.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "cadence-brain"}
