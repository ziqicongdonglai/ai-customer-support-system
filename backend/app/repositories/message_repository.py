from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message


class MessageRepository:

    def __init__(
        self,
        db: AsyncSession,
    ):
        self.db = db


    async def create(
        self,
        message: Message,
    ) -> Message:

        self.db.add(message)

        await self.db.commit()

        # 重新从数据库加载 让 Python 对象同步
        await self.db.refresh(message)

        return message


    async def get_by_conversation_id(
        self,
        conversation_id: UUID,
    ) -> list[Message]:

        result = await self.db.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation_id
            )
            .order_by(
                Message.created_at
            )
        )

        # scalars 只取 ORM 对象；all 变为列表
        return result.scalars().all()

    async def update(
        self,
        message: Message,
    ) -> Message:

        await self.db.commit()

        await self.db.refresh(message)

        return message

    async def get_paginated(
        self,
        conversation_id: UUID,
        offset: int,
        limit: int,
    ) -> list[Message]:

        result = await self.db.execute(
            select(Message)
            .where(
                Message.conversation_id
                == conversation_id
            )
            .order_by(
                Message.created_at.desc(),
                Message.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )

        messages = list(
            result.scalars().all()
        )

        messages.reverse()

        return messages

    async def count_by_conversation_id(
        self,
        conversation_id: UUID,
    ) -> int:

        result = await self.db.execute(
            select(
                func.count(Message.id)
            )
            .where(
                Message.conversation_id == conversation_id
            )
        )

        return result.scalar_one()