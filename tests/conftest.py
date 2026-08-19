import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable

import pytest_asyncio
from fastapi import BackgroundTasks
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import Base
from app.core.security import hash_password
from app.modules.auth.models import AccountClaimToken, EmailOtp, PasswordResetToken, RefreshToken
from app.modules.case_attempts.models import CaseAttempt, CaseAttemptMode, CaseFeedback
from app.modules.case_categories.models import CaseCategory
from app.modules.cases.models import Case
from app.modules.course_certificates.models import CourseCertificate
from app.modules.course_lectures.models import CourseLecture, LectureSource, LectureWatchState
from app.modules.course_resources.models import CourseResource, ResourceCategory
from app.modules.courses.models import Course, CourseFaculty
from app.modules.faculty_applications.models import FacultyApplication
from app.modules.registrations.models import Registration, RegistrationStatus
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
    # instead. Order matters: children before parents (Registration
    # references both Course and User, so it must go before either).
    async with session_factory() as cleanup_session:
        for model in (
            PasswordResetToken,
            EmailOtp,
            RefreshToken,
            AccountClaimToken,
            Registration,
            FacultyApplication,
            CourseFaculty,
            CaseFeedback,
            CaseAttempt,
            Case,
            CaseCategory,
            CourseResource,
            LectureWatchState,
            CourseLecture,
            CourseCertificate,
            Course,
            User,
        ):
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
        role: UserRole = UserRole.LEARNER,
        is_active: bool = True,
        is_email_verified: bool = True,
    ) -> User:
        user = User(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            role=role,
            is_active=is_active,
            is_email_verified=is_email_verified,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user

    return _make_user


@pytest_asyncio.fixture
def make_course(
    db_session: AsyncSession,
) -> Callable[..., Awaitable[Course]]:
    async def _make_course(
        slug: str = "1",
        title: str = "Test Course",
        price_cents: int = 25000,
        *,
        is_active: bool = True,
    ) -> Course:
        course = Course(slug=slug, title=title, price_cents=price_cents, is_active=is_active)
        db_session.add(course)
        await db_session.commit()
        await db_session.refresh(course)
        return course

    return _make_course


@pytest_asyncio.fixture
def make_course_faculty(
    db_session: AsyncSession,
) -> Callable[..., Awaitable[CourseFaculty]]:
    async def _make_course_faculty(
        course: Course,
        user: User,
        *,
        assigned_by: uuid.UUID | None = None,
    ) -> CourseFaculty:
        assignment = CourseFaculty(course_id=course.id, user_id=user.id, assigned_by=assigned_by)
        db_session.add(assignment)
        await db_session.commit()
        await db_session.refresh(assignment)
        return assignment

    return _make_course_faculty


@pytest_asyncio.fixture
def make_case_category(
    db_session: AsyncSession,
) -> Callable[..., Awaitable[CaseCategory]]:
    async def _make_case_category(
        course: Course,
        name: str = "CAD",
        *,
        is_active: bool = True,
        sort_order: int = 0,
    ) -> CaseCategory:
        category = CaseCategory(course_id=course.id, name=name, is_active=is_active, sort_order=sort_order)
        db_session.add(category)
        await db_session.commit()
        await db_session.refresh(category)
        return category

    return _make_case_category


@pytest_asyncio.fixture
def make_registration(
    db_session: AsyncSession,
) -> Callable[..., Awaitable[Registration]]:
    async def _make_registration(
        course: Course,
        user: User | None = None,
        *,
        status: RegistrationStatus = RegistrationStatus.PAID,
        full_name: str = "Test Learner",
        email: str = "learner@example.com",
    ) -> Registration:
        registration = Registration(
            course_id=course.id,
            user_id=user.id if user is not None else None,
            stripe_session_id=f"test-{uuid.uuid4()}",
            status=status,
            full_name=full_name,
            email=email,
            country="United Arab Emirates",
            city="Dubai",
            institution="Test Hospital",
            specialty="Cardiology",
        )
        db_session.add(registration)
        await db_session.commit()
        await db_session.refresh(registration)
        return registration

    return _make_registration


@pytest_asyncio.fixture
def make_case(
    db_session: AsyncSession,
) -> Callable[..., Awaitable[Case]]:
    async def _make_case(
        course: Course,
        category: CaseCategory,
        faculty: User,
        title: str = "Chest pain in a 54-year-old",
        report_text: str = "Patient presents with...",
        *,
        answer_key_findings: dict | None = None,
        imaging_reference: dict | None = None,
    ) -> Case:
        case = Case(
            course_id=course.id,
            category_id=category.id,
            faculty_id=faculty.id,
            title=title,
            report_text=report_text,
            answer_key_findings=answer_key_findings,
            imaging_reference=imaging_reference,
        )
        db_session.add(case)
        await db_session.commit()
        await db_session.refresh(case)
        return case

    return _make_case


@pytest_asyncio.fixture
def make_case_attempt(
    db_session: AsyncSession,
) -> Callable[..., Awaitable[CaseAttempt]]:
    async def _make_case_attempt(
        case: Case,
        learner: User,
        *,
        mode: CaseAttemptMode = CaseAttemptMode.FINDINGS,
    ) -> CaseAttempt:
        attempt = CaseAttempt(case_id=case.id, learner_id=learner.id, mode=mode)
        db_session.add(attempt)
        await db_session.commit()
        await db_session.refresh(attempt)
        return attempt

    return _make_case_attempt


@pytest_asyncio.fixture
def make_course_resource(
    db_session: AsyncSession,
) -> Callable[..., Awaitable[CourseResource]]:
    async def _make_course_resource(
        course: Course,
        *,
        category: ResourceCategory = ResourceCategory.GUIDELINES,
        title: str = "Test Guideline",
        subtitle: str | None = None,
        file_key: str | None = None,
        content_type: str = "application/pdf",
        file_size_bytes: int = 1024,
        uploaded_by: uuid.UUID | None = None,
    ) -> CourseResource:
        resource = CourseResource(
            course_id=course.id,
            category=category,
            title=title,
            subtitle=subtitle,
            file_key=file_key or f"course-resources/{course.id}/{uuid.uuid4()}.pdf",
            content_type=content_type,
            file_size_bytes=file_size_bytes,
            uploaded_by=uploaded_by,
        )
        db_session.add(resource)
        await db_session.commit()
        await db_session.refresh(resource)
        return resource

    return _make_course_resource


@pytest_asyncio.fixture
def make_course_lecture(
    db_session: AsyncSession,
) -> Callable[..., Awaitable[CourseLecture]]:
    async def _make_course_lecture(
        course: Course,
        *,
        title: str = "Coronary Anatomy & Variants",
        source: LectureSource = LectureSource.LINK,
        video_url: str | None = "https://example.com/video.mp4",
        file_key: str | None = None,
        group_label: str | None = None,
        sort_order: int = 0,
        created_by: uuid.UUID | None = None,
    ) -> CourseLecture:
        lecture = CourseLecture(
            course_id=course.id,
            title=title,
            source=source,
            video_url=video_url if source == LectureSource.LINK else None,
            file_key=file_key if source == LectureSource.UPLOAD else None,
            group_label=group_label,
            sort_order=sort_order,
            created_by=created_by,
        )
        db_session.add(lecture)
        await db_session.commit()
        await db_session.refresh(lecture)
        return lecture

    return _make_course_lecture


@pytest_asyncio.fixture
def make_course_certificate(
    db_session: AsyncSession,
) -> Callable[..., Awaitable[CourseCertificate]]:
    async def _make_course_certificate(
        course: Course,
        *,
        file_key: str | None = None,
        uploaded_by: uuid.UUID | None = None,
    ) -> CourseCertificate:
        certificate = CourseCertificate(
            course_id=course.id,
            file_key=file_key or f"course-certificates/{course.id}/{uuid.uuid4()}-certificate.pdf",
            uploaded_by=uploaded_by,
        )
        db_session.add(certificate)
        await db_session.commit()
        await db_session.refresh(certificate)
        return certificate

    return _make_course_certificate


@pytest_asyncio.fixture
def background_tasks() -> BackgroundTasks:
    return BackgroundTasks()
