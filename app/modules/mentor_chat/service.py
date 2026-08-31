import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.courses.models import Course
from app.modules.courses.service import is_course_faculty
from app.modules.mentor_chat.models import Conversation, Message
from app.modules.users.models import User, UserRole


class MentorChatError(Exception):
    """Base class for mentor-chat failures."""


class ConversationNotFoundError(MentorChatError):
    pass


async def get_or_create_conversation(db: AsyncSession, *, course: Course, learner: User) -> Conversation:
    stmt = select(Conversation).where(Conversation.course_id == course.id, Conversation.learner_id == learner.id)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing

    conversation = Conversation(
        course_id=course.id,
        learner_id=learner.id,
        learner_name=learner.full_name,
        learner_email=learner.email,
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def get_conversation(db: AsyncSession, conversation_id: uuid.UUID) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise ConversationNotFoundError(conversation_id)
    return conversation


async def user_can_access_conversation(db: AsyncSession, *, conversation: Conversation, user: User) -> bool:
    # Deliberately excludes admin — this is a direct learner<->faculty
    # channel only, see the product decision behind this feature.
    if user.role == UserRole.LEARNER:
        return conversation.learner_id == user.id
    if user.role == UserRole.TEACHER:
        return await is_course_faculty(db, course_id=conversation.course_id, user_id=user.id)
    return False


async def list_messages(db: AsyncSession, conversation_id: uuid.UUID) -> list[Message]:
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def send_message(db: AsyncSession, *, conversation: Conversation, sender: User, body: str) -> Message:
    message = Message(
        conversation_id=conversation.id,
        sender_id=sender.id,
        sender_name=sender.full_name,
        sender_role=sender.role.value,
        body=body,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


async def list_conversations_for_course(db: AsyncSession, course_id: uuid.UUID) -> list[dict]:
    """One row per learner thread in this course, newest activity first."""
    stmt = (
        select(Conversation)
        .where(Conversation.course_id == course_id)
        .options(selectinload(Conversation.messages))
    )
    conversations = (await db.execute(stmt)).scalars().all()

    rows: list[dict] = []
    for conversation in conversations:
        last = max(conversation.messages, key=lambda m: m.created_at, default=None)
        rows.append(
            {
                "id": conversation.id,
                "learner_name": conversation.learner_name,
                "learner_email": conversation.learner_email,
                "last_message": last.body if last else None,
                "last_message_at": last.created_at if last else conversation.created_at,
            }
        )
    rows.sort(key=lambda r: r["last_message_at"], reverse=True)
    return rows
