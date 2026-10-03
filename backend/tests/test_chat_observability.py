import asyncio
import logging
import re
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.api.routes.stream import generate_stream
from app.context.models import ContextBuildResult
from app.core.context import request_id_context
from app.core.exceptions import NotFoundException, ProviderException
from app.core.logging import RequestIDFilter
from app.database.engine import engine
from app.providers.base import BaseLLMProvider, ContentDelta, ToolCallComplete
from app.rag.models import RetrievedChunk
from app.services.chat_service import ChatService


REQUEST_ID = "request-observability-test"
USER_TEXT = "sensitive user message sentinel"
ANSWER_TEXT = "sensitive generated answer sentinel"
CHUNK_TEXT = "sensitive retrieved chunk sentinel"
SHIPMENT_ID = "639e5619-a77b-5323-89ac-94e1f7a58214"
CUSTOMER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


async def collect(stream):
    return [item async for item in stream]


class FakeProvider(BaseLLMProvider):
    def __init__(self, tool_call=None, fail_final=False):
        self.tool_call = tool_call
        self.fail_final = fail_final

    async def chat(self, messages):
        return ANSWER_TEXT

    async def stream_with_tools(self, messages, tools, tool_choice):
        if self.tool_call is None:
            yield ContentDelta(ANSWER_TEXT)
        else:
            yield self.tool_call

    async def stream_chat(self, messages):
        if self.fail_final:
            raise ProviderException("safe provider failure")
        yield ANSWER_TEXT


class FakeConversationRepository:
    async def create(self, conversation):
        conversation.id = UUID(int=1)
        return conversation

    async def get_by_id(self, conversation_id):
        return SimpleNamespace(id=conversation_id)


class FakeMessageRepository:
    async def create(self, message):
        return message

    async def update(self, message):
        return message


class FakeContextBuilder:
    async def build(self, conversation_id, retrieved_chunks=None, system_suffix=""):
        return ContextBuildResult(
            messages=[{"role": "user", "content": USER_TEXT}],
            used_chunks=retrieved_chunks or [],
        )


class FakeRetriever:
    def retrieve(self, query):
        return [
            RetrievedChunk(
                "chunk-id",
                "document-id",
                CHUNK_TEXT,
                0.875,
                {"source": r"C:\private\policy.md", "chunk_index": 4},
            )
        ]


class FakeBusinessService:
    def __init__(self, error=None):
        self.error = error

    async def get_shipment(self, customer_id, shipment_id):
        if self.error is not None:
            raise self.error
        raise NotFoundException("ownership-safe unavailable")


def make_service(provider, business_service=None):
    return ChatService(
        provider=provider,
        conversation_repo=FakeConversationRepository(),
        message_repo=FakeMessageRepository(),
        context_builder=FakeContextBuilder(),
        retriever=FakeRetriever(),
        business_service=business_service or FakeBusinessService(),
    )


def semantic_logs(caplog):
    records = [record for record in caplog.records if "event=" in record.getMessage()]
    return records, "\n".join(record.getMessage() for record in records)


def test_direct_stream_has_correlated_safe_lifecycle_logs(caplog):
    caplog.set_level(logging.INFO)
    caplog.handler.addFilter(RequestIDFilter())

    async def run():
        return await collect(
            generate_stream(
                make_service(FakeProvider()),
                USER_TEXT,
                None,
                use_rag=True,
                request_id=REQUEST_ID,
            )
        )

    asyncio.run(run())
    records, logs = semantic_logs(caplog)

    assert records and {record.request_id for record in records} == {REQUEST_ID}
    assert "event=chat.execution.started rag_enabled=true" in logs
    assert "event=chat.retrieval.completed outcome=ran" in logs
    assert "retrieved_count=1 used_count=1 empty=false" in logs
    assert "evidence=policy.md:4:0.875000" in logs
    assert "call_ordinal=1 mode=tool_enabled" in logs
    assert "outcome=direct_answer" in logs
    assert "event=chat.execution.completed outcome=completed" in logs
    assert "event=chat.sse.completed outcome=completed" in logs
    assert re.search(r"duration_ms=\d+\.\d{3}", logs)
    for sensitive in (USER_TEXT, ANSWER_TEXT, CHUNK_TEXT, "C:\\private"):
        assert sensitive not in logs


def test_tool_stream_logs_validation_execution_and_second_call_without_ids(caplog):
    caplog.set_level(logging.INFO)
    caplog.handler.addFilter(RequestIDFilter())
    tool_call = ToolCallComplete(
        "call-safe",
        "get_shipment_status",
        {"shipment_id": SHIPMENT_ID},
    )

    async def run():
        return await collect(
            generate_stream(
                make_service(FakeProvider(tool_call)),
                USER_TEXT,
                None,
                request_id=REQUEST_ID,
            )
        )

    asyncio.run(run())
    records, logs = semantic_logs(caplog)

    assert records and {record.request_id for record in records} == {REQUEST_ID}
    assert "outcome=tool_selected" in logs
    assert "event=chat.tool.selected tool_name=get_shipment_status" in logs
    assert "event=chat.tool.validation.completed tool_name=get_shipment_status outcome=valid" in logs
    assert "event=chat.tool.completed tool_name=get_shipment_status outcome=unavailable" in logs
    assert "call_ordinal=2 mode=normal_stream" in logs
    assert "outcome=completed usage_available=false" in logs
    for sensitive in (USER_TEXT, ANSWER_TEXT, SHIPMENT_ID, CUSTOMER_ID):
        assert sensitive not in logs


def test_second_call_failure_keeps_tool_completion_and_failure_stage(caplog):
    caplog.set_level(logging.INFO)
    caplog.handler.addFilter(RequestIDFilter())
    tool_call = ToolCallComplete(
        "call-safe",
        "get_shipment_status",
        {"shipment_id": SHIPMENT_ID},
    )

    async def run():
        return await collect(
            generate_stream(
                make_service(FakeProvider(tool_call, fail_final=True)),
                USER_TEXT,
                None,
                request_id=REQUEST_ID,
            )
        )

    asyncio.run(run())
    _, logs = semantic_logs(caplog)

    assert "event=chat.tool.completed tool_name=get_shipment_status outcome=unavailable" in logs
    assert "call_ordinal=2 mode=normal_stream" in logs
    assert "outcome=failed usage_available=false" in logs
    assert "outcome=handled_error failure_stage=llm_call_2" in logs
    assert "event=chat.sse.completed outcome=handled_provider_error" in logs


def test_invalid_tool_stops_before_execution_and_logs_validation_failure(caplog):
    caplog.set_level(logging.INFO)
    caplog.handler.addFilter(RequestIDFilter())
    sensitive_argument = "sensitive validation argument sentinel"
    tool_call = ToolCallComplete(
        "call-invalid",
        "invalid_tool_name",
        {"unsafe": sensitive_argument},
    )

    asyncio.run(
        collect(
            generate_stream(
                make_service(FakeProvider(tool_call)),
                USER_TEXT,
                None,
                request_id=REQUEST_ID,
            )
        )
    )
    _, logs = semantic_logs(caplog)

    assert "outcome=tool_selected" in logs
    assert "event=chat.tool.selected tool_name=invalid_tool_name" in logs
    assert (
        "event=chat.tool.validation.completed "
        "tool_name=invalid_tool_name outcome=invalid"
    ) in logs
    assert "outcome=handled_error failure_stage=tool_validation" in logs
    assert "event=chat.sse.completed outcome=handled_provider_error" in logs
    assert "event=chat.tool.started" not in logs
    assert sensitive_argument not in logs


def test_tool_execution_failure_logs_failed_completion_and_reraises(caplog):
    caplog.set_level(logging.INFO)
    caplog.handler.addFilter(RequestIDFilter())
    failure = RuntimeError("safe tool execution failure")
    tool_call = ToolCallComplete(
        "call-safe",
        "get_shipment_status",
        {"shipment_id": SHIPMENT_ID},
    )

    with pytest.raises(RuntimeError) as caught:
        asyncio.run(
            collect(
                generate_stream(
                    make_service(
                        FakeProvider(tool_call),
                        business_service=FakeBusinessService(error=failure),
                    ),
                    USER_TEXT,
                    None,
                    request_id=REQUEST_ID,
                )
            )
        )

    _, logs = semantic_logs(caplog)
    assert caught.value is failure
    assert "event=chat.tool.started tool_name=get_shipment_status" in logs
    assert (
        "event=chat.tool.completed "
        "tool_name=get_shipment_status outcome=failed"
    ) in logs
    assert "outcome=unexpected_error failure_stage=tool_execution" in logs
    assert SHIPMENT_ID not in logs
    assert USER_TEXT not in logs


def test_handoff_completion_is_logged_before_sse_yield(caplog):
    caplog.set_level(logging.INFO)
    caplog.handler.addFilter(RequestIDFilter())
    tool_call = ToolCallComplete(
        "call-handoff",
        "request_return_eligibility_check",
        {},
    )

    async def run():
        saw_handoff = False
        async for event in make_service(FakeProvider(tool_call)).stream_chat(
            USER_TEXT,
            None,
        ):
            if event.type == "workflow_handoff":
                _, logs_at_yield = semantic_logs(caplog)
                assert (
                    "event=chat.tool.completed "
                    "tool_name=request_return_eligibility_check "
                    "outcome=handoff_ready"
                ) in logs_at_yield
                saw_handoff = True
        assert saw_handoff

    asyncio.run(run())


def test_stream_context_resets_when_consumer_closes_generator():
    async def run():
        stream = generate_stream(
            make_service(FakeProvider()),
            USER_TEXT,
            None,
            request_id=REQUEST_ID,
        )
        await anext(stream)
        assert request_id_context.get() == REQUEST_ID
        await stream.aclose()
        assert request_id_context.get() is None

    asyncio.run(run())


def test_sql_parameters_are_hidden_by_default():
    assert engine.echo is False
    assert engine.sync_engine.hide_parameters is True
