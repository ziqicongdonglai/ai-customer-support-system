from uuid import UUID

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConversationResponse(BaseModel):

    id: UUID

    title: str | None

    created_at: datetime

    updated_at: datetime

    model_config = ConfigDict(
        # 不要只读取 dict，也可以读取对象属性。
        from_attributes=True
    )

class ConversationUpdateRequest(BaseModel):

    title: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Conversation title",
    )

class ConversationListResponse(BaseModel):

    conversations: list[ConversationResponse]