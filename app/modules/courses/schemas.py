import uuid

from pydantic import BaseModel, ConfigDict


class CourseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    title: str
    price_cents: int
    currency: str
    is_active: bool
