# cardio-ai-server

FastAPI backend for CardioAI. Owns auth, users, and persistent data for the [`cardio-ai`](../cardio-ai) Next.js frontend.

## Tech stack

- **Framework**: FastAPI (async), Python 3.13
- **Database**: PostgreSQL via SQLAlchemy 2.0 (async) + `asyncpg`, migrations with Alembic
- **Auth**: self-rolled JWT (PyJWT) access/refresh tokens, `bcrypt` password hashing — no third-party auth provider
- **Package management**: `uv` (see `uv.lock`, `pyproject.toml`)

## Getting started

```bash
cp .env.example .env   # fill in JWT_SECRET_KEY at minimum
docker compose up -d   # Postgres on localhost:5432
uv sync
uv run alembic upgrade head
uv run fastapi dev app/main.py
```

API is served at `http://localhost:8000`, routes prefixed with `/api/v1`. Health check at `/health`.

### Environment variables

See `.env.example`:

| Variable | Purpose |
| --- | --- |
| `ENVIRONMENT` | `development` enables SQL echo logging |
| `DATABASE_URL` | `postgresql+asyncpg://...` connection string |
| `JWT_SECRET_KEY` | Signing key for access/refresh tokens — generate with `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `JWT_ALGORITHM` | Defaults to `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` / `REFRESH_TOKEN_EXPIRE_DAYS` | Token lifetimes — must stay in sync with the frontend's cookie max-ages (`src/lib/auth/constants.ts` in `cardio-ai`) |
| `CORS_ORIGINS` | Comma-separated list of allowed frontend origins |

## Project structure

```
app/
  core/            Settings, async DB session/engine, password hashing + JWT helpers
  modules/
    auth/          Register/login/refresh/logout/me — router, service, schemas, models (RefreshToken)
    users/         User model (id, email, hashed_password, role, is_active) and schemas
  main.py          FastAPI app, CORS, router registration
migrations/        Alembic environment and versioned migrations
docker-compose.yml Local Postgres for development
```

## Auth model

- Users have a `role`: `learner`, `teacher` (owns course content), or `admin`. Only learner auth is implemented so far.
- Access tokens are short-lived JWTs carrying `sub` (user id) and `role`. Refresh tokens are JWTs carrying `sub` and a `jti` that maps to a `RefreshToken` row in Postgres, so a refresh token can be revoked (logout) or rejected once used/expired/revoked.
- `/api/v1/auth/refresh` rotates the refresh token (old row marked revoked, new one issued) rather than just re-signing.

## Migrations

```bash
uv run alembic revision --autogenerate -m "description"
uv run alembic upgrade head
```
