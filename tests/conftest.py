from collections.abc import AsyncGenerator, Awaitable, Callable

import pytest_asyncio
from fastapi import BackgroundTasks
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import Base
from app.core.security import hash_password
from app.modules.auth.models import EmailOtp, PasswordResetToken, RefreshToken
from app.modules.users.models import User, UserRole

settings = get_settings()

# Tests run against the same local Postgres instance as development (no
# separate test database is provisioned in this environment), but isolated
# into their own schema via `schema_translate_map` so they never touch the
# `public` schema's dev data. The schema is dropped and recreated once per
# test session, and tables are cleared between individual tests.
_TEST_SCHEMA = "test_auth"


@pytest_asyncio.fixture(scope="session")
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    base_engine = create_async_engine(settings.database_url)
    async with base_engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{_TEST_SCHEMA}" CASCADE'))
        await conn.execute(text(f'CREATE SCHEMA "{_TEST_SCHEMA}"'))

    scoped_engine = base_engine.execution_options(schema_translate_map={None: _TEST_SCHEMA})
    async with scoped_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield scoped_engine

    async with base_engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{_TEST_SCHEMA}" CASCADE'))
    await base_engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    # Service functions commit internally, so an outer-transaction rollback
    # wouldn't undo anything — clear the tables explicitly between tests
    # instead. Order matters: children before the `users` parent.
    async with session_factory() as cleanup_session:
        for model in (PasswordResetToken, EmailOtp, RefreshToken, User):
            await cleanup_session.execute(model.__table__.delete())
        await cleanup_session.commit()


@pytest_asyncio.fixture
def make_user(
    db_session: AsyncSession,
) -> Callable[..., Awaitable[User]]:
    async def _make_user(
        email: str = "learner@example.com",
        password: str = "Str0ngPass!",
        full_name: str = "Test Learner",
        *,
        is_active: bool = True,
        is_email_verified: bool = True,
    ) -> User:
        user = User(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            role=UserRole.LEARNER,
            is_active=is_active,
            is_email_verified=is_email_verified,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user

    return _make_user


@pytest_asyncio.fixture
def background_tasks() -> BackgroundTasks:
    return BackgroundTasks()
