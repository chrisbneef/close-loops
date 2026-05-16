from fastapi import FastAPI

app = FastAPI(title="Cadence Brain", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "cadence-brain"}
