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
  helper that normalizes both. Phase 3 handles this at every boundary that reads
  `CalendarBlock.start`/`.end` (priority.py, scheduler.py, persistence.py) — a
  TypeDecorator would be cleaner; deferred until we actually run on Postgres in prod.
  Don't compare naive vs aware datetimes directly — Python raises `TypeError`.
- **Sync tick from `/ingest` is intentional.** The user expects new tasks to land on
  the calendar in the same request, not 60s later. The synchronous tick adds maybe
  100-300ms to /ingest latency for two cofounders; if it ever gets slow we can move to
  background-thread or asyncio.create_task. Until then, the simplicity is worth it.
- **Direct Google OAuth, not MCP (Phase 4 architecture pivot).** The spec recommended
  Composio (or the official Google MCP server) as a brokered OAuth path. We chose
  direct Google OAuth instead: shorter data path (you ↔ Google only), no per-call
  vendor cost, no third-party in the consent screen, and an Internal Workspace OAuth
  app skips Google's verification process entirely (no test-user list, no 100-user cap,
  no scary "unverified app" warning). Trade-off: ~5 hrs of OAuth + Calendar API
  integration code vs. ~1 hr for Composio. Worth it for a SaaS-grade architecture from
  day one — if Cadence ever ships externally, the same code switches from Internal to
  External and goes through Google's app verification (sensitive Calendar scopes, no
  third-party security audit needed).
- **PKCE code_verifier travels inside the signed state token.** Google's OAuth flow
  requires PKCE: `/start` generates a `code_verifier`, sends `code_challenge` to
  Google, and `/callback` must present the verifier on token exchange. Since each
  route creates a fresh `Flow` instance, we encode the verifier in the HMAC-signed
  `state` so the callback can recover it. This is safe for a confidential client —
  the client_secret is what really authenticates us; PKCE here is just a Google-
  required protocol step.
- **DATABASE_URL prefix is auto-normalized.** SQLAlchemy 2.x defaults `postgresql://`
  to the psycopg2 driver, which we don't install. `app/config.py` rewrites the prefix
  to `postgresql+psycopg://` (psycopg3) so users can paste Supabase URLs as-is.

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
- [x] Phase 3a — scheduling engine, pure-compute slice (no APScheduler, no persistence):
      [app/services/priority.py](backend/app/services/priority.py) implements the spec's
      full `P(t)` formula with the deadline div-by-zero guard, past-deadline clamp,
      circadian penalty by local hour, and a graceful fallback when the user has no
      energy_curve. [app/services/momentum.py](backend/app/services/momentum.py) counts
      direct dependents per task (transitive reach is a clean upgrade later if needed).
      [app/services/calendar_provider.py](backend/app/services/calendar_provider.py)
      ships `StubCalendarProvider` (9–12 + 13–17 weekdays in the owner's tz, skipping
      already-elapsed time) behind a `CalendarProvider` protocol — Phase 4's Google
      Calendar MCP plugs in here without packer changes. [app/services/packer.py](backend/app/services/packer.py)
      does **topological-by-readiness, priority-tiebreaking** packing (a higher-priority
      dependent never loses its slot because its prereqs weren't seen first), respects
      immutable anchors (fragmenting slots around them), enforces a daily-capacity cap,
      and surfaces unscheduled task IDs. `GET /schedule/{owner_id}` returns the proposed
      schedule. 60 pytest cases pass (32 new). Demoed live against the 28-task DB seeded
      by two prior `/ingest` calls — 17 of Michael's 22 tasks packed cleanly with correct
      DAG ordering and priority ranking.

      **Known limitation for Phase 3b:** cross-owner dependencies don't resolve in the
      pure-compute slice. Chris's tasks correctly identify "prereq=Michael's task X" but
      have no way to see Michael's schedule until we persist to `calendar_blocks`. In
      Phase 3b, after each scheduler tick writes to `calendar_blocks`, the next pass for
      a different owner can read those rows as fixed anchors.
- [x] Phase 3b — persistence + cross-owner deps + APScheduler loop:
      [app/services/persistence.py](backend/app/services/persistence.py) diffs the
      packer proposal against `calendar_blocks` (insert / update / delete; preserves
      `locked=true` blocks the user pinned manually). Idempotent — a second call with
      the same proposal is a no-op. [app/services/scheduler.py](backend/app/services/scheduler.py)
      loads cross-owner anchors (other owners' persisted blocks for tasks this owner's
      tasks depend on) so the packer can satisfy delegated-task deps. The packer's
      `existing_anchors` param wraps those without consuming this owner's slots.
      [app/services/scheduler_tick.py](backend/app/services/scheduler_tick.py) runs a
      fixed-point multi-pass loop (up to 3 passes) — pass 1 packs owner A, pass 2 sees
      A's newly-persisted blocks and unblocks owner B's delegated tasks. Aggregates
      diff counts across passes so a real insert isn't masked by a no-op pass.
      [app/services/scheduler_loop.py](backend/app/services/scheduler_loop.py) is the
      APScheduler `BackgroundScheduler` (60s interval, configurable via
      `SCHEDULER_TICK_SECONDS`), started by [app/main.py](backend/app/main.py)'s
      FastAPI lifespan handler. [app/services/reschedule.py](backend/app/services/reschedule.py)
      now runs a real synchronous tick from `/ingest` so a new goal's tasks land on
      the calendar within the same request, not 60s later. `POST /admin/tick` exposes
      a manual trigger for dev. 11 new tests (60 → 71). End-to-end demo: all 28 tasks
      across both cofounders persist on the first tick, including all 6 of Chris's
      delegated tasks correctly ordered after their cross-owner Michael prereqs.

      **Test conftest disables `enable_scheduler_loop`** so pytest never races with a
      background tick.
- [x] Phase 4 — Google Calendar via direct OAuth (NOT MCP — see Deviations):
      Each `User` gets `email` + `google_refresh_token` columns (Alembic 0002).
      [app/routers/oauth.py](backend/app/routers/oauth.py) hosts `/oauth/google/start`
      and `/callback` with PKCE — the code_verifier rides inside the HMAC-signed
      `state` (confidential-client safe; client_secret is the real auth factor) so
      the callback can recover it after Google's redirect round trip.
      [app/services/google_calendar.py](backend/app/services/google_calendar.py)
      reads real events via `events.list`, skips its own `cadence_block`-tagged
      events, subtracts the rest from the work-hours skeleton, and writes new
      events with `extendedProperties.private.cadence_block: "true"` so the user's
      real meetings are never touched. [app/services/scheduler.py](backend/app/services/scheduler.py)
      auto-picks `GoogleCalendarProvider` when the owner has a refresh_token,
      else falls back to `StubCalendarProvider`. [app/services/persistence.py](backend/app/services/persistence.py)
      mirrors `calendar_blocks` writes upstream (insert→`events.insert`,
      update→`events.patch`, delete→`events.delete`) and stores the returned
      `event_id` on each row. 16 new tests (97 total). Live demo: 26 events on
      Michael's calendar + 6 on Chris's, all `cadence_block`-tagged, dependency-
      ordered, dropped into actual work-hour slots.
- [x] Phase 4.1 — migrated to Supabase Postgres. `alembic upgrade head` against the
      Supabase URL applied both migrations (0001 + 0002) including the Postgres-only
      `text_pattern_ops` index on `delegation_graph.materialized_path`. Cofounders
      re-seeded with emails; both re-OAuthed. Verified end-to-end on Postgres: the
      same press-launch /ingest produced 16 tasks → 16 calendar_blocks (all with
      gcal_event_id) → 14 events on Michael's Google Calendar + 2 on Chris's. SQLite
      `cadence.db` is now stale and can be deleted whenever; tests still use
      `:memory:` SQLite, dev defaults to Postgres if `DATABASE_URL` is set.
- [x] Phase 5 — Now-screen vertical slice.
      **Backend (5a):** three new endpoints in [app/routers/now.py](backend/app/routers/now.py)
      — `GET /next-action?owner_id=N` returns the earliest-starting calendar_block
      whose task is still surfaceable; `POST /tasks/{id}/start` flips status to
      `in_progress` + stamps `started_at`; `POST /tasks/{id}/done` stamps
      `finished_at`, logs to `execution_log` (feeds temporal correction), triggers
      a reschedule, and returns the new `next-action` inline so the UI flips
      without a second round-trip. CORS middleware added so the Expo web target
      can hit the API from a different port. 11 new tests (109 total).
      **Frontend (5b/5c):** Expo SDK 54 (React 19, Reanimated 4) at [cadence/](cadence/).
      Stripped the default `tabs` template; single Stack screen. Aesthetic commitment
      from the `frontend-design` skill: refined minimalism with intentional warmth
      — warm dark palette, Fraunces serif reserved for the task title only, DM Sans
      for everything else, single dominant terra-cotta accent for the action button.
      [cadence/src/theme.ts](cadence/src/theme.ts) is the only source of design
      tokens. [cadence/src/api.ts](cadence/src/api.ts) is a tiny fetch wrapper
      (typed). [cadence/src/timer-store.ts](cadence/src/timer-store.ts) is the local
      Pomodoro state (Zustand). [cadence/app/_layout.tsx](cadence/app/_layout.tsx)
      loads Google Fonts behind the SplashScreen + mounts the QueryClient.
      [cadence/app/index.tsx](cadence/app/index.tsx) is the Now screen — wordmark,
      single task card with the why-line and countdown, Start→Done button,
      dim Up-Next preview. No NativeWind (compatibility friction on SDK 54);
      `StyleSheet` + design tokens instead. `OWNER_ID` is hardcoded to 1 (Michael)
      for v1; auth/login comes later.
      **Demo:** `cd cadence && npx expo start --web` serves the app at
      http://localhost:8081 against the brain at http://localhost:8000 (backend
      should run with `--host 0.0.0.0` if you want to hit it from a phone via
      LAN; set `EXPO_PUBLIC_API_BASE=http://LAN_IP:8000` when starting expo).
- [ ] Phase 5 — Now-screen vertical slice (bootstrap Expo here)
- [ ] Phase 4 — Google Calendar via MCP
- [ ] Phase 6 — reminders + gamification + execution analytics.
      Three workstreams; 6a done, 6b/6c pending.
      (a) [x] **Execution analytics + reports** — Alembic 0003 added
          `execution_log.scheduled_for`, captured at `/tasks/{id}/done` from the
          live `calendar_block.start` BEFORE reschedule wipes the block. New
          `GET /reports/weekly?owner_id=N` (configurable `end_date` + `window_days`)
          returns `{ total_completed, completed_on_time, completed_late, no_deadline,
          avg_actual_over_est, total_minutes_estimated/actual, longest_overrun,
          by_importance (importance → {completed, on_time, late}), rows[] }`.
          12 new tests (121 total). Live-verified against Postgres — picked up
          4 organic completions from the user's click-testing of the Now screen
          and computed correct stats.
      (b) [x] **Gamification** — `app/services/gamification.py` does the math:
          +5 on Start, +20 on Done, +10 first-of-day bonus on Done. Streak
          continues if last done was yesterday in the OWNER'S timezone (not UTC
          — tested), resets to 1 after a 2+ day gap, longest_streak preserved
          across resets. `gamification_state` row is lazily created on first
          action. `GET /gamification?owner_id=N` returns the current counters
          (zeros if user never played). Hooked into existing /tasks/{id}/start
          and /done. Frontend shows a small "★ N · M-day streak" chip in the
          Now-screen header, hidden when points=0; query invalidates on Start
          + Done so the number updates without polling. 9 new tests (130 total).
      (c) **Reminders** — multi-modal escalation per Section 8.1: in-app pulse →
          push notification → push requiring acknowledgement. Expo push token on
          `users.push_token`, server-side fire via `EXPO_ACCESS_TOKEN`.
- [ ] Phase 7 — daily closed-loop briefing + body doubling
