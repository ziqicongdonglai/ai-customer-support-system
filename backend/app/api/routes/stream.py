import asyncio
import logging
import time
from uuid import UUID
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.schemas.requests import ChatRequest
from app.core.dependencies import get_chat_service
from app.core.sse import format_sse
from app.core.sse_events import SSEEvent
from app.services.chat_service import ChatService

from app.core.exceptions import (
    ProviderException,
    ConfigurationException,
)
from app.core.context import request_id_context

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)

@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    service: ChatService = Depends(
        get_chat_service
    ),
):
    # 使用 StreamingResponse 返回流式响应
    return StreamingResponse(
        generate_stream(
            service,
            request.message,
            request.conversation_id,
            request.use_rag,
            request_id_context.get(),
        ),
        media_type="text/event-stream",
    )

async def generate_stream(
    service: ChatService,
    message: str,
    conversation_id: UUID | None,
    use_rag: bool = False,
    request_id: str | None = None,
):
    # StreamingResponse 在 route 返回后仍会继续迭代 body generator；
    # 这里显式重绑 request_id，保证 SSE 生命周期内的日志仍关联原始 HTTP request。
    context_token = (
        request_id_context.set(request_id)
        if request_id is not None
        else None
    )
    stream = _generate_stream(service, message, conversation_id, use_rag)
    try:
        async for event in stream:
            yield event
    finally:
        # 无论正常、异常、取消或 consumer 提前关闭，都必须恢复原 ContextVar，
        # 避免 request_id 泄漏到后续 execution。
        try:
            await stream.aclose()
        finally:
            if context_token is not None:
                request_id_context.reset(context_token)


async def _generate_stream(
    service: ChatService,
    message: str,
    conversation_id: UUID | None,
    use_rag: bool = False,
):
    started = time.perf_counter()
    outcome = "completed"
    logger.info("event=chat.sse.started")
    try:

        async for event in service.stream_chat(
            message,
            conversation_id,
            use_rag=use_rag,
        ):
            if event.type == "conversation":
            
                # 标识一次流式请求开始
                yield format_sse(
                    SSEEvent.START,
                    {
                        "conversation_id": str(
                            event.conversation_id
                        )
                    },
                )

            elif event.type == "token":

                yield format_sse(
                    SSEEvent.TOKEN,
                    {
                        "content": event.content,
                    },
                )
            
            elif event.type == "sources":

                yield format_sse(
                    SSEEvent.SOURCES,
                    {
                        "sources": [
                            source.model_dump()
                            for source in event.sources or []
                        ]
                    },
                )

            elif event.type == "workflow_handoff":
                # workflow_handoff 是 transient structured UI signal，不是 Workflow State；
                # 保留独立 SSE event 可避免前端从 LLM 自然语言中猜测控制意图。
                yield format_sse(
                    SSEEvent.WORKFLOW_HANDOFF,
                    {"kind": event.kind},
                )

    except asyncio.CancelledError:
        # Client 已经断开，不再发送任何 SSE event。
        logger.info(
            "event=chat.sse.completed outcome=cancelled duration_ms=%.3f",
            (time.perf_counter() - started) * 1000,
        )
        raise

    except GeneratorExit:
        logger.info(
            "event=chat.sse.completed outcome=disconnected duration_ms=%.3f",
            (time.perf_counter() - started) * 1000,
        )
        raise

    except ProviderException as exc:
        outcome = "handled_provider_error"
        yield format_sse(
            SSEEvent.ERROR,
            {
                "code": 1001,
                "message": str(exc),
            },
        )

    except ConfigurationException as exc:
        outcome = "handled_configuration_error"
        yield format_sse(
            SSEEvent.ERROR,
            {
                "code": 1002,
                "message": str(exc),
            },
        )

    except Exception:
        logger.exception(
            "event=chat.sse.completed outcome=unexpected_error duration_ms=%.3f",
            (time.perf_counter() - started) * 1000,
        )
        raise

    # 只有正常完成或已经转换为 SSE ERROR 的业务异常，
    # 才会执行到这里。
    yield format_sse(SSEEvent.END, {})
    logger.info(
        "event=chat.sse.completed outcome=%s duration_ms=%.3f",
        outcome,
        (time.perf_counter() - started) * 1000,
    )
