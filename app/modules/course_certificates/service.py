import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.modules.case_attempts.models import CaseAttempt, CaseAttemptStatus
from app.modules.cases.models import Case, CaseStatus
from app.modules.course_certificates.models import CourseCertificate
from app.modules.course_lectures.models import CourseLecture, LectureWatchState

_SUPPORTED_CONTENT_TYPES = {"application/pdf", "image/png", "image/jpeg"}
_KEY_PREFIX = "course-certificates"


class CourseCertificateError(Exception):
    """Base class for course-certificate failures."""


class UnsupportedFileTypeError(CourseCertificateError):
    pass


class CertificateNotEarnedError(CourseCertificateError):
    pass


class CertificateNotAvailableError(CourseCertificateError):
    pass


def create_upload_url(*, course_id: uuid.UUID, filename: str, content_type: str) -> tuple[str, str]:
    if content_type not in _SUPPORTED_CONTENT_TYPES:
        raise UnsupportedFileTypeError(content_type)

    file_key = f"{_KEY_PREFIX}/{course_id}/{uuid.uuid4()}-{filename}"
    upload_url = storage.generate_presigned_put_url(file_key, content_type)
    return file_key, upload_url


async def is_course_complete(db: AsyncSession, *, course_id: uuid.UUID, learner_id: uuid.UUID) -> bool:
    lecture_ids = set(
        (await db.execute(select(CourseLecture.id).where(CourseLecture.course_id == course_id))).scalars().all()
    )
    approved_case_ids = set(
        (
            await db.execute(select(Case.id).where(Case.course_id == course_id, Case.status == CaseStatus.APPROVED))
        )
        .scalars()
        .all()
    )

    if not lecture_ids and not approved_case_ids:
        return False

    if lecture_ids:
        watched_ids = set(
            (
                await db.execute(
                    select(LectureWatchState.lecture_id).where(
                        LectureWatchState.user_id == learner_id,
                        LectureWatchState.lecture_id.in_(lecture_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not lecture_ids <= watched_ids:
            return False

    if approved_case_ids:
        reviewed_case_ids = set(
            (
                await db.execute(
                    select(CaseAttempt.case_id).where(
                        CaseAttempt.learner_id == learner_id,
                        CaseAttempt.case_id.in_(approved_case_ids),
                        CaseAttempt.status == CaseAttemptStatus.REVIEWED,
                    )
                )
            )
            .scalars()
            .all()
        )
        if not approved_case_ids <= reviewed_case_ids:
            return False

    return True


async def get_certificate_for_learner(db: AsyncSession, *, course_id: uuid.UUID, learner_id: uuid.UUID) -> str:
    if not await is_course_complete(db, course_id=course_id, learner_id=learner_id):
        raise CertificateNotEarnedError(course_id)

    stmt = select(CourseCertificate).where(CourseCertificate.course_id == course_id)
    certificate = (await db.execute(stmt)).scalar_one_or_none()
    if certificate is None:
        raise CertificateNotAvailableError(course_id)

    return storage.generate_presigned_get_url(certificate.file_key)


async def upsert_certificate_template(
    db: AsyncSession, *, course_id: uuid.UUID, uploaded_by: uuid.UUID | None, file_key: str
) -> CourseCertificate:
    stmt = select(CourseCertificate).where(CourseCertificate.course_id == course_id)
    certificate = (await db.execute(stmt)).scalar_one_or_none()

    if certificate is None:
        certificate = CourseCertificate(course_id=course_id, file_key=file_key, uploaded_by=uploaded_by)
        db.add(certificate)
    else:
        certificate.file_key = file_key
        certificate.uploaded_by = uploaded_by

    await db.commit()
    await db.refresh(certificate)
    return certificate
