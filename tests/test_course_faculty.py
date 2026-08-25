import uuid

import pytest

from app.modules.cases.service import approve_case
from app.modules.courses.service import (
    DuplicateCourseFacultyError,
    CourseFacultyAssignmentNotFoundError,
    NotATeacherError,
    UserNotFoundError,
    assign_course_faculty,
    get_course_content_stats,
    get_course_faculty_stats,
    is_course_faculty,
    list_faculty_courses,
    remove_course_faculty,
)
from app.modules.registrations.models import RegistrationStatus
from app.modules.users.models import UserRole


async def test_assign_course_faculty_creates_row(db_session, make_course, make_user):
    course = await make_course()
    teacher = await make_user(email="teacher@example.com", role=UserRole.TEACHER)

    assignment = await assign_course_faculty(db_session, course_id=course.id, user_id=teacher.id, assigned_by=None)

    assert assignment.course_id == course.id
    assert assignment.user_id == teacher.id


async def test_assign_course_faculty_rejects_non_teacher(db_session, make_course, make_user):
    course = await make_course()
    learner = await make_user(email="learner2@example.com", role=UserRole.LEARNER)

    with pytest.raises(NotATeacherError):
        await assign_course_faculty(db_session, course_id=course.id, user_id=learner.id, assigned_by=None)


async def test_assign_course_faculty_rejects_unknown_user(db_session, make_course):
    course = await make_course()

    with pytest.raises(UserNotFoundError):
        await assign_course_faculty(db_session, course_id=course.id, user_id=uuid.uuid4(), assigned_by=None)


async def test_assign_course_faculty_blocks_duplicate(db_session, make_course, make_user):
    course = await make_course()
    teacher = await make_user(email="teacher3@example.com", role=UserRole.TEACHER)
    await assign_course_faculty(db_session, course_id=course.id, user_id=teacher.id, assigned_by=None)

    with pytest.raises(DuplicateCourseFacultyError):
        await assign_course_faculty(db_session, course_id=course.id, user_id=teacher.id, assigned_by=None)


async def test_remove_course_faculty(db_session, make_course, make_user, make_course_faculty):
    course = await make_course()
    teacher = await make_user(email="teacher4@example.com", role=UserRole.TEACHER)
    await make_course_faculty(course, teacher)

    await remove_course_faculty(db_session, course_id=course.id, user_id=teacher.id)

    assert await is_course_faculty(db_session, course_id=course.id, user_id=teacher.id) is False


async def test_remove_course_faculty_missing_raises(db_session, make_course, make_user):
    course = await make_course()
    teacher = await make_user(email="teacher5@example.com", role=UserRole.TEACHER)

    with pytest.raises(CourseFacultyAssignmentNotFoundError):
        await remove_course_faculty(db_session, course_id=course.id, user_id=teacher.id)


async def test_is_course_faculty_true_and_false(db_session, make_course, make_user, make_course_faculty):
    course = await make_course()
    teacher = await make_user(email="teacher6@example.com", role=UserRole.TEACHER)
    other_teacher = await make_user(email="teacher7@example.com", role=UserRole.TEACHER)
    await make_course_faculty(course, teacher)

    assert await is_course_faculty(db_session, course_id=course.id, user_id=teacher.id) is True
    assert await is_course_faculty(db_session, course_id=course.id, user_id=other_teacher.id) is False


async def test_list_faculty_courses_returns_all_assigned(db_session, make_course, make_user, make_course_faculty):
    course_one = await make_course(slug="1")
    course_two = await make_course(slug="1.5")
    course_three = await make_course(slug="2")
    teacher = await make_user(email="teacher8@example.com", role=UserRole.TEACHER)
    await make_course_faculty(course_one, teacher)
    await make_course_faculty(course_two, teacher)

    courses = await list_faculty_courses(db_session, teacher.id)

    assert {c.slug for c in courses} == {"1", "1.5"}
    assert course_three.slug not in {c.slug for c in courses}


async def test_get_course_content_stats_counts_resources_lectures_and_enrollments(
    db_session, make_course, make_course_resource, make_course_lecture, make_registration
):
    course = await make_course(slug="1")
    other_course = await make_course(slug="2")
    await make_course_resource(course)
    await make_course_resource(course)
    await make_course_lecture(course)
    await make_registration(course, status=RegistrationStatus.PAID)
    await make_registration(course, status=RegistrationStatus.FREE)
    await make_registration(course, status=RegistrationStatus.PENDING)
    await make_course_resource(other_course)

    stats = await get_course_content_stats(db_session, [course.id, other_course.id])

    assert stats[course.id] == {"resource_count": 2, "lecture_count": 1, "enrolled_count": 2}
    assert stats[other_course.id] == {"resource_count": 1, "lecture_count": 0, "enrolled_count": 0}


async def test_get_course_content_stats_empty_list_returns_empty_dict(db_session):
    assert await get_course_content_stats(db_session, []) == {}


async def test_get_course_faculty_stats_groups_by_uploader(
    db_session,
    make_course,
    make_case_category,
    make_user,
    make_course_resource,
    make_course_lecture,
    make_case,
):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty_a = await make_user(email="stats-fac-a@example.com", role=UserRole.TEACHER)
    faculty_b = await make_user(email="stats-fac-b@example.com", role=UserRole.TEACHER)
    admin = await make_user(email="stats-admin@example.com", role=UserRole.ADMIN)
    await make_course_resource(course, uploaded_by=faculty_a.id)
    await make_course_resource(course, uploaded_by=faculty_a.id)
    await make_course_lecture(course, created_by=faculty_a.id)
    submitted = await make_case(course, category, faculty_a, title="Submitted")
    approved = await make_case(course, category, faculty_b, title="Approved")
    await approve_case(db_session, approved, reviewer_id=admin.id)

    stats = await get_course_faculty_stats(db_session, course.id)

    assert stats[faculty_a.id] == {
        "resource_count": 2,
        "lecture_count": 1,
        "cases_submitted": 1,
        "cases_approved": 0,
    }
    assert stats[faculty_b.id] == {
        "resource_count": 0,
        "lecture_count": 0,
        "cases_submitted": 1,
        "cases_approved": 1,
    }
    assert submitted.faculty_id == faculty_a.id
