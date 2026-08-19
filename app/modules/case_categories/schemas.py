import uuid

from pydantic import BaseModel, ConfigDict


class CaseCategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    course_id: uuid.UUID
    name: str
    is_active: bool
    sort_order: int


class CreateCategoryRequest(BaseModel):
    name: str


class UpdateCategoryRequest(BaseModel):
    name: str | None = None
    is_active: bool | None = None
