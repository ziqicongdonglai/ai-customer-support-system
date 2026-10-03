from uuid import UUID

from pydantic import BaseModel, Field


class SourceReference(BaseModel):
    document_id: str
    chunk_id: str
    source: str
    chunk_index: int
    score: float


class ChatResponse(BaseModel):
    conversation_id: UUID
    content: str
    model: str
    # 每次创建实例时，调用 list() 函数生成一个全新的空列表，分配给当前实例。
    sources: list[SourceReference] = Field(default_factory=list)