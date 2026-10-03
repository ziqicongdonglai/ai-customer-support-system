from fastapi import APIRouter, Depends

from app.core.dependencies import get_chat_service
from app.schemas.requests import ChatRequest
from app.schemas.responses import ChatResponse
from app.services.chat_service import ChatService


router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
) -> ChatResponse:

    return await service.chat(
        request.message,
        request.conversation_id,
        use_rag=request.use_rag,
    )