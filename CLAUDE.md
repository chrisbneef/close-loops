# Cadence — Project Constitution

## What this is
An externalized executive-function system for two high-ideation, low-execution
co-founders. It decides what to do, when, and who owns it, and keeps them moving.

## Inviolable principles
1. **Zero-initiation** — open the app → told the one next action, timer running.
2. **The schedule is alive** — reality changes → silent full re-optimization.
3. **Momentum over completion** — reward starting; idle work decays gently, never punitively.
4. The user never plans, sorts, estimates, or reschedules by hand.

## Architecture
Expo/TS mobile ⇄ FastAPI/Python brain ⇄ Postgres (Supabase) ⇄ Google Calendar (MCP).
A continuous APScheduler optimizer recomputes `P(t)` and re-packs the calendar.

## Build order (phase-gated — finish a phase, demo it, commit, then ASK before next)
0. env setup → **1. schema** → 2. LLM decomposition → 3. scheduler → 4. calendar MCP →
5. Now-screen vertical slice → 6. reminders / gamification → 7. closed loop + body doubling.

## Definition of done (per phase)
Demoable end-to-end on a device/simulator with real data, migrations applied, and the
scheduler-math unit tests passing once the scheduler exists.

## Rules
- Read `/mnt/skills/public/frontend-design/SKILL.md` before any UI work. (Currently
  missing on this machine; search again at the start of Phase 5.)
- Verify library / MCP setup against current docs; record deviations here.
- Secrets only in env, never URLs, never committed.
- Scheduler logic must be unit-tested (priority math, greedy packing, dependency order,
  immutable anchors, deadline guard against div-by-zero).

## Repo layout
```
Close-Loops/
├── CLAUDE.md          # this file
├── backend/           # FastAPI + SQLAlchemy + Alembic — "the brain"
│   ├── app/
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── models.py
│   │   └── main.py
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/0001_initial_schema.py
│   ├── alembic.ini
│   ├── requirements.txt
│   └── .env.example
└── cadence/           # Expo / React Native — bootstrapped at start of Phase 5
```

## Local dev quickstart
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # then fill ANTHROPIC_API_KEY, DATABASE_URL (optional)
alembic upgrade head        # creates ./cadence.db (SQLite) if no DATABASE_URL set
uvicorn app.main:app --reload --port 8000
curl http://localhost:8000/health
```

## Deviations from the spec (record as we go)
- **Python 3.14** is the only interpreter available on this machine (spec asked 3.12).
  All dependencies in `requirements.txt` are 3.14-compatible. Note for production: pin
  3.12 if you want to match a Supabase Edge runtime exactly; otherwise 3.14 is fine.
- **Postgres driver:** using `psycopg[binary]` (psycopg3, the modern SQLAlchemy 2.x
  recommendation) rather than the spec's `psycopg2-binary`. Cleaner type handling.
- **Pydantic settings:** `BaseSettings` lives in the separate `pydantic-settings`
  package in Pydantic v2 — listed in `requirements.txt`.
- **Dev database:** defaults to SQLite (`sqlite:///./cadence.db`) when `DATABASE_URL` is
  unset, so the migration runs without a Supabase project. The Postgres-only index op
  on `delegation_graph.materialized_path` (`text_pattern_ops`) is conditionally applied
  in the migration based on dialect.
- **Expo bootstrap deferred to Phase 5.** `create-expo-app` is heavyweight and not load-
  bearing for Phases 1–4 (backend, scheduler, MCP). `cadence/` is an empty placeholder.
  Run the bootstrap in Section 2.3 at the start of Phase 5.
- **`frontend-design` skill not present** at `/mnt/skills/public/frontend-design/`. Find
  it (or install it) before any UI work — see the memory note `reference-frontend-design-skill`.

## Phase status
- [x] Phase 0 — env setup
- [x] Phase 1 — data schema (SQLAlchemy models + Alembic initial migration; verified
      on SQLite)
- [ ] Phase 2 — LLM decomposition + estimation (`POST /ingest`)
- [ ] Phase 3 — scheduling engine (priority math + greedy packing + APScheduler loop)
- [ ] Phase 4 — Google Calendar via MCP
- [ ] Phase 5 — Now-screen vertical slice (bootstrap Expo here)
- [ ] Phase 6 — reminders + gamification
- [ ] Phase 7 — daily closed-loop briefing + body doubling
