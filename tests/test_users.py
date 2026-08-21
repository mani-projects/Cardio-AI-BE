from datetime import datetime, timedelta, timezone

import pytest

from app.modules.users.models import User, UserRole
from app.modules.users.service import (
    UserNotDeletedError,
    delete_user,
    list_users,
    purge_deleted_users,
    restore_user,
)


# ---------------------------------------------------------------------------
# delete_user / restore_user / purge_deleted_users
# ---------------------------------------------------------------------------


async def test_delete_user_soft_deletes(db_session, make_user):
    user = await make_user()

    await delete_user(db_session, user)

    await db_session.refresh(user)
    assert user.deleted_at is not None
    # Still physically present, not gone.
    assert await db_session.get(User, user.id) is not None


async def test_restore_user_clears_deleted_at(db_session, make_user):
    user = await make_user()
    await delete_user(db_session, user)

    restored = await restore_user(db_session, user)

    assert restored.deleted_at is None


async def test_restore_user_raises_when_not_deleted(db_session, make_user):
    user = await make_user()

    with pytest.raises(UserNotDeletedError):
        await restore_user(db_session, user)


async def test_purge_deleted_users_only_removes_rows_past_the_retention_window(db_session, make_user):
    recent = await make_user(email="recent@example.com")
    old = await make_user(email="old@example.com")

    await delete_user(db_session, recent)
    await delete_user(db_session, old)
    old.deleted_at = datetime.now(timezone.utc) - timedelta(days=4)
    await db_session.commit()

    purged_count = await purge_deleted_users(db_session)

    assert purged_count == 1
    assert await db_session.get(User, old.id) is None
    assert await db_session.get(User, recent.id) is not None


async def test_list_users_excludes_deleted_by_default(db_session, make_user):
    active = await make_user(email="active@example.com")
    deleted = await make_user(email="deleted@example.com")
    await delete_user(db_session, deleted)

    items, total = await list_users(db_session)

    assert total == 1
    assert [item.id for item in items] == [active.id]


async def test_list_users_deleted_true_shows_only_deleted(db_session, make_user):
    active = await make_user(email="active@example.com")
    deleted = await make_user(email="deleted@example.com")
    await delete_user(db_session, deleted)

    items, total = await list_users(db_session, deleted=True)

    assert total == 1
    assert [item.id for item in items] == [deleted.id]
    assert active.id not in [item.id for item in items]


async def test_list_users_deleted_combines_with_role_filter(db_session, make_user):
    deleted_learner = await make_user(email="learner@example.com", role=UserRole.LEARNER)
    deleted_teacher = await make_user(email="teacher@example.com", role=UserRole.TEACHER)
    await delete_user(db_session, deleted_learner)
    await delete_user(db_session, deleted_teacher)

    items, total = await list_users(db_session, deleted=True, role=UserRole.TEACHER)

    assert total == 1
    assert [item.id for item in items] == [deleted_teacher.id]
