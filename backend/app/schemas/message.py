from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.responses import SourceReference

class MessageResponse(BaseModel):

    id: UUID

    conversation_id: UUID

    role: str

    content: str

    model: str | None

    status: str

    created_at: datetime

    sources: list[SourceReference] = Field(default_factory=list)

    model_config = ConfigDict(
        # 不要只读取 dict，也可以读取对象属性。
        from_attributes=True
    )

class PaginationResponse(BaseModel):

    page: int

    page_size: int

    total: int

class MessageListResponse(BaseModel):

    messages: list[MessageResponse]

    pagination: PaginationResponse