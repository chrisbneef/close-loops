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
│   │   ├── schemas.py        # Pydantic v2 — LLM output + API I/O
│   │   ├── main.py           # FastAPI app, mounts routers
│   │   ├── routers/
│   │   │   └── ingest.py     # POST /ingest
│   │   └── services/
│   │       ├── llm.py        # Anthropic wrapper (messages.parse + cached system prompt)
│   │       ├── decomposition.py  # ingest pipeline orchestrator
│   │       ├── cycles.py     # DAG cycle prevention
│   │       ├── temporal.py   # est_minutes correction factor
│   │       └── reschedule.py # Phase 3 stub
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/0001_initial_schema.py
│   ├── tests/                # 25 pytest cases (cycles, temporal, ingest pipeline, router)
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

# Seed at least one cofounder so /ingest can resolve a default owner:
python -c "from app.db import SessionLocal; from app.models import User; s=SessionLocal(); s.add_all([User(name='Michael', role='cofounder'), User(name='Chris', role='cofounder')]); s.commit()"

uvicorn app.main:app --reload --port 8000
curl http://localhost:8000/health
curl -X POST http://localhost:8000/ingest -H 'Content-Type: application/json' \
  -d '{"raw_goal":"Get the Q3 webinar live and follow up the warm leads"}'

# Tests:
PYTHONPATH=. pytest tests/
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
- **LLM model + thinking knobs (Phase 2):** `claude-opus-4-7` with adaptive thinking and
  `effort: "high"`. Configurable in [backend/app/services/llm.py](backend/app/services/llm.py).
  Decomposition is intelligence-sensitive (ranking importance, estimating effort, mapping
  deps); per the claude-api skill, Opus 4.7 + `high` is the right minimum. Drop to Sonnet
  4.6 if cost becomes an issue at higher call volumes.
- **`messages.parse()` over manual JSON parsing.** The Anthropic SDK validates Pydantic
  schemas server-side — no need for the spec's "try/except, strip fences, re-prompt once"
  loop. If a future schema violation happens, it surfaces as `pydantic.ValidationError`
  bubbled up to the router and returned as a 502.
- **SQLite drops tzinfo on `DateTime(timezone=True)` reads** even though Pydantic /
  SQLAlchemy stored it correctly. Postgres reads preserve tz. Tests use a `_as_utc()`
  helper that normalizes both. For Phase 3, the scheduler should normalize at read time
  too (either via a SQLAlchemy `TypeDecorator` that always returns UTC-aware, or a
  small `_as_utc()` shim at the boundary). Don't compare naive vs aware datetimes
  directly — Python will raise `TypeError`.

## Phase status
- [x] Phase 0 — env setup
- [x] Phase 1 — data schema (SQLAlchemy models + Alembic initial migration; verified
      on SQLite)
- [x] Phase 2 — LLM decomposition + estimation (`POST /ingest`):
      `claude-opus-4-7` via `messages.parse()` with Pydantic-typed output (no JSON
      string parsing). Adaptive thinking + `effort: "high"`. System prompt has
      `cache_control: ephemeral` (caches once prefix exceeds ~4096 tokens on Opus 4.7;
      currently ~3000 tokens after Phase 2.1 — adding 1–2 more few-shots would cross
      the threshold). Pipeline: cycle-safe DAG ingest → temporal correction
      (mean(actual/estimated) clamped 0.5–3.0; falls back to 1.0 under 3 samples) →
      owner routing (self/partner/contractor) → persistence → reschedule stub. Verified
      end-to-end against live Opus 4.7 on a fresh goal — 14 tasks, 14 edges, 0 dropped,
      clean DAG, smart owner routing (Chris → web, Michael → strategy, contractor → video edit).
- [x] Phase 2.1 — deadline extraction. `LLMDecomposition.goal_deadline: Optional[datetime]`
      added; prompt instructs Claude to interpret "by June 1" / "end of month" / "Q3"
      using the requester's timezone (passed in user-message context along with today's
      date). Pipeline normalizes naive datetimes to UTC and applies the deadline uniformly
      to every task in the decomposition. Per-task deadline overrides are deliberately
      out of scope — the Phase 3 scheduler will derive finer-grained per-task effective
      deadlines from the DAG. 28 pytest cases pass.
- [ ] Phase 3 — scheduling engine (priority math + greedy packing + APScheduler loop)
- [ ] Phase 4 — Google Calendar via MCP
- [ ] Phase 5 — Now-screen vertical slice (bootstrap Expo here)
- [ ] Phase 6 — reminders + gamification
- [ ] Phase 7 — daily closed-loop briefing + body doubling
