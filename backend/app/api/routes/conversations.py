from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import (
    get_conversation_service,
)

from app.schemas.conversation import (
    ConversationListResponse,
    ConversationResponse,
    ConversationUpdateRequest,
)

from app.schemas.message import (
    MessageListResponse,
)

from app.services.conversation_service import (
    ConversationService,
)

router = APIRouter(
    prefix="/conversations",
    tags=["Conversation"],
)

@router.get(
    "",
    response_model=ConversationListResponse,
)
async def get_conversations(
    service: ConversationService = Depends(
        get_conversation_service
    ),
):
    conversations = await service.get_conversations()
    
    return ConversationListResponse(
        conversations=conversations,
    )

@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
)
async def get_conversation(
    conversation_id: UUID,
    service: ConversationService = Depends(
        get_conversation_service
    )
):
    return await service.get_conversation(
        conversation_id
    )

@router.get(
    "/{conversation_id}/messages",
    response_model=MessageListResponse,
)
async def get_messages(
    conversation_id: UUID,
    page: int = Query(
        1,
        ge=1,
    ),
    page_size: int = Query(
        20,
        ge=1,
        le=100,
    ),
    service: ConversationService = Depends(
        get_conversation_service
    ),
):

    return await service.get_messages_paginated(
        conversation_id,
        page,
        page_size,
    )

@router.delete(
    "/{conversation_id}",
)
async def delete_conversation(
    conversation_id: UUID,
    service: ConversationService = Depends(
        get_conversation_service
    )
):
    await service.delete_conversation(
        conversation_id
    )

    return {
        "message": "Conversation deleted"
    }

@router.patch(
    "/{conversation_id}",
    response_model=ConversationResponse,
)
async def update_conversation(
    conversation_id: UUID,
    request: ConversationUpdateRequest,
    service: ConversationService = Depends(
        get_conversation_service
    )
):
    
    return await service.update_conversation(
        conversation_id,
        request.title,
    )