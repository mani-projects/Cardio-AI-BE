from app.modules.case_attempts.models import CaseAttemptStatus
from app.modules.cases.models import CaseStatus
from app.modules.course_lectures.service import mark_watched
from app.modules.course_progress.service import compute_progress_percent, get_course_progress
from app.modules.course_resources.service import mark_viewed


def test_compute_progress_percent_all_categories_empty():
    assert (
        compute_progress_percent(
            lectures_total=0,
            lectures_watched=0,
            resources_total=0,
            resources_viewed=0,
            cases_total=0,
            cases_reviewed=0,
        )
        == 0
    )


def test_compute_progress_percent_skips_empty_categories():
    # Only lectures has any items — resources/cases (total == 0) must not be
    # treated as 0% or 100%; the result is purely the lectures ratio.
    assert (
        compute_progress_percent(
            lectures_total=4,
            lectures_watched=2,
            resources_total=0,
            resources_viewed=0,
            cases_total=0,
            cases_reviewed=0,
        )
        == 50
    )


def test_compute_progress_percent_zero_progress_in_a_nonempty_category_still_counts():
    # resources has items but none viewed yet (ratio 0), which must drag the
    # average down — it must not be skipped the way a total == 0 category is.
    assert (
        compute_progress_percent(
            lectures_total=0,
            lectures_watched=0,
            resources_total=4,
            resources_viewed=0,
            cases_total=4,
            cases_reviewed=4,
        )
        == 50
    )


def test_compute_progress_percent_partial_completion_across_all_three():
    assert (
        compute_progress_percent(
            lectures_total=3,
            lectures_watched=2,
            resources_total=0,
            resources_viewed=0,
            cases_total=2,
            cases_reviewed=1,
        )
        == 58
    )
    assert (
        compute_progress_percent(
            lectures_total=2,
            lectures_watched=1,
            resources_total=4,
            resources_viewed=1,
            cases_total=3,
            cases_reviewed=1,
        )
        == 36
    )


def test_compute_progress_percent_full_completion():
    assert (
        compute_progress_percent(
            lectures_total=5,
            lectures_watched=5,
            resources_total=2,
            resources_viewed=2,
            cases_total=3,
            cases_reviewed=3,
        )
        == 100
    )


async def test_get_course_progress_counts_and_scopes_to_course(
    db_session,
    make_course,
    make_user,
    make_course_lecture,
    make_course_resource,
    make_case_category,
    make_case,
    make_case_attempt,
):
    course = await make_course(slug="1")
    other_course = await make_course(slug="2")
    learner = await make_user(email="learner-progress@example.com")
    faculty = await make_user(email="faculty-progress@example.com")

    lecture_a = await make_course_lecture(course, title="Lecture A")
    lecture_b = await make_course_lecture(course, title="Lecture B")
    await make_course_lecture(course, title="Lecture C")
    await mark_watched(db_session, lecture_id=lecture_a.id, user_id=learner.id)
    await mark_watched(db_session, lecture_id=lecture_b.id, user_id=learner.id)
    # Noise: a lecture in a different course must not affect this course's counts.
    await make_course_lecture(other_course, title="Other course lecture")

    resource = await make_course_resource(course, title="Resource A")
    await make_course_resource(course, title="Resource B")
    await mark_viewed(db_session, resource_id=resource.id, user_id=learner.id)

    category = await make_case_category(course)
    approved_a = await make_case(course, category, faculty, title="Approved A")
    approved_a.status = CaseStatus.APPROVED
    approved_b = await make_case(course, category, faculty, title="Approved B")
    approved_b.status = CaseStatus.APPROVED
    pending = await make_case(course, category, faculty, title="Pending")
    await db_session.commit()
    assert pending.status == CaseStatus.PENDING_REVIEW

    reviewed_attempt = await make_case_attempt(approved_a, learner)
    reviewed_attempt.status = CaseAttemptStatus.REVIEWED
    submitted_attempt = await make_case_attempt(approved_b, learner)
    submitted_attempt.status = CaseAttemptStatus.SUBMITTED
    await db_session.commit()

    progress = await get_course_progress(db_session, course_id=course.id, learner_id=learner.id)

    assert progress["lectures_total"] == 3
    assert progress["lectures_watched"] == 2
    assert progress["resources_total"] == 2
    assert progress["resources_viewed"] == 1
    assert progress["cases_total"] == 2
    assert progress["cases_reviewed"] == 1
    assert progress["percent"] == compute_progress_percent(
        lectures_total=3,
        lectures_watched=2,
        resources_total=2,
        resources_viewed=1,
        cases_total=2,
        cases_reviewed=1,
    )


async def test_get_course_progress_empty_course_is_zero_percent(db_session, make_course, make_user):
    course = await make_course(slug="1")
    learner = await make_user(email="learner-progress-empty@example.com")

    progress = await get_course_progress(db_session, course_id=course.id, learner_id=learner.id)

    assert progress == {
        "lectures_total": 0,
        "lectures_watched": 0,
        "resources_total": 0,
        "resources_viewed": 0,
        "cases_total": 0,
        "cases_reviewed": 0,
        "percent": 0,
    }
