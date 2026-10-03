from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.dependencies import get_message_repository
from app.repositories.message_repository import MessageRepository
from app.schemas.message import MessageResponse


router = APIRouter(
    prefix="/memory",
    tags=["Memory"],
)


@router.get(
    "/{conversation_id}/messages",
    response_model=list[MessageResponse]
)
async def get_messages(
    conversation_id: UUID,
    repo: MessageRepository = Depends(
        get_message_repository,
    ),
):
    messages = await repo.get_by_conversation_id(
        conversation_id,
    )

    return messages