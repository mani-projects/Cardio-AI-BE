from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.course_certificates.schemas import (
    CertificateRead,
    CertificateTemplateRead,
    CreateUploadUrlRequest,
    UploadUrlRead,
    UpsertCertificateRequest,
)
from app.modules.course_certificates.service import (
    CertificateNotAvailableError,
    CertificateNotEarnedError,
    UnsupportedFileTypeError,
    create_upload_url,
    get_certificate_for_learner,
    upsert_certificate_template,
)
from app.modules.courses.dependencies import require_course_faculty
from app.modules.courses.models import Course
from app.modules.registrations.dependencies import require_course_registration
from app.modules.users.models import User

faculty_router = APIRouter(prefix="/faculty", tags=["faculty"])
learner_router = APIRouter(prefix="/courses", tags=["courses"])


@learner_router.get("/{course_id}/certificate", response_model=CertificateRead)
async def get_course_certificate_endpoint(
    course: Course = Depends(require_course_registration()),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CertificateRead:
    try:
        download_url = await get_certificate_for_learner(db, course_id=course.id, learner_id=current_user.id)
    except CertificateNotEarnedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You haven't completed this course yet."
        ) from exc
    except CertificateNotAvailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No certificate is available for this course yet."
        ) from exc
    return CertificateRead(download_url=download_url)


@faculty_router.post("/courses/{course_id}/certificate/upload-url", response_model=UploadUrlRead)
async def create_certificate_upload_url_endpoint(
    payload: CreateUploadUrlRequest,
    course: Course = Depends(require_course_faculty()),
) -> UploadUrlRead:
    try:
        file_key, upload_url = create_upload_url(
            course_id=course.id, filename=payload.filename, content_type=payload.content_type
        )
    except UnsupportedFileTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF/PNG/JPEG files are supported."
        ) from exc
    return UploadUrlRead(upload_url=upload_url, file_key=file_key)


@faculty_router.post("/courses/{course_id}/certificate", response_model=CertificateTemplateRead)
async def upsert_certificate_endpoint(
    payload: UpsertCertificateRequest,
    course: Course = Depends(require_course_faculty()),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CertificateTemplateRead:
    certificate = await upsert_certificate_template(
        db, course_id=course.id, uploaded_by=current_user.id, file_key=payload.file_key
    )
    return CertificateTemplateRead.model_validate(certificate)
