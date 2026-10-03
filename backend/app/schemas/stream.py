from uuid import UUID

from pydantic import BaseModel

from app.schemas.responses import SourceReference

class ChatStreamEvent(BaseModel):
    type: str
    
    conversation_id: UUID | None = None

    content: str | None = None

    sources: list[SourceReference] | None = None

    kind: str | None = None
