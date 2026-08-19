import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from app.modules.course_lectures.models import LectureSource

if TYPE_CHECKING:
    from app.modules.course_lectures.models import CourseLecture


class CreateUploadUrlRequest(BaseModel):
    content_type: str = Field(min_length=1, max_length=100)


class UploadUrlRead(BaseModel):
    upload_url: str
    file_key: str


class CreateLectureRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    source: LectureSource
    video_url: str | None = Field(default=None, max_length=1024)
    file_key: str | None = Field(default=None, max_length=1024)
    group_label: str | None = Field(default=None, max_length=255)
    sort_order: int = 0


class UpdateLectureRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    video_url: str | None = Field(default=None, max_length=1024)
    file_key: str | None = Field(default=None, max_length=1024)
    group_label: str | None = Field(default=None, max_length=255)
    sort_order: int | None = None


# Faculty-facing management view — no presigned URL needed for a list/edit UI.
class CourseLectureFacultyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    course_id: uuid.UUID
    title: str
    source: LectureSource
    video_url: str | None
    file_key: str | None
    group_label: str | None
    sort_order: int
    created_at: datetime


# Learner-facing playback view — carries a ready-to-use playback URL (the
# stored link, or a freshly minted presigned GET for an uploaded video) and
# this learner's own watch state.
class CourseLectureRead(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    title: str
    source: LectureSource
    group_label: str | None
    sort_order: int
    created_at: datetime
    playback_url: str
    watched: bool

    @classmethod
    def from_lecture(cls, lecture: "CourseLecture", playback_url: str, watched: bool) -> "CourseLectureRead":
        return cls(
            id=lecture.id,
            course_id=lecture.course_id,
            title=lecture.title,
            source=lecture.source,
            group_label=lecture.group_label,
            sort_order=lecture.sort_order,
            created_at=lecture.created_at,
            playback_url=playback_url,
            watched=watched,
        )
