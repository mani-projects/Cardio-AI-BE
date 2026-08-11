#!/usr/bin/env bash
# Redeploy script — run ON THE VPS from /opt/cardio-ai-server after the
# one-time setup (see deploy/README.md). Pulls latest code, syncs deps,
# applies migrations, restarts the service.
set -euo pipefail

cd "$(dirname "$0")/.."

git pull
uv sync
uv run alembic upgrade head
sudo systemctl restart cardio-ai-server
sudo systemctl status cardio-ai-server --no-pager -l
