from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation

class ConversationRepository:

    def __init__(
        self,
        db: AsyncSession,
    ):
        self.db = db

    async def create(
        self,
        conversation: Conversation,
    ) -> Conversation:

        self.db.add(conversation)

        await self.db.commit()

        await self.db.refresh(
            conversation
        )

        return conversation

    async def get_by_id(
        self,
        conversation_id: UUID,
    ) -> Conversation | None:
        return await self.db.get(
            Conversation,
            conversation_id,
        )

    async def get_all(
        self,
    ) -> list[Conversation]:

        result = await self.db.execute(
            select(Conversation)
            .order_by(
                Conversation.created_at.desc()
            )
        )

        return result.scalars().all()

    async def delete(
        self,
        conversation: Conversation,
    ) -> None:
        await self.db.delete(
            conversation
        )

        await self.db.commit()

    async def update(
        self,
        conversation: Conversation,
    ) -> Conversation:

        await self.db.commit()

        await self.db.refresh(
            conversation
        )

        return conversation