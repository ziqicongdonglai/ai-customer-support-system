from uuid import UUID

from pydantic import BaseModel, Field

class ChatRequest(BaseModel):

    conversation_id: UUID | None = Field(
        default=None,
        description="会话ID，新会话时为空",
    )
    
    message: str = Field(
        ..., 
        min_length=1,
        max_length=4000,
        description="用户发送的聊天内容",
        examples=["请介绍一下 FastAPI"],
)
    use_rag: bool = Field(
        default=False,
        description="是否启用 RAG 知识检索",
    )