import asyncio
import json
import logging
import ntpath
import time
from datetime import datetime, timezone
from typing import AsyncGenerator
from uuid import UUID

from anyio import CancelScope

from app.core.config import settings
from app.core.demo_principal import DEMO_CUSTOMER_ID

from app.models.conversation import Conversation
from app.models.message import (
    Message,
    MessageStatus,
)
from app.schemas.stream import ChatStreamEvent

from app.providers.base import BaseLLMProvider, ContentDelta, ToolCallComplete

from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository

from app.schemas.responses import (
    ChatResponse,
    SourceReference,
)

from app.core.exceptions import (
    ConfigurationException,
    ConversationNotFoundException,
    NotFoundException,
    ProviderException,
)

from app.services.context_builder import ContextBuilder
from app.services.business_service import BusinessService

from app.rag.retriever import BaseRetriever

from app.rag.models import RetrievedChunk

logger = logging.getLogger(__name__)


# Demo 身份由应用控制，绝不能接受模型参数中的 customer_id 作为可信身份。
# 该指令约束模型选择与安全表述；真正的 Tool 与 ownership 校验仍由应用执行。
TOOL_STREAM_INSTRUCTION = (
    "For shipment status or logistics-exception questions, call get_shipment_status. "
    "For current-case return eligibility questions, call request_return_eligibility_check. "
    "That Tool only prepares the application's return eligibility interaction; it does not "
    "start a Workflow or determine eligibility. After handoff_ready, direct the user to click "
    "Start check and choose the purchase. Do not claim that a Workflow has started, a purchase "
    "was selected, or that a return is eligible, ineligible, approved, or denied. Never infer "
    "a current-case return result from Knowledge Context. "
    "If you call either Tool, emit no assistant content before the Tool Call. "
    "Treat logistics_exception.decision in the Tool result as authoritative for the current case; "
    "use Knowledge Context only to explain that decision, never to override it. "
    "If the result says available=false, only say that the shipment is unavailable; "
    "do not infer whether it is missing or belongs to someone else. "
    "For unrelated questions, answer normally without mentioning this Tool or shipment capabilities."
)
SHIPMENT_STATUS_TOOL = {
    "type": "function",
    "function": {
        "name": "get_shipment_status",
        "description": (
            "Get the current status and logistics-exception decision for a shipment "
            "belonging to the signed-in customer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "shipment_id": {
                    "type": "string",
                    "format": "uuid",
                    "description": "Shipment UUID shown to the customer.",
                }
            },
            "required": ["shipment_id"],
            "additionalProperties": False,
        },
    },
}

# LLM 只负责识别“用户想检查退货资格”的 semantic routing；该 handoff Tool
# 既不创建 Workflow、不判断 eligibility，也不修改任何 Business State。
RETURN_ELIGIBILITY_HANDOFF_TOOL = {
    "type": "function",
    "function": {
        "name": "request_return_eligibility_check",
        "description": (
            "Prepare the application's return eligibility interaction. "
            "This does not start a workflow or determine eligibility."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
}


class ChatService:

    def __init__(
        self,
        provider: BaseLLMProvider,
        conversation_repo: ConversationRepository,
        message_repo: MessageRepository,
        context_builder: ContextBuilder,
        retriever: BaseRetriever,
        business_service: BusinessService,
    ):
        self.provider = provider
        self.conversation_repo = conversation_repo
        self.message_repo = message_repo
        self.context_builder = context_builder
        self.retriever = retriever
        self.business_service = business_service


    async def chat(
        self,
        message: str,
        conversation_id: UUID | None,
        use_rag: bool = False,
    ) -> ChatResponse:

        conversation = await self._prepare_conversation(
            message, 
            conversation_id,
        )

        retrieved_chunks: list[RetrievedChunk] = []

        if use_rag:
            retrieved_chunks = self.retriever.retrieve(message)

        # 3. 查询历史消息
        # 4. 转换 LLM messages
        context_result = await self.context_builder.build(
            conversation.id,
            retrieved_chunks=retrieved_chunks,
        )

        messages = context_result.messages

        used_chunks = context_result.used_chunks

        sources = self._build_sources(used_chunks=used_chunks)

        # 5. 创建 空 AI 回复
        assistant_message = await self._create_assistant_message(
            conversation.id,
            sources,
        )

        try:

            # 6. 调用模型

            response_text = await self.provider.chat(
                messages
            )

            assistant_message.content = response_text

            assistant_message.status = MessageStatus.COMPLETED

            # 7. 更新 AI 实际回复的内容

            await self.message_repo.update(
                assistant_message
            )

        except Exception:
            assistant_message.status = MessageStatus.FAILED

            await self.message_repo.update(
                assistant_message
            )

            raise

                # 8. 返回

        return ChatResponse(
            conversation_id=conversation.id,
            content=response_text,
            model=settings.deepseek_model,
            sources=sources,
        )

    async def stream_chat(
        self,
        message: str,
        conversation_id: UUID | None,
        use_rag: bool = False,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        execution_started = time.perf_counter()
        # 记录当前执行阶段，使外层异常日志能定位 AI / Tool / persistence 的失败位置。
        failure_stage = "setup"
        assistant_message = None
        logger.info(
            "event=chat.execution.started rag_enabled=%s",
            str(use_rag).lower(),
        )
        try:
            conversation = await self._prepare_conversation(message, conversation_id)

            failure_stage = "retrieval"
            retrieval_started = time.perf_counter()
            retrieved_chunks: list[RetrievedChunk] = []
            if use_rag:
                retrieved_chunks = self.retriever.retrieve(message)
            retrieval_duration_ms = (time.perf_counter() - retrieval_started) * 1000

            failure_stage = "context"
            context_result = await self.context_builder.build(
                conversation.id,
                retrieved_chunks=retrieved_chunks,
                system_suffix=TOOL_STREAM_INSTRUCTION,
            )
            messages = context_result.messages
            used_chunks = context_result.used_chunks
            evidence = ",".join(
                f"{ntpath.basename(str(chunk.metadata['source']))}:"
                f"{chunk.metadata['chunk_index']}:{chunk.score:.6f}"
                for chunk in retrieved_chunks
            ) or "-"
            logger.info(
                "event=chat.retrieval.completed outcome=%s rag_enabled=%s "
                "top_k=%s retrieved_count=%s used_count=%s empty=%s "
                "duration_ms=%.3f evidence=%s",
                "ran" if use_rag else "skipped",
                str(use_rag).lower(),
                settings.rag_top_k,
                len(retrieved_chunks),
                len(used_chunks),
                str(not retrieved_chunks).lower(),
                retrieval_duration_ms,
                evidence,
            )

            sources = self._build_sources(used_chunks=used_chunks)
            assistant_message = await self._create_assistant_message(
                conversation.id,
                sources,
            )
            chunks = []

            yield ChatStreamEvent(
                type="conversation",
                conversation_id=conversation.id
            )

            yield ChatStreamEvent(
                type="sources",
                sources=sources,
            )

            failure_stage = "llm_call_1"
            tool_context = [dict(item) for item in messages]
            tool_call: ToolCallComplete | None = None
            llm_started = time.perf_counter()
            logger.info(
                "event=chat.llm.started call_ordinal=1 mode=tool_enabled "
                "provider=%s model=%s usage_available=false",
                settings.llm_provider,
                settings.deepseek_model,
            )
            try:
                async for event in self.provider.stream_with_tools(
                    tool_context,
                    tools=[SHIPMENT_STATUS_TOOL, RETURN_ELIGIBILITY_HANDOFF_TOOL],
                    tool_choice="auto",
                ):
                    if isinstance(event, ContentDelta):
                        if tool_call is not None:
                            raise ProviderException("Provider returned mixed Tool content")
                        chunks.append(event.text)
                        yield ChatStreamEvent(type="token", content=event.text)
                    elif isinstance(event, ToolCallComplete):
                        if tool_call is not None or chunks:
                            raise ProviderException("Provider returned unsupported Tool Calls")
                        tool_call = event
                    else:
                        raise ProviderException("Provider returned an unsupported stream event")
            except Exception:
                logger.info(
                    "event=chat.llm.completed call_ordinal=1 mode=tool_enabled "
                    "provider=%s model=%s outcome=failed usage_available=false "
                    "duration_ms=%.3f",
                    settings.llm_provider,
                    settings.deepseek_model,
                    (time.perf_counter() - llm_started) * 1000,
                )
                raise

            logger.info(
                "event=chat.llm.completed call_ordinal=1 mode=tool_enabled "
                "provider=%s model=%s outcome=%s usage_available=false duration_ms=%.3f",
                settings.llm_provider,
                settings.deepseek_model,
                "tool_selected" if tool_call is not None else "direct_answer",
                (time.perf_counter() - llm_started) * 1000,
            )

            if tool_call is not None:
                logger.info("event=chat.tool.selected tool_name=%s", tool_call.name)
                failure_stage = "tool_validation"
                try:
                    self._validate_tool_call(tool_call)
                except ProviderException:
                    logger.info(
                        "event=chat.tool.validation.completed tool_name=%s outcome=invalid",
                        tool_call.name,
                    )
                    raise
                logger.info(
                    "event=chat.tool.validation.completed tool_name=%s outcome=valid",
                    tool_call.name,
                )

                failure_stage = "tool_execution"
                tool_started = time.perf_counter()
                logger.info("event=chat.tool.started tool_name=%s", tool_call.name)
                try:
                    if tool_call.name == "get_shipment_status":
                        tool_result = await self._execute_shipment_status_tool(tool_call)
                    elif tool_call.name == "request_return_eligibility_check":
                        tool_result = self._execute_return_eligibility_handoff_tool(tool_call)
                    else:
                        raise ProviderException("Provider returned an invalid Tool Call")
                except Exception:
                    logger.info(
                        "event=chat.tool.completed tool_name=%s outcome=failed "
                        "duration_ms=%.3f",
                        tool_call.name,
                        (time.perf_counter() - tool_started) * 1000,
                    )
                    raise
                tool_outcome = "handoff_ready"
                if tool_call.name == "get_shipment_status":
                    tool_outcome = (
                        "available" if tool_result.get("available") else "unavailable"
                    )
                logger.info(
                    "event=chat.tool.completed tool_name=%s outcome=%s duration_ms=%.3f",
                    tool_call.name,
                    tool_outcome,
                    (time.perf_counter() - tool_started) * 1000,
                )
                if tool_call.name == "request_return_eligibility_check":
                    # Tool completion 是服务端已发生的事实；先记录再交给 SSE consumer，
                    # 避免 consumer 提前断开导致 completion evidence 丢失。
                    yield ChatStreamEvent(
                        type="workflow_handoff",
                        kind="return_eligibility",
                    )
                # Tool Call/Result 只服务本次编排，历史中仅持久化最终 assistant 消息。
                tool_messages = tool_context + [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_call.name,
                                "arguments": json.dumps(tool_call.arguments),
                            },
                        }],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(tool_result),
                    },
                ]
                failure_stage = "llm_call_2"
                llm_started = time.perf_counter()
                logger.info(
                    "event=chat.llm.started call_ordinal=2 mode=normal_stream "
                    "provider=%s model=%s usage_available=false",
                    settings.llm_provider,
                    settings.deepseek_model,
                )
                try:
                    async for chunk in self.provider.stream_chat(tool_messages):
                        chunks.append(chunk)
                        yield ChatStreamEvent(type="token", content=chunk)
                except Exception:
                    logger.info(
                        "event=chat.llm.completed call_ordinal=2 mode=normal_stream "
                        "provider=%s model=%s outcome=failed usage_available=false "
                        "duration_ms=%.3f",
                        settings.llm_provider,
                        settings.deepseek_model,
                        (time.perf_counter() - llm_started) * 1000,
                    )
                    raise
                logger.info(
                    "event=chat.llm.completed call_ordinal=2 mode=normal_stream "
                    "provider=%s model=%s outcome=completed usage_available=false "
                    "duration_ms=%.3f",
                    settings.llm_provider,
                    settings.deepseek_model,
                    (time.perf_counter() - llm_started) * 1000,
                )
            
            full_content = "".join(chunks)

            assistant_message.content = full_content

            assistant_message.status = MessageStatus.COMPLETED

            failure_stage = "persistence"
            await self.message_repo.update(assistant_message)
            logger.info(
                "event=chat.execution.completed outcome=completed duration_ms=%.3f",
                (time.perf_counter() - execution_started) * 1000,
            )

        except asyncio.CancelledError:
            if assistant_message is not None:
                assistant_message.status = MessageStatus.FAILED

            # Request cancellation 已经生效。
            # 用一个很短的 shielded scope 保证 failed 状态能够提交，
            # 然后继续向上传播 cancellation。
                with CancelScope(shield=True):
                    await self.message_repo.update(assistant_message)

            logger.info(
                "event=chat.execution.completed outcome=cancelled failure_stage=%s "
                "duration_ms=%.3f",
                failure_stage,
                (time.perf_counter() - execution_started) * 1000,
            )

            raise

        except (ProviderException, ConfigurationException):
            if assistant_message is not None:
                assistant_message.status = MessageStatus.FAILED
                await self.message_repo.update(assistant_message)
            logger.warning(
                "event=chat.execution.completed outcome=handled_error failure_stage=%s "
                "duration_ms=%.3f",
                failure_stage,
                (time.perf_counter() - execution_started) * 1000,
            )
            raise

        except Exception:
            if assistant_message is not None:
                assistant_message.status = MessageStatus.FAILED
                await self.message_repo.update(assistant_message)
            logger.exception(
                "event=chat.execution.completed outcome=unexpected_error failure_stage=%s "
                "duration_ms=%.3f",
                failure_stage,
                (time.perf_counter() - execution_started) * 1000,
            )
            raise

    @staticmethod
    def _validate_tool_call(tool_call: ToolCallComplete) -> None:
        if not tool_call.id:
            raise ProviderException("Provider returned an invalid Tool Call")
        if tool_call.name == "request_return_eligibility_check":
            if tool_call.arguments != {}:
                raise ProviderException("Provider returned invalid Tool arguments")
            return
        if tool_call.name != "get_shipment_status":
            raise ProviderException("Provider returned an invalid Tool Call")
        if set(tool_call.arguments) != {"shipment_id"}:
            raise ProviderException("Provider returned invalid Tool arguments")
        raw_shipment_id = tool_call.arguments["shipment_id"]
        if not isinstance(raw_shipment_id, str):
            raise ProviderException("Provider returned invalid Tool arguments")
        try:
            shipment_id = UUID(raw_shipment_id)
        except ValueError as exc:
            raise ProviderException("Provider returned invalid Tool arguments") from exc
        if str(shipment_id) != raw_shipment_id.lower():
            raise ProviderException("Provider returned invalid Tool arguments")

    @staticmethod
    def _execute_return_eligibility_handoff_tool(
        tool_call: ToolCallComplete,
    ) -> dict:
        # Tool result 只声明 application handoff ready；无参数设计刻意避免让 LLM
        # 选择 purchase、注入 identity 或越过 BusinessService 做业务判断。
        ChatService._validate_tool_call(tool_call)
        if tool_call.name != "request_return_eligibility_check":
            raise ProviderException("Provider returned an invalid Tool Call")
        return {
            "status": "handoff_ready",
            "action": "return_eligibility",
            "requires_user_confirmation": True,
        }

    async def _execute_shipment_status_tool(
        self,
        tool_call: ToolCallComplete,
        now: datetime | None = None,
    ) -> dict:
        self._validate_tool_call(tool_call)
        if tool_call.name != "get_shipment_status":
            raise ProviderException("Provider returned an invalid Tool Call")
        raw_shipment_id = tool_call.arguments["shipment_id"]
        shipment_id = UUID(raw_shipment_id)

        try:
            shipment = await self.business_service.get_shipment(
                DEMO_CUSTOMER_ID,
                shipment_id,
            )
        except NotFoundException:
            # 缺失与跨客户访问统一为不可用，避免通过响应差异泄露记录是否存在。
            return {"available": False}

        logistics_exception = self.business_service.detect_logistics_exception(
            shipment,
            now or datetime.now(timezone.utc),
        )
        return {
            "available": True,
            "status": shipment.status,
            "tracking_number": shipment.tracking_number,
            "updated_at": shipment.updated_at.isoformat(),
            "delivered_at": (
                shipment.delivered_at.isoformat()
                if shipment.delivered_at is not None
                else None
            ),
            "logistics_exception": {
                "decision": logistics_exception.decision,
            },
        }

    async def _prepare_conversation(
        self,
        message: str,
        conversation_id: UUID | None,
    ) -> Conversation:

        # 1. 获取或者创建 conversation

        if conversation_id:

            conversation = await self.conversation_repo.get_by_id(
                conversation_id
            )

            if conversation is None:
                raise ConversationNotFoundException(
                    "Conversation not found"
                )

        else:

            conversation = Conversation(
                title=message[:20]
            )

            conversation = await self.conversation_repo.create(
                conversation
            )


        # 2. 保存用户消息

        user_message = Message(
            conversation_id=conversation.id,
            role="user",
            content=message,
            sources=[]
        )

        await self.message_repo.create(
            user_message
        )

        return conversation

    async def _create_assistant_message(
        self,
        conversation_id: UUID,
        sources: list[SourceReference],
    ) -> Message:

        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="",
            model=settings.deepseek_model,
            status=MessageStatus.STREAMING,
            sources=[source.model_dump() for source in sources],
        )

        return await self.message_repo.create(
            assistant_message
        )

    def _build_sources(
        self,
        used_chunks: list[RetrievedChunk],
    ) -> list[SourceReference]:

        return [
            SourceReference(
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                source=chunk.metadata["source"],
                chunk_index=chunk.metadata["chunk_index"],
                score=chunk.score,
            )
            for chunk in used_chunks
        ]
