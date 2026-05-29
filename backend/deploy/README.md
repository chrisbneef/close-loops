# Deploying the brain to a Hostinger VPS (Ubuntu)

The brain (FastAPI + the always-on scheduler) runs on the VPS under **systemd**,
with **Caddy** in front for automatic HTTPS. It talks to your existing Supabase
DB. The web app lives separately on Vercel and points at this VPS.

```
Browser / widget ──https──▶ Caddy (:443)  ──▶ uvicorn (127.0.0.1:8000)  ──▶ Supabase
                    api.closedloops.com         systemd: cadence-brain
```

Substitute your real domain for `closedloops.com` and your VPS IP for `VPS_IP`
throughout. Run everything as root (or with sudo).

---

## 0. Push the repo to GitHub (from your dev machine, one time)

The repo currently has only local commits. Create an empty **private** repo on
GitHub, then:

```bash
cd /root/Claude-Projects/Close-Loops          # your local repo
git remote add origin git@github.com:<you>/close-loops.git
git push -u origin main
```

> `.env` is gitignored and must NOT be pushed — you'll create it directly on the
> VPS in step 4.

## 1. DNS — point the API subdomain at the VPS

In Hostinger's DNS panel for your domain, add an **A record**:

| Type | Name | Value    |
| ---- | ---- | -------- |
| A    | api  | `VPS_IP` |

(So `api.closedloops.com → VPS_IP`. Point the apex/`www` at Vercel later for the
web app.) Wait for it to resolve: `dig +short api.closedloops.com` → `VPS_IP`.

## 2. VPS prep

```bash
apt update && apt -y upgrade
apt -y install python3-venv python3-pip git curl

# Caddy (official repo)
apt -y install debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt update && apt -y install caddy

# Firewall — allow SSH + HTTP/HTTPS (Caddy needs 80 for the ACME challenge, 443 for TLS)
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
```

## 3. Get the code + create the service user

```bash
useradd --system --create-home --home-dir /opt/cadence cadence
install -d -o cadence -g cadence /opt/cadence
sudo -u cadence git clone https://github.com/<you>/close-loops.git /opt/cadence/Close-Loops

cd /opt/cadence/Close-Loops/backend
sudo -u cadence python3 -m venv .venv
sudo -u cadence .venv/bin/pip install -r requirements.txt
```

(Python 3.10+ — Ubuntu's system `python3` is fine.)

## 4. Production `.env`

Create `/opt/cadence/Close-Loops/backend/.env` (owned by `cadence`). Start from
`.env.example` and fill the prod values:

```bash
DATABASE_URL=<your Supabase postgresql:// URL>
ANTHROPIC_API_KEY=<key>
GOOGLE_OAUTH_CLIENT_ID=<id>
GOOGLE_OAUTH_CLIENT_SECRET=<secret>
GOOGLE_OAUTH_REDIRECT_URI=https://api.closedloops.com/oauth/google/callback
AUTH_SECRET=<generate: python3 -c "import secrets;print(secrets.token_urlsafe(48))">
CORS_ALLOW_ORIGINS=https://closedloops.com,https://<your>.vercel.app
# optional, post-MVP:
SLACK_WEBHOOK_URL=
SLACK_SIGNING_SECRET=
EXPO_ACCESS_TOKEN=
```

```bash
chown cadence:cadence /opt/cadence/Close-Loops/backend/.env
chmod 600 /opt/cadence/Close-Loops/backend/.env
```

## 5. Migrate the DB (idempotent)

```bash
cd /opt/cadence/Close-Loops/backend
sudo -u cadence .venv/bin/alembic upgrade head
```

(Already at head if you've been migrating from your dev machine — this is a
no-op then.)

## 6. Start the service

```bash
cp /opt/cadence/Close-Loops/backend/deploy/cadence-brain.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now cadence-brain
systemctl status cadence-brain --no-pager
curl -fsS http://127.0.0.1:8000/health        # {"status":"ok",...}
```

## 7. Caddy (HTTPS)

```bash
# Edit the domain in the Caddyfile first, then:
cp /opt/cadence/Close-Loops/backend/deploy/Caddyfile /etc/caddy/Caddyfile
systemctl reload caddy
curl -fsS https://api.closedloops.com/health   # cert auto-provisioned on first hit
```

## 8. Google OAuth — add the prod redirect

In Google Cloud Console → your OAuth client → **Authorized redirect URIs**, add:

```
https://api.closedloops.com/oauth/google/callback
```

That URI must match `GOOGLE_OAUTH_REDIRECT_URI` in `.env` exactly. Then both
cofounders re-connect once at `https://api.closedloops.com/oauth/google/start?user_id=1`
(and `?user_id=2`) to store a fresh refresh token for the prod host.

## 9. Point the web app (Vercel) at the brain

When you deploy the web app, build it with:

```
EXPO_PUBLIC_API_BASE=https://api.closedloops.com
```

and make sure that Vercel origin is in `CORS_ALLOW_ORIGINS` (step 4). Restart the
brain after any `.env` change: `systemctl restart cadence-brain`.

---

## Updating after a code change

Push to GitHub from your dev machine, then on the VPS:

```bash
sudo -u cadence /opt/cadence/Close-Loops/backend/deploy/update.sh
```

## Logs / troubleshooting

```bash
journalctl -u cadence-brain -f      # app logs (scheduler ticks, requests)
journalctl -u caddy -f              # TLS / proxy
systemctl restart cadence-brain
```
