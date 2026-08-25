import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import require_roles
from app.modules.case_categories.service import CaseCategoryNotFoundError, get_category
from app.modules.cases.models import CaseStatus
from app.modules.cases.schemas import (
    CaseLearnerRead,
    CaseRead,
    CreateCaseRequest,
    PaginatedCases,
    RejectCaseRequest,
    UpdateCaseRequest,
    UpdateCaseStatusRequest,
)
from app.modules.cases.service import (
    CaseAlreadyReviewedError,
    CaseNotEditableError,
    CaseNotFoundError,
    RejectionReasonRequiredError,
    approve_case,
    create_case,
    delete_case,
    get_case,
    get_case_for_learner,
    list_cases_admin,
    list_cases_for_course,
    list_my_cases,
    reject_case,
    update_and_resubmit_case,
    update_case_status,
)
from app.modules.courses.dependencies import require_course_faculty
from app.modules.courses.models import Course
from app.modules.registrations.dependencies import require_course_registration
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/cases", tags=["cases"])
faculty_router = APIRouter(prefix="/faculty", tags=["faculty"])
learner_router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("", response_model=PaginatedCases)
async def list_cases_endpoint(
    course_id: uuid.UUID | None = Query(None),
    category_id: uuid.UUID | None = Query(None),
    status_filter: CaseStatus | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> PaginatedCases:
    items, total = await list_cases_admin(
        db, course_id=course_id, category_id=category_id, status=status_filter, page=page, page_size=page_size
    )
    return PaginatedCases(
        items=[CaseRead.model_validate(item) for item in items], total=total, page=page, page_size=page_size
    )


@router.get("/{case_id}", response_model=CaseRead)
async def get_case_endpoint(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> CaseRead:
    try:
        case = await get_case(db, case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found") from exc
    return CaseRead.model_validate(case)


@router.post("/{case_id}/approve", response_model=CaseRead)
async def approve_case_endpoint(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> CaseRead:
    try:
        case = await get_case(db, case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found") from exc

    try:
        case = await approve_case(db, case, reviewer_id=admin.id)
    except CaseAlreadyReviewedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This case has already been reviewed.") from exc
    return CaseRead.model_validate(case)


@router.post("/{case_id}/reject", response_model=CaseRead)
async def reject_case_endpoint(
    case_id: uuid.UUID,
    payload: RejectCaseRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> CaseRead:
    try:
        case = await get_case(db, case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found") from exc

    try:
        case = await reject_case(db, case, reviewer_id=admin.id, reason=payload.reason)
    except CaseAlreadyReviewedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This case has already been reviewed.") from exc
    return CaseRead.model_validate(case)


@router.patch("/{case_id}/status", response_model=CaseRead)
async def update_case_status_endpoint(
    case_id: uuid.UUID,
    payload: UpdateCaseStatusRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> CaseRead:
    try:
        case = await get_case(db, case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found") from exc

    try:
        case = await update_case_status(
            db, case, status=payload.status, reviewer_id=admin.id, rejection_reason=payload.rejection_reason
        )
    except RejectionReasonRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="A rejection reason is required."
        ) from exc
    return CaseRead.model_validate(case)


@faculty_router.post(
    "/courses/{course_id}/categories/{category_id}/cases", response_model=CaseRead, status_code=status.HTTP_201_CREATED
)
async def submit_case_endpoint(
    category_id: uuid.UUID,
    payload: CreateCaseRequest,
    course: Course = Depends(require_course_faculty()),
    current_user: User = Depends(require_roles(UserRole.TEACHER, UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> CaseRead:
    try:
        category = await get_category(db, category_id)
    except CaseCategoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found") from exc
    if category.course_id != course.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    case = await create_case(
        db,
        course_id=course.id,
        category_id=category.id,
        faculty_id=current_user.id,
        title=payload.title,
        report_text=payload.report_text,
        answer_key_findings=payload.answer_key_findings,
        imaging_reference=payload.imaging_reference,
    )
    return CaseRead.model_validate(case)


@faculty_router.get("/my-cases", response_model=list[CaseRead])
async def list_my_cases_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.TEACHER)),
) -> list[CaseRead]:
    cases = await list_my_cases(db, current_user.id)
    return [CaseRead.model_validate(case) for case in cases]


@faculty_router.patch("/cases/{case_id}", response_model=CaseRead)
async def update_and_resubmit_case_endpoint(
    case_id: uuid.UUID,
    payload: UpdateCaseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.TEACHER)),
) -> CaseRead:
    try:
        case = await get_case(db, case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found") from exc
    if case.faculty_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This is not your case.")

    try:
        case = await update_and_resubmit_case(
            db,
            case,
            title=payload.title,
            report_text=payload.report_text,
            answer_key_findings=payload.answer_key_findings,
            imaging_reference=payload.imaging_reference,
        )
    except CaseNotEditableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending or rejected cases can be edited and resubmitted.",
        ) from exc
    return CaseRead.model_validate(case)


@faculty_router.delete("/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_case_endpoint(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.TEACHER)),
) -> None:
    try:
        case = await get_case(db, case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found") from exc
    if case.faculty_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This is not your case.")

    try:
        await delete_case(db, case)
    except CaseNotEditableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Only pending cases can be deleted."
        ) from exc


@learner_router.get("/{course_id}/cases", response_model=list[CaseLearnerRead])
async def list_course_cases_endpoint(
    category_id: uuid.UUID | None = Query(None),
    course: Course = Depends(require_course_registration()),
    db: AsyncSession = Depends(get_db),
) -> list[CaseLearnerRead]:
    cases = await list_cases_for_course(db, course.id, category_id=category_id)
    return [CaseLearnerRead.model_validate(case) for case in cases]


@learner_router.get("/{course_id}/cases/{case_id}", response_model=CaseLearnerRead)
async def get_course_case_endpoint(
    case_id: uuid.UUID,
    course: Course = Depends(require_course_registration()),
    db: AsyncSession = Depends(get_db),
) -> CaseLearnerRead:
    try:
        case = await get_case_for_learner(db, case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found") from exc
    if case.course_id != course.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return CaseLearnerRead.model_validate(case)
