# Deploying Cadence ("Close Your Loops")

Three runtime surfaces, one backend:

| Surface          | What it is                              | Where it runs                         |
| ---------------- | --------------------------------------- | ------------------------------------- |
| **Brain**        | FastAPI + scheduler + Postgres          | A server (Fly/Render/Railway/VM)      |
| **Web app**      | Expo web export — Now / dashboard / widget routes | Any static host (Vercel/Netlify/Cloudflare Pages) |
| **Desktop widget** | Tauri shell wrapping the `/widget` route | Downloaded `.dmg` / `.msi`, runs as a tray overlay |

The widget is **not** a separate codebase — it's a thin native window that loads the
same `/widget` web route. Ship the web app once; the desktop widget is a downloadable
wrapper around it.

> **Auth (Phase 8) — built.** Login is required: `POST /auth/login` issues a session JWT
> and every data router is gated by `Depends(get_current_user)`; `auth`/`oauth`/`slack`/
> `health` stay public. The frontend shows a login screen and gates all surfaces (Now /
> dashboard / widget) behind it. Auth gates the **two-person team** (only the seeded
> accounts can touch the API) rather than isolating per user — the shared board, partner
> presence, and cross-owner delegation all need cross-visibility.
>
> Production checklist for auth:
> - Set a strong **`AUTH_SECRET`** (≥32 bytes) per environment — login 503s without it,
>   and rotating it invalidates all existing sessions.
> - Seed each user's password once with `backend/scripts/set_password.py`
>   (`EMAIL=… PASSWORD=… PYTHONPATH=. .venv/bin/python scripts/set_password.py`).
> - Tokens are long-lived (`AUTH_TOKEN_TTL_DAYS`, default 30) and have no server-side
>   revocation list — fine for a 2-person internal tool. If you need instant kill-switch
>   revocation later, add a token-version column to `users` and check it in
>   `app/security.py`.

---

## 1. Backend (the brain)

Already runs against Supabase Postgres. To host it:

> **Hostinger VPS (Ubuntu): see [backend/deploy/README.md](backend/deploy/README.md)**
> for a complete copy-paste runbook (systemd + Caddy auto-HTTPS + the prod `.env`
> + Google OAuth redirect update). The generic steps below are the same idea for
> any always-on host.

1. Provision a small always-on instance (the APScheduler loop must run continuously —
   serverless/lambda won't work for the 60s scheduler + reminder ticks).
2. Set environment (see `backend/.env.example`). Production-relevant additions:
   - `DATABASE_URL` — the Supabase connection string.
   - `CORS_ALLOW_ORIGINS` — the deployed web origin **and** the Tauri origin, e.g.
     `https://closedloops.tech,tauri://localhost`. (Dev default is `*`.)
   - `GOOGLE_OAUTH_REDIRECT_URI` — must point at the deployed host's
     `/oauth/google/callback`, and that exact URI must be added to the Google Cloud
     OAuth client's authorized redirect URIs.
   - `ANTHROPIC_API_KEY`, `SLACK_WEBHOOK_URL`, `SLACK_SIGNING_SECRET`,
     `EXPO_ACCESS_TOKEN` as needed.
3. Run migrations on deploy: `alembic upgrade head`.
4. Start: `uvicorn app.main:app --host 0.0.0.0 --port 8000` (behind TLS — Google OAuth
   and Expo push both expect https in production).

## 2. Web app (dashboard + Now + widget routes)

Build the static bundle:

```bash
cd cadence
EXPO_PUBLIC_API_BASE=https://api.closedloops.tech npm run web:export   # -> cadence/dist/
```

`EXPO_PUBLIC_API_BASE` is baked in at export time — point it at the deployed brain, not
localhost. The output `dist/` is plain static files:

- `dist/index.html`      → the mobile Now screen (`/`)
- `dist/dashboard.html`  → the desktop Kanban dashboard (`/dashboard`)
- `dist/widget.html`     → the compact overlay (`/widget`)

Deploy `dist/` to any static host. Routes are flat `.html` files (Expo Router static
export), so configure the host to serve `/dashboard` → `dashboard.html` if it doesn't
resolve extensionless paths automatically.

## 3. Desktop widget (Tauri overlay)

The native shell lives in `cadence/src-tauri/`. It opens a **frameless, transparent,
always-on-top** window pointed at the `/widget` route, plus a **system-tray icon** and a
**global hotkey (Cmd/Ctrl+Shift+L)** to show/hide it.

> **Cannot be built in this dev sandbox** — there's no Rust toolchain here and the target
> is your Mac/Windows machine, not Linux. The `src-tauri/` files are a faithful scaffold;
> build and verify them on your own machine. Minor Tauri-v2 API tweaks may be needed.

### One-time setup on your machine

```bash
# Install Rust: https://rustup.rs
# macOS also needs Xcode CLT; Windows needs the WebView2 runtime (preinstalled on Win11).
cd cadence
npm install          # pulls @tauri-apps/cli (already in package.json)
```

### Point the widget at the right server

`src-tauri/tauri.conf.json` → `app.windows[0].url`:

- **Local dev:** `http://localhost:8081/widget` (the value committed now). Run the Expo
  web dev server (`npm run web`) and the backend, then `npm run widget:dev`.
- **Production:** set it to your deployed web origin, e.g.
  `https://closedloops.tech/widget`, then `npm run widget:build`. The widget always
  renders live server state — no rebuild needed when the web app changes, only when the
  URL or native shell changes.

### Build

```bash
npm run widget:dev      # hot-reload dev run of the overlay
npm run widget:build    # produces a .dmg (macOS) / .msi (Windows) installer
```

Installers land in `src-tauri/target/release/bundle/`.

### Known follow-ups for the native shell

- **Dragging:** the window is frameless (`decorations: false`), so it has no titlebar to
  drag. To move it, either add a drag region to the widget header (`-webkit-app-region:
  drag` in the web CSS, or a `data-tauri-drag-region` element) or flip `decorations` back
  to `true` in `tauri.conf.json`.
- **Icons:** `src-tauri/icons/` holds the default Tauri icons. Replace them with the
  Close-Your-Loops mark (`npx tauri icon path/to/logo.png` regenerates every size).
- **Transparency:** enabled via `macOSPrivateApi: true` (macOS) — fine for an internal
  tool; note Apple may reject private-API apps from the App Store, but direct `.dmg`
  distribution is unaffected.

---

## Quick local smoke test (no native build needed)

```bash
# terminal 1 — brain
cd backend && uvicorn app.main:app --reload --port 8000
# terminal 2 — web (serves all three routes)
cd cadence && npm run web
```

Open `http://localhost:8081/dashboard` (Kanban) and `http://localhost:8081/widget`
(overlay) in a browser. The Tauri build just wraps that same `/widget` route in a native
always-on-top window.
