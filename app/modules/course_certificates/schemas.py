import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CreateUploadUrlRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)


class UploadUrlRead(BaseModel):
    upload_url: str
    file_key: str


class UpsertCertificateRequest(BaseModel):
    file_key: str = Field(min_length=1, max_length=1024)


class CertificateTemplateRead(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    file_key: str
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CertificateRead(BaseModel):
    download_url: str
