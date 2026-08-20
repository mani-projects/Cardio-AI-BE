import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.modules.course_resources.models import ResourceCategory, ResourceViewState
from app.modules.course_resources.service import (
    InvalidFileKeyError,
    UnsupportedFileTypeError,
    UploadNotFoundError,
    create_upload_url,
    delete_resource,
    finalize_resource,
    list_resources_for_course,
    mark_viewed,
)


def test_create_upload_url_rejects_non_pdf_content_type():
    with pytest.raises(UnsupportedFileTypeError):
        create_upload_url(course_id=uuid.uuid4(), content_type="image/png")


def test_create_upload_url_returns_prefixed_key_and_presigned_url():
    course_id = uuid.uuid4()

    with patch("app.core.storage.generate_presigned_put_url", return_value="https://s3.example.com/put") as mock_put:
        file_key, upload_url = create_upload_url(course_id=course_id, content_type="application/pdf")

    assert file_key.startswith(f"course-resources/{course_id}/")
    assert file_key.endswith(".pdf")
    assert upload_url == "https://s3.example.com/put"
    mock_put.assert_called_once_with(file_key, "application/pdf")


async def test_finalize_resource_rejects_key_from_a_different_course(db_session, make_course):
    course = await make_course(slug="1")
    other_course_id = uuid.uuid4()
    bad_key = f"course-resources/{other_course_id}/{uuid.uuid4()}.pdf"

    with pytest.raises(InvalidFileKeyError):
        await finalize_resource(
            db_session,
            course_id=course.id,
            category=ResourceCategory.GUIDELINES,
            title="Guideline",
            subtitle=None,
            file_key=bad_key,
            content_type="application/pdf",
            uploaded_by=None,
        )


async def test_finalize_resource_raises_when_upload_not_found_in_s3(db_session, make_course):
    course = await make_course(slug="1")
    file_key = f"course-resources/{course.id}/{uuid.uuid4()}.pdf"

    with patch("app.core.storage.head_object", new=AsyncMock(return_value=None)):
        with pytest.raises(UploadNotFoundError):
            await finalize_resource(
                db_session,
                course_id=course.id,
                category=ResourceCategory.GUIDELINES,
                title="Guideline",
                subtitle=None,
                file_key=file_key,
                content_type="application/pdf",
                uploaded_by=None,
            )


async def test_finalize_resource_creates_row_with_size_from_s3_head(db_session, make_course, make_user):
    course = await make_course(slug="1")
    faculty = await make_user(email="fac@example.com")
    file_key = f"course-resources/{course.id}/{uuid.uuid4()}.pdf"

    with patch("app.core.storage.head_object", new=AsyncMock(return_value={"ContentLength": 54321})):
        resource = await finalize_resource(
            db_session,
            course_id=course.id,
            category=ResourceCategory.TEMPLATES,
            title="Report Template",
            subtitle="Fillable PDF",
            file_key=file_key,
            content_type="application/pdf",
            uploaded_by=faculty.id,
        )

    assert resource.file_size_bytes == 54321
    assert resource.category == ResourceCategory.TEMPLATES
    assert resource.uploaded_by == faculty.id


async def test_list_resources_for_course_filters_by_category(db_session, make_course, make_course_resource):
    course = await make_course(slug="1")
    guideline = await make_course_resource(course, category=ResourceCategory.GUIDELINES)
    await make_course_resource(course, category=ResourceCategory.TEMPLATES)

    resources = await list_resources_for_course(db_session, course.id, category=ResourceCategory.GUIDELINES)

    assert [r.id for r in resources] == [guideline.id]


async def test_list_resources_for_course_scoped_to_course(db_session, make_course, make_course_resource):
    course_a = await make_course(slug="1")
    course_b = await make_course(slug="2")
    resource_a = await make_course_resource(course_a)
    await make_course_resource(course_b)

    resources = await list_resources_for_course(db_session, course_a.id)

    assert [r.id for r in resources] == [resource_a.id]


async def test_delete_resource_removes_row_even_if_s3_delete_fails(db_session, make_course, make_course_resource):
    course = await make_course(slug="1")
    resource = await make_course_resource(course)

    with patch("app.core.storage.delete_object", new=AsyncMock(return_value=None)) as mock_delete:
        await delete_resource(db_session, resource)

    mock_delete.assert_called_once_with(resource.file_key)
    remaining = await list_resources_for_course(db_session, course.id)
    assert remaining == []


async def test_mark_viewed_is_idempotent(db_session, make_course, make_course_resource, make_user):
    course = await make_course(slug="1")
    learner = await make_user(email="learner-viewed@example.com")
    resource = await make_course_resource(course)

    await mark_viewed(db_session, resource_id=resource.id, user_id=learner.id)
    await mark_viewed(db_session, resource_id=resource.id, user_id=learner.id)

    rows = (
        (
            await db_session.execute(
                select(ResourceViewState).where(
                    ResourceViewState.resource_id == resource.id, ResourceViewState.user_id == learner.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_delete_resource_cascades_view_state(db_session, make_course, make_course_resource, make_user):
    course = await make_course(slug="1")
    learner = await make_user(email="learner-viewed2@example.com")
    resource = await make_course_resource(course)
    await mark_viewed(db_session, resource_id=resource.id, user_id=learner.id)

    with patch("app.core.storage.delete_object", new=AsyncMock(return_value=None)):
        await delete_resource(db_session, resource)

    remaining = (
        (await db_session.execute(select(ResourceViewState).where(ResourceViewState.resource_id == resource.id)))
        .scalars()
        .all()
    )
    assert remaining == []
