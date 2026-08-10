import uuid

from pydantic import BaseModel, ConfigDict

from app.modules.users.models import UserRole


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
