from uuid import UUID

from app.core.exceptions import ConversationNotFoundException

from app.repositories.conversation_repository import (
    ConversationRepository,
)

from app.repositories.message_repository import (
    MessageRepository,
)

from app.schemas.conversation import (
    ConversationResponse,
)

from app.schemas.message import (
    MessageResponse,
    MessageListResponse,
    PaginationResponse,
)

class ConversationService:

    def __init__(
        self,
        conversation_repo: ConversationRepository,
        message_repo: MessageRepository,
    ):
        self.conversation_repo = conversation_repo
        self.message_repo = message_repo

    async def get_conversations(
        self,
    ) -> list[ConversationResponse]:

        conversations = await(
            self.conversation_repo.get_all()
        )

        return [
            # ConversationResponse.model_validate
            # SQLAlchemy ORM
            # ↓
            # Pydantic Schema
            ConversationResponse.model_validate(
                item
            )
            for item in conversations
        ]

    async def get_messages(
        self,
        conversation_id: UUID,
    ) -> list[MessageResponse]:

        conversation = await (
            self.conversation_repo.get_by_id(
                conversation_id
            )
        )

        if conversation is None:
            raise ConversationNotFoundException(
                "Conversation not found"
            )

        messages = await (
            self.message_repo.get_by_conversation_id(
                conversation_id
            )
        )

        return [
            MessageResponse.model_validate(
                item
            )
            for item in messages
        ]

    async def get_conversation(
        self,
        conversation_id: UUID,
    ) -> ConversationResponse:
        conversation = await self.conversation_repo.get_by_id(
            conversation_id
        )

        if conversation is None:
            raise ConversationNotFoundException(
                "Conversation not found"
            )
        
        return ConversationResponse.model_validate(
            conversation
        )

    async def delete_conversation(
        self,
        conversation_id: UUID,
    ) -> None:

        conversation = await self.conversation_repo.get_by_id(
            conversation_id
        )

        if conversation is None:
            raise ConversationNotFoundException(
                "Conversation not found"
            )

        await self.conversation_repo.delete(
            conversation
        )

    async def get_messages_paginated(
        self,
        conversation_id: UUID,
        page: int,
        page_size: int,
    ) -> MessageListResponse:

        conversation = await self.conversation_repo.get_by_id(
            conversation_id
        )

        if conversation is None:
            raise ConversationNotFoundException(
                "Conversation not found"
            )

        offset = (page - 1) * page_size

        messages = await self.message_repo.get_paginated(
            conversation_id,
            offset,
            page_size,
        )

        total = await self.message_repo.count_by_conversation_id(
            conversation_id
        )

        return MessageListResponse(
            messages=[
                MessageResponse.model_validate(
                    item
                )
                for item in messages
            ],
            pagination=PaginationResponse(
                page = page,
                page_size=page_size,
                total=total,
            )
        )

    async def update_conversation(
        self,
        conversation_id: UUID,
        title: str,
    ) -> ConversationResponse:

        conversation = await self.conversation_repo.get_by_id(
            conversation_id
        )

        if conversation is None:
            raise ConversationNotFoundException(
                "Conversation not found"
            )

        conversation.title = title

        conversation = await self.conversation_repo.update(
            conversation
        )

        return ConversationResponse.model_validate(
            conversation
        )