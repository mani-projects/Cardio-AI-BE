import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession
import jwt

from app.core.database import get_db
from app.core.security import decode_token
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.service import get_user_by_id
from app.modules.courses.models import Course
from app.modules.mentor_chat.connection_manager import manager
from app.modules.mentor_chat.models import Conversation
from app.modules.mentor_chat.schemas import (
    ConversationRead,
    ConversationSummary,
    MessageRead,
    SendMessageRequest,
)
from app.modules.mentor_chat.service import (
    ConversationNotFoundError,
    get_conversation,
    get_or_create_conversation,
    list_conversations_for_course,
    list_messages,
    send_message,
    user_can_access_conversation,
)
from app.modules.registrations.dependencies import require_course_registration
from app.modules.courses.dependencies import get_course_or_404
from app.modules.courses.service import is_course_faculty
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/courses", tags=["courses"])
faculty_router = APIRouter(prefix="/faculty", tags=["faculty"])
ws_router = APIRouter(tags=["mentor-chat-ws"])


# Deliberately stricter than the shared require_course_faculty() dependency
# (which lets admin through as an oversight bypass everywhere else) — this
# chat is a direct learner<->faculty channel admin has no visibility into,
# by product decision, so admin is excluded here even though they otherwise
# can manage every course.
async def require_teacher_course_faculty(
    course_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Course:
    course = await get_course_or_404(course_id, db)
    if current_user.role != UserRole.TEACHER or not await is_course_faculty(
        db, course_id=course.id, user_id=current_user.id
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return course


@router.get("/{course_id}/conversation", response_model=ConversationRead)
async def get_my_conversation_endpoint(
    course: Course = Depends(require_course_registration()),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationRead:
    conversation = await get_or_create_conversation(db, course=course, learner=current_user)
    messages = await list_messages(db, conversation.id)
    return ConversationRead(
        id=conversation.id,
        course_id=course.id,
        course_title=course.title,
        messages=[MessageRead.model_validate(m) for m in messages],
    )


@router.post("/{course_id}/conversation/messages", response_model=MessageRead, status_code=status.HTTP_201_CREATED)
async def send_my_message_endpoint(
    payload: SendMessageRequest,
    course: Course = Depends(require_course_registration()),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageRead:
    conversation = await get_or_create_conversation(db, course=course, learner=current_user)
    message = await send_message(db, conversation=conversation, sender=current_user, body=payload.body)
    read = MessageRead.model_validate(message)
    await manager.broadcast(conversation.id, read.model_dump(mode="json"))
    return read


@faculty_router.get("/courses/{course_id}/conversations", response_model=list[ConversationSummary])
async def list_course_conversations_endpoint(
    course: Course = Depends(require_teacher_course_faculty),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationSummary]:
    rows = await list_conversations_for_course(db, course.id)
    return [ConversationSummary(**row) for row in rows]


async def _faculty_conversation_or_403(
    conversation_id: uuid.UUID, current_user: User, db: AsyncSession
) -> Conversation:
    try:
        conversation = await get_conversation(db, conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from exc
    if not await user_can_access_conversation(db, conversation=conversation, user=current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return conversation


@faculty_router.get("/conversations/{conversation_id}/messages", response_model=list[MessageRead])
async def list_conversation_messages_endpoint(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MessageRead]:
    conversation = await _faculty_conversation_or_403(conversation_id, current_user, db)
    messages = await list_messages(db, conversation.id)
    return [MessageRead.model_validate(m) for m in messages]


@faculty_router.post(
    "/conversations/{conversation_id}/messages", response_model=MessageRead, status_code=status.HTTP_201_CREATED
)
async def send_conversation_message_endpoint(
    conversation_id: uuid.UUID,
    payload: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageRead:
    conversation = await _faculty_conversation_or_403(conversation_id, current_user, db)
    message = await send_message(db, conversation=conversation, sender=current_user, body=payload.body)
    read = MessageRead.model_validate(message)
    await manager.broadcast(conversation.id, read.model_dump(mode="json"))
    return read


# Query-param token, not a header — the browser WebSocket API can't set
# custom headers on the handshake. The token is the learner/faculty's own
# short-lived (30 min) access token, the same one already used for every
# other API call; nothing new is minted for this.
@ws_router.websocket("/ws/conversations/{conversation_id}")
async def conversation_socket(
    websocket: WebSocket,
    conversation_id: uuid.UUID,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise ValueError("not an access token")
        current_user = await get_user_by_id(db, uuid.UUID(payload["sub"]))
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if current_user is None or not current_user.is_active:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        conversation = await get_conversation(db, conversation_id)
    except ConversationNotFoundError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if not await user_can_access_conversation(db, conversation=conversation, user=current_user):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(conversation_id, websocket)
    try:
        while True:
            # Messages are sent via the REST endpoints (durable, retriable);
            # this loop only exists to detect disconnects and keep the
            # connection open for the server -> client broadcast direction.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(conversation_id, websocket)
