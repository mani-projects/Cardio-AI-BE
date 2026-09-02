from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import get_settings
from app.modules.auth.service import impersonate_user
from app.modules.users.models import User, UserRole
from app.modules.registrations.models import RegistrationStatus
from app.modules.users.schemas import UserCourseSummary
from app.modules.users.service import (
    UserNotDeletedError,
    delete_user,
    get_preview_user,
    get_user_courses,
    list_users,
    permanently_delete_user,
    purge_deleted_users,
    restore_user,
)

settings = get_settings()


# ---------------------------------------------------------------------------
# impersonate_user
# ---------------------------------------------------------------------------


async def test_impersonate_user_issues_a_real_token_pair_for_the_target(db_session, make_user):
    target = await make_user(email="faculty@example.com", role=UserRole.TEACHER)

    access_token, refresh_token = await impersonate_user(db_session, target)

    access_claims = jwt.decode(access_token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    refresh_claims = jwt.decode(refresh_token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    assert access_claims["sub"] == str(target.id)
    assert access_claims["role"] == "teacher"
    assert refresh_claims["sub"] == str(target.id)


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


async def test_permanently_delete_user_removes_an_already_soft_deleted_user(db_session, make_user):
    user = await make_user()
    await delete_user(db_session, user)

    await permanently_delete_user(db_session, user)

    assert await db_session.get(User, user.id) is None


async def test_permanently_delete_user_raises_when_not_deleted(db_session, make_user):
    user = await make_user()

    with pytest.raises(UserNotDeletedError):
        await permanently_delete_user(db_session, user)


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


async def test_list_users_course_filter_covers_learners_and_teachers(
    db_session, make_user, make_course, make_registration, make_course_faculty
):
    level_two = await make_course(slug="2")
    level_one = await make_course(slug="1")
    learner = await make_user(email="learner@example.com", role=UserRole.LEARNER)
    teacher = await make_user(email="teacher@example.com", role=UserRole.TEACHER)
    other = await make_user(email="other@example.com", role=UserRole.LEARNER)
    await make_registration(level_two, learner, status=RegistrationStatus.PAID)
    await make_course_faculty(level_two, teacher)
    await make_registration(level_one, other, status=RegistrationStatus.PAID)

    items, total = await list_users(db_session, course_slug="2")

    assert total == 2
    assert {item.id for item in items} == {learner.id, teacher.id}


async def test_list_users_attendance_filter_matches_loosely(
    db_session, make_user, make_course, make_registration
):
    course = await make_course(slug="2")
    virtual = await make_user(email="virtual@example.com", role=UserRole.LEARNER)
    hybrid = await make_user(email="hybrid@example.com", role=UserRole.LEARNER)
    await make_registration(course, virtual, status=RegistrationStatus.PAID, attendance="Fully Virtual")
    await make_registration(
        course, hybrid, status=RegistrationStatus.PAID, attendance="Hybrid (in-person in Dubai)"
    )

    virtual_items, virtual_total = await list_users(db_session, attendance="virtual")
    hybrid_items, hybrid_total = await list_users(db_session, attendance="hybrid")

    assert virtual_total == 1
    assert [item.id for item in virtual_items] == [virtual.id]
    assert hybrid_total == 1
    assert [item.id for item in hybrid_items] == [hybrid.id]


async def test_get_user_courses_covers_learners_and_teachers(
    db_session, make_user, make_course, make_registration, make_course_faculty
):
    course = await make_course(slug="1")
    learner = await make_user(email="student@example.com", role=UserRole.LEARNER)
    teacher = await make_user(email="prof@example.com", role=UserRole.TEACHER)
    admin = await make_user(email="root@example.com", role=UserRole.ADMIN)
    await make_registration(course, learner, status=RegistrationStatus.PAID)
    await make_course_faculty(course, teacher)

    courses = await get_user_courses(db_session, [learner.id, teacher.id, admin.id])

    assert [c.title for c in courses[learner.id]] == [course.title]
    assert [c.title for c in courses[teacher.id]] == [course.title]
    assert courses[admin.id] == []


async def test_get_user_courses_includes_attendance_for_level_two(
    db_session, make_user, make_course, make_registration
):
    course = await make_course(slug="2", title="Hybrid Advance Cardiac CT Course (Level II)")
    learner = await make_user(email="student@example.com", role=UserRole.LEARNER)
    await make_registration(course, learner, status=RegistrationStatus.PAID, attendance="Fully Virtual")

    courses = await get_user_courses(db_session, [learner.id])

    assert courses[learner.id] == [
        UserCourseSummary(slug="2", title=course.title, attendance="Fully Virtual"),
    ]


async def test_get_user_courses_empty_list_returns_empty_dict(db_session):
    assert await get_user_courses(db_session, []) == {}


# ---------------------------------------------------------------------------
# get_preview_user
# ---------------------------------------------------------------------------


async def test_get_preview_user_prefers_teacher_with_a_course_assignment(
    db_session, make_user, make_course, make_course_faculty
):
    course = await make_course(slug="1")
    idle_teacher = await make_user(email="idle@example.com", role=UserRole.TEACHER)
    assigned_teacher = await make_user(email="assigned@example.com", role=UserRole.TEACHER)
    await make_course_faculty(course, assigned_teacher)

    preview = await get_preview_user(db_session, UserRole.TEACHER)

    assert preview is not None
    assert preview.id == assigned_teacher.id
    assert preview.id != idle_teacher.id


async def test_get_preview_user_prefers_learner_with_a_registration(
    db_session, make_user, make_course, make_registration
):
    course = await make_course(slug="1")
    idle_learner = await make_user(email="idle@example.com", role=UserRole.LEARNER)
    registered_learner = await make_user(email="registered@example.com", role=UserRole.LEARNER)
    await make_registration(course, registered_learner, status=RegistrationStatus.PAID)

    preview = await get_preview_user(db_session, UserRole.LEARNER)

    assert preview is not None
    assert preview.id == registered_learner.id
    assert preview.id != idle_learner.id


async def test_get_preview_user_falls_back_to_any_active_account_of_the_role(db_session, make_user):
    teacher = await make_user(email="prof@example.com", role=UserRole.TEACHER)

    preview = await get_preview_user(db_session, UserRole.TEACHER)

    assert preview is not None
    assert preview.id == teacher.id


async def test_get_preview_user_excludes_deleted_and_inactive_accounts(db_session, make_user):
    deleted_teacher = await make_user(email="deleted@example.com", role=UserRole.TEACHER)
    await delete_user(db_session, deleted_teacher)
    await make_user(email="inactive@example.com", role=UserRole.TEACHER, is_active=False)

    preview = await get_preview_user(db_session, UserRole.TEACHER)

    assert preview is None


async def test_get_preview_user_returns_none_when_no_account_of_that_role_exists(db_session):
    assert await get_preview_user(db_session, UserRole.TEACHER) is None
