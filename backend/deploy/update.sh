#!/usr/bin/env bash
# Redeploy the brain after a GitHub push: pull, install deps, migrate, restart.
# Idempotent — safe to run any time. Run from the backend dir (or anywhere; it
# cd's itself). The systemctl line needs sudo unless run as root.
set -euo pipefail

cd /opt/cadence/Close-Loops/backend

git pull --ff-only
.venv/bin/pip install -q -r requirements.txt
.venv/bin/alembic upgrade head
sudo systemctl restart cadence-brain

sleep 1
curl -fsS http://127.0.0.1:8000/health && echo
echo "deployed: $(git rev-parse --short HEAD)"
