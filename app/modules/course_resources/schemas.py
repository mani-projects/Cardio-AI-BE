import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.modules.course_resources.models import ResourceCategory

if TYPE_CHECKING:
    from app.modules.course_resources.models import CourseResource


class CreateUploadUrlRequest(BaseModel):
    category: ResourceCategory
    title: str = Field(min_length=1, max_length=255)
    subtitle: str | None = Field(default=None, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)


class UploadUrlRead(BaseModel):
    upload_url: str
    file_key: str


class FinalizeResourceRequest(BaseModel):
    category: ResourceCategory
    title: str = Field(min_length=1, max_length=255)
    subtitle: str | None = Field(default=None, max_length=255)
    file_key: str = Field(min_length=1, max_length=1024)
    content_type: str = Field(min_length=1, max_length=100)


class CourseResourceRead(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    category: ResourceCategory
    title: str
    subtitle: str | None
    content_type: str
    file_size_bytes: int
    created_at: datetime
    download_url: str | None = None

    @classmethod
    def from_resource(cls, resource: "CourseResource", download_url: str | None = None) -> "CourseResourceRead":
        return cls(
            id=resource.id,
            course_id=resource.course_id,
            category=resource.category,
            title=resource.title,
            subtitle=resource.subtitle,
            content_type=resource.content_type,
            file_size_bytes=resource.file_size_bytes,
            created_at=resource.created_at,
            download_url=download_url,
        )
