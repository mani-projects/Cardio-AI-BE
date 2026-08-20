import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.case_attempts.models import CaseAttempt, CaseAttemptStatus
from app.modules.cases.models import Case, CaseStatus
from app.modules.course_lectures.models import CourseLecture, LectureWatchState
from app.modules.course_resources.models import CourseResource, ResourceViewState


async def _count(db: AsyncSession, stmt: Select) -> int:
    return (await db.execute(stmt)).scalar_one()


def compute_progress_percent(
    *,
    lectures_total: int,
    lectures_watched: int,
    resources_total: int,
    resources_viewed: int,
    cases_total: int,
    cases_reviewed: int,
) -> int:
    """Average per-category completion ratio, skipping empty categories.

    Each of the three categories (lectures, resources, cases) contributes
    completed/total to the average only if it has at least one item — an
    empty category (total == 0) is left out of the average entirely rather
    than counted as 0% or 100%. If every category is empty, the result is 0.
    """
    ratios = [
        completed / total
        for total, completed in (
            (lectures_total, lectures_watched),
            (resources_total, resources_viewed),
            (cases_total, cases_reviewed),
        )
        if total > 0
    ]
    if not ratios:
        return 0
    return round(sum(ratios) / len(ratios) * 100)


async def get_course_progress(db: AsyncSession, *, course_id: uuid.UUID, learner_id: uuid.UUID) -> dict[str, int]:
    lectures_total = await _count(
        db, select(func.count()).select_from(CourseLecture).where(CourseLecture.course_id == course_id)
    )
    lectures_watched = await _count(
        db,
        select(func.count())
        .select_from(LectureWatchState)
        .join(CourseLecture, CourseLecture.id == LectureWatchState.lecture_id)
        .where(CourseLecture.course_id == course_id, LectureWatchState.user_id == learner_id),
    )

    resources_total = await _count(
        db, select(func.count()).select_from(CourseResource).where(CourseResource.course_id == course_id)
    )
    resources_viewed = await _count(
        db,
        select(func.count())
        .select_from(ResourceViewState)
        .join(CourseResource, CourseResource.id == ResourceViewState.resource_id)
        .where(CourseResource.course_id == course_id, ResourceViewState.user_id == learner_id),
    )

    cases_total = await _count(
        db,
        select(func.count()).select_from(Case).where(Case.course_id == course_id, Case.status == CaseStatus.APPROVED),
    )
    cases_reviewed = await _count(
        db,
        select(func.count())
        .select_from(CaseAttempt)
        .join(Case, Case.id == CaseAttempt.case_id)
        .where(
            Case.course_id == course_id,
            Case.status == CaseStatus.APPROVED,
            CaseAttempt.learner_id == learner_id,
            CaseAttempt.status == CaseAttemptStatus.REVIEWED,
        ),
    )

    percent = compute_progress_percent(
        lectures_total=lectures_total,
        lectures_watched=lectures_watched,
        resources_total=resources_total,
        resources_viewed=resources_viewed,
        cases_total=cases_total,
        cases_reviewed=cases_reviewed,
    )

    return {
        "lectures_total": lectures_total,
        "lectures_watched": lectures_watched,
        "resources_total": resources_total,
        "resources_viewed": resources_viewed,
        "cases_total": cases_total,
        "cases_reviewed": cases_reviewed,
        "percent": percent,
    }
