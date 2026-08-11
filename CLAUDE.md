# cardio-ai-server

FastAPI backend for CardioAI, a cardiology training platform. Serves the Next.js frontend, [`cardio-ai`](../cardio-ai) (sibling directory). Build production-ready code, not MVP-phased scaffolding.

## Roles

Three roles on `User.role`: **learner**, **teacher** (owns course content), **admin**. Only learner auth (`app/modules/auth/`) is built so far — don't assume teacher/admin endpoints exist yet.

## Auth

Self-rolled JWT, not a third-party provider:

- `app/core/security.py` — password hashing (bcrypt) and JWT create/decode (PyJWT).
- Access tokens: short-lived, carry `sub` (user id) + `role`, stateless.
- Refresh tokens: carry `sub` + `jti`; `jti` maps to a `RefreshToken` row (`app/modules/auth/models.py`) so tokens can be revoked. `/auth/refresh` rotates — marks the old row revoked and issues a new pair — rather than re-signing in place.
- `app/modules/auth/service.py` holds the actual logic (`register_learner`, `authenticate`, `rotate_refresh_token`, `revoke_refresh_token`); `router.py` is thin HTTP glue.
- Token lifetimes (`ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS` in `.env`) must stay in sync by hand with the frontend's cookie max-ages in `cardio-ai`'s `src/lib/auth/constants.ts`.

## Database

- Async SQLAlchemy 2.0 (`asyncpg`), session per request via `app.core.database.get_db`.
- Schema changes go through Alembic — never edit the DB by hand. `uv run alembic revision --autogenerate -m "..."` then `uv run alembic upgrade head`.

## Conventions

- Package/dependency management is `uv`, not pip/poetry — use `uv add`/`uv sync`/`uv run`.
- Each domain lives under `app/modules/<name>/` with `router.py` (HTTP), `service.py` (logic), `models.py` (SQLAlchemy), `schemas.py` (Pydantic). Keep routers thin; put business logic in services.
- Domain errors are raised as plain exceptions (e.g. `InvalidCredentialsError`) in the service layer and translated to `HTTPException` in the router — don't raise `HTTPException` from services.
