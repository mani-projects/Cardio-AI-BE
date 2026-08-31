import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_id: uuid.UUID | None
    sender_name: str
    sender_role: str
    body: str
    created_at: datetime


class ConversationRead(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    course_title: str
    messages: list[MessageRead]


class ConversationSummary(BaseModel):
    id: uuid.UUID
    learner_name: str
    learner_email: str
    last_message: str | None
    last_message_at: datetime


class SendMessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
