from fastapi import FastAPI

from app.routers import ingest

app = FastAPI(title="Cadence Brain", version="0.2.0")
app.include_router(ingest.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "cadence-brain"}
