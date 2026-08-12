# Deploying to the VPS (72.167.44.58 / api.cardioai.health)

One-time setup. Run on the VPS over SSH as your normal sudo-capable user — the
service runs as that same user (see step 4), so there's no separate service
account and no chown juggling between deploys.

## 1. Postgres

```bash
sudo apt update && sudo apt install -y postgresql
sudo -u postgres psql <<'SQL'
CREATE USER cardioai WITH PASSWORD 'REPLACE_WITH_A_STRONG_PASSWORD';
CREATE DATABASE cardioai OWNER cardioai;
SQL
```

Generate the password with `openssl rand -base64 24` — don't reuse the local-dev `cardioai:cardioai` default. Postgres already listens on localhost only by default; leave it that way (matches the port scan showing 5432 closed externally).

## 2. Code

```bash
sudo mkdir -p /opt/cardio-ai-server
sudo chown "$USER" /opt/cardio-ai-server
git clone <your-repo-url> /opt/cardio-ai-server
cd /opt/cardio-ai-server
curl -LsSf https://astral.sh/uv/install.sh | sh   # installs uv, if not already present
uv sync
```

## 3. `.env`

Create `/opt/cardio-ai-server/.env` (same keys as `.env.example`, production values):

```bash
ENVIRONMENT=production
DATABASE_URL=postgresql+asyncpg://cardioai:<the password from step 1>@localhost:5432/cardioai
JWT_SECRET_KEY=<openssl rand -base64 64>
OTP_HMAC_SECRET=<a different openssl rand -base64 64>
# ...copy the OTP_*, SMTP_* values you already have from local .env...
CORS_ORIGINS=https://cardioai.health
```

Then apply the schema:

```bash
uv run alembic upgrade head
```

## 4. systemd service

Edit `deploy/cardio-ai-server.service` first — replace `REPLACE_WITH_YOUR_SSH_USER` with your actual username (`whoami`). Then:

```bash
sudo cp deploy/cardio-ai-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cardio-ai-server
sudo systemctl status cardio-ai-server --no-pager
```

## 5. nginx + TLS

```bash
sudo cp deploy/nginx-api.cardioai.health.conf /etc/nginx/sites-available/api.cardioai.health
sudo ln -s /etc/nginx/sites-available/api.cardioai.health /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d api.cardioai.health
```

Certbot rewrites the nginx config to add HTTPS + the 80→443 redirect and sets up auto-renewal. Verify:

```bash
curl -i https://api.cardioai.health/health
```

## 6. Firewall

```bash
sudo ufw allow 22,80,443/tcp
sudo ufw enable
sudo ufw status
```

8000 and 5432 should stay unreachable from outside — they already are (confirmed by port scan) since the app binds `127.0.0.1` and Postgres defaults to localhost-only.

## Ongoing deploys

After this one-time setup, ship updates with:

```bash
git pull
./deploy/deploy.sh
```

Always `git pull` *before* running the script, as a separate command — never
let `deploy.sh` pull itself while it's running. Overwriting a script's own
file mid-execution corrupts bash's read of it (it can keep executing stale
lines even after `git pull` reports success), which is exactly what broke
the CI deploy the first time this was wired up.

## Frontend

Point the frontend's `BACKEND_API_URL` at `https://api.cardioai.health/api/v1` and redeploy it.
