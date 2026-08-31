import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.support.models import SupportRequestCategory


class CreateUploadUrlRequest(BaseModel):
    content_type: str


class UploadUrlRead(BaseModel):
    upload_url: str
    file_key: str


class SupportRequestCreate(BaseModel):
    category: SupportRequestCategory
    message: str = Field(min_length=1, max_length=4000)
    screenshot_key: str | None = None


class SupportRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: SupportRequestCategory
    message: str
    created_at: datetime


class SupportRequestListItem(BaseModel):
    id: uuid.UUID
    category: SupportRequestCategory
    message: str
    requester_name: str
    requester_email: str
    course_title: str
    screenshot_url: str | None
    created_at: datetime
