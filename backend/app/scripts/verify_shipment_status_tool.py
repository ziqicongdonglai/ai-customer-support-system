"""Deterministic verification for Mission 4 Phase 3 Slice 3."""
import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from app.context.models import ContextBuildResult
from app.core.config import settings
from app.core.exceptions import NotFoundException, ProviderException
from app.models.message import MessageStatus
from app.providers.base import BaseLLMProvider, ContentDelta, ToolCallComplete
from app.providers.deepseek import DeepSeekProvider
from app.providers.mock import MockProvider
from app.rag.models import RetrievedChunk
from app.services.chat_service import (
    ChatService,
    DEMO_CUSTOMER_ID,
    RETURN_ELIGIBILITY_HANDOFF_TOOL,
    SHIPMENT_STATUS_TOOL,
    TOOL_STREAM_INSTRUCTION,
)
from app.services.business_service import BusinessService
from app.services.context_builder import ContextBuilder


OWNED_SHIPMENT_ID = UUID("639e5619-a77b-5323-89ac-94e1f7a58214")
NON_EXCEPTION_SHIPMENT_ID = UUID("20000000-0000-4000-8000-000000000002")
CROSS_CUSTOMER_SHIPMENT_ID = UUID("4ed0ea70-39bb-5e2a-bd8a-4e636e219bcf")
MISSING_SHIPMENT_ID = UUID("00000000-0000-4000-8000-000000000001")


async def chunks(items):
    for item in items:
        yield item


async def collect(stream):
    return [item async for item in stream]


async def expect_provider_error(stream):
    try:
        await collect(stream)
    except ProviderException:
        return
    raise AssertionError("Expected ProviderException")


class FakeProvider(BaseLLMProvider):
    def __init__(self, tool_call=None):
        self.tool_call = tool_call
        self.first_messages = None
        self.final_messages = None
        self.model_call_count = 0

    async def chat(self, messages):
        self.model_call_count += 1
        return "unused"

    async def stream_with_tools(self, messages, tools, tool_choice):
        self.model_call_count += 1
        self.first_messages = messages
        assert tools == [SHIPMENT_STATUS_TOOL, RETURN_ELIGIBILITY_HANDOFF_TOOL]
        assert tool_choice == "auto"
        assert tools[0]["function"]["parameters"]["properties"] == {
            "shipment_id": {
                "type": "string",
                "format": "uuid",
                "description": "Shipment UUID shown to the customer.",
            }
        }
        if self.tool_call is not None:
            yield self.tool_call
            return
        for text in ("direct ", "streamed ", "answer"):
            yield ContentDelta(text)

    async def stream_chat(self, messages):
        self.model_call_count += 1
        self.final_messages = messages
        result = json.loads(messages[-1]["content"])
        chunks = (
            ("handoff is ", "ready")
            if result.get("action") == "return_eligibility"
            else ("shipment is ", "in_transit")
        )
        for text in chunks:
            yield text


class FakeConversationRepository:
    async def create(self, conversation):
        conversation.id = UUID("10000000-0000-4000-8000-000000000001")
        return conversation

    async def get_by_id(self, conversation_id):
        return SimpleNamespace(id=conversation_id)


class FakeMessageRepository:
    def __init__(self):
        self.created = []
        self.updated = []

    async def create(self, message):
        self.created.append(message)
        return message

    async def update(self, message):
        self.updated.append(message)
        return message


class FakeContextBuilder:
    async def build(self, conversation_id, retrieved_chunks=None, system_suffix=""):
        system_content = "helpful"
        if system_suffix:
            system_content += f"\n\n{system_suffix}"
        if retrieved_chunks:
            system_content += "\n\n[Knowledge Context]\n" + "\n".join(
                chunk.content for chunk in retrieved_chunks
            )
        return ContextBuildResult(
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": "test"},
            ],
            used_chunks=retrieved_chunks or [],
        )


class FakeRetriever:
    def __init__(self):
        self.calls = 0

    def retrieve(self, query):
        self.calls += 1
        return [RetrievedChunk(
            "logistics-chunk",
            "logistics-document",
            "Policy: a non-delivered shipment is exceptional only after more than 72 hours.",
            0.99,
            {"source": "logistics_exception.md", "chunk_index": 0},
        )]


class FakeBusinessService:
    def __init__(self):
        self.calls = []
        self.rule_calls = []

    async def get_shipment(self, customer_id, shipment_id):
        self.calls.append((customer_id, shipment_id))
        if shipment_id not in {OWNED_SHIPMENT_ID, NON_EXCEPTION_SHIPMENT_ID}:
            raise NotFoundException("not exposed")
        return SimpleNamespace(
            status="in_transit",
            tracking_number=(
                "DEMO-A-STALE"
                if shipment_id == OWNED_SHIPMENT_ID
                else "DEMO-A-RECENT"
            ),
            updated_at=(
                datetime(2026, 9, 2, 12, tzinfo=timezone.utc)
                if shipment_id == OWNED_SHIPMENT_ID
                else datetime(2026, 9, 6, 12, tzinfo=timezone.utc)
            ),
            delivered_at=None,
        )

    def detect_logistics_exception(self, shipment, now):
        self.rule_calls.append((shipment, now))
        return BusinessService.detect_logistics_exception(self, shipment, now)


def make_service(provider):
    message_repo = FakeMessageRepository()
    retriever = FakeRetriever()
    business_service = FakeBusinessService()
    service = ChatService(
        provider=provider,
        conversation_repo=FakeConversationRepository(),
        message_repo=message_repo,
        context_builder=FakeContextBuilder(),
        retriever=retriever,
        business_service=business_service,
    )
    return service, message_repo, retriever, business_service


class BudgetMessageRepository:
    async def get_by_conversation_id(self, conversation_id):
        return [SimpleNamespace(role="user", content="question")]


class BudgetStrategy:
    def __init__(self):
        self.max_tokens = []

    async def build(self, history, max_tokens):
        self.max_tokens.append(max_tokens)
        return []


class BudgetTokenCounter:
    def __init__(self, suffixed_system):
        self.suffixed_system = suffixed_system
        self.calls = []

    def estimate_tokens(self, text):
        self.calls.append(text)
        if text == self.suffixed_system:
            return settings.max_context_tokens - 2
        if text in (settings.default_system_prompt, "question"):
            return 1
        return 2


async def verify_context_budget():
    suffix = TOOL_STREAM_INSTRUCTION
    suffixed_system = f"{settings.default_system_prompt}\n\n{suffix}"
    chunk = RetrievedChunk("chunk", "document", "knowledge", 1.0, {})

    default_strategy = BudgetStrategy()
    default_counter = BudgetTokenCounter(suffixed_system)
    default_result = await ContextBuilder(
        BudgetMessageRepository(), default_strategy, default_counter,
    ).build(UUID(int=1), retrieved_chunks=[chunk])
    assert default_result.messages[0]["content"].startswith(
        f"{settings.default_system_prompt}\n\n[Knowledge Context]"
    )
    assert default_result.used_chunks == [chunk]
    assert default_strategy.max_tokens == [settings.max_context_tokens - 4]

    suffix_strategy = BudgetStrategy()
    suffix_counter = BudgetTokenCounter(suffixed_system)
    suffix_result = await ContextBuilder(
        BudgetMessageRepository(), suffix_strategy, suffix_counter,
    ).build(UUID(int=1), retrieved_chunks=[chunk], system_suffix=suffix)
    assert suffix_result.messages[0]["content"] == suffixed_system
    assert suffix_result.used_chunks == []
    assert suffix_counter.calls[0] == suffixed_system
    assert suffix_strategy.max_tokens == [1]


async def verify_provider():
    provider = DeepSeekProvider()
    direct = await collect(provider._translate_tool_chunks(chunks([
        {"choices": [{"delta": {"role": "assistant", "content": ""}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "hello "}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "world"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ])))
    assert direct == [ContentDelta("hello "), ContentDelta("world")]

    tool_events = await collect(provider._translate_tool_chunks(chunks([
        {"choices": [{"delta": {"role": "assistant", "content": ""}, "finish_reason": None}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call-42", "function": {
            "name": "get_shipment_status", "arguments": "{\"shipment_"
        }}]}, "finish_reason": None}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {
            "arguments": f"id\": \"{OWNED_SHIPMENT_ID}\"}}"
        }}]}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ])))
    expected_call = ToolCallComplete(
        "call-42", "get_shipment_status", {"shipment_id": str(OWNED_SHIPMENT_ID)},
    )
    assert tool_events == [expected_call]

    await expect_provider_error(provider._translate_tool_chunks(chunks([
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "bad", "function": {
            "name": "get_shipment_status", "arguments": "{bad"
        }}]}, "finish_reason": "tool_calls"}]},
    ])))
    await expect_provider_error(provider._translate_tool_chunks(chunks([
        {"choices": [{"delta": {"tool_calls": [{"index": 1, "id": "bad", "function": {
            "name": "get_shipment_status", "arguments": "{}"
        }}]}, "finish_reason": "tool_calls"}]},
    ])))
    await expect_provider_error(provider._translate_tool_chunks(chunks([
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "one", "function": {"name": "get_shipment_status", "arguments": "{}"}},
            {"index": 1, "id": "two", "function": {"name": "get_shipment_status", "arguments": "{}"}},
        ]}, "finish_reason": "tool_calls"}]},
    ])))
    await expect_provider_error(provider._translate_tool_chunks(chunks([
        {"choices": [{"delta": {"content": "visible"}, "finish_reason": None}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "late", "function": {
            "name": "get_shipment_status", "arguments": "{}"
        }}]}, "finish_reason": "tool_calls"}]},
    ])))
    await expect_provider_error(provider._translate_tool_chunks(chunks([
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call", "function": {
            "name": "get_shipment_status", "arguments": "{}"
        }}]}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "visible"}, "finish_reason": "stop"}]},
    ])))
    return direct, expected_call


async def verify_business_tool():
    service, _, _, business = make_service(FakeProvider())
    results = {}
    fixed_now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    for label, shipment_id in (
        ("exception", OWNED_SHIPMENT_ID),
        ("non-exception", NON_EXCEPTION_SHIPMENT_ID),
        ("cross-customer", CROSS_CUSTOMER_SHIPMENT_ID),
        ("missing", MISSING_SHIPMENT_ID),
    ):
        results[label] = await service._execute_shipment_status_tool(ToolCallComplete(
            "call-safe", "get_shipment_status", {"shipment_id": str(shipment_id)},
        ), now=fixed_now)
    assert results["exception"] == {
        "available": True,
        "status": "in_transit",
        "tracking_number": "DEMO-A-STALE",
        "updated_at": "2026-09-02T12:00:00+00:00",
        "delivered_at": None,
        "logistics_exception": {"decision": True},
    }
    assert results["non-exception"] == {
        "available": True,
        "status": "in_transit",
        "tracking_number": "DEMO-A-RECENT",
        "updated_at": "2026-09-06T12:00:00+00:00",
        "delivered_at": None,
        "logistics_exception": {"decision": False},
    }
    assert results["cross-customer"] == results["missing"] == {"available": False}
    assert all(customer_id == DEMO_CUSTOMER_ID for customer_id, _ in business.calls)
    assert len(business.rule_calls) == 2
    return results


def verify_handoff_tool():
    call = ToolCallComplete(
        "call-handoff", "request_return_eligibility_check", {},
    )
    result = ChatService._execute_return_eligibility_handoff_tool(call)
    assert result == {
        "status": "handoff_ready",
        "action": "return_eligibility",
        "requires_user_confirmation": True,
    }
    assert "workflow_id" not in result
    try:
        ChatService._execute_return_eligibility_handoff_tool(ToolCallComplete(
            "call-invalid", "request_return_eligibility_check", {"order_item_id": "no"},
        ))
    except ProviderException:
        pass
    else:
        raise AssertionError("Expected invalid handoff arguments to be rejected")
    return result


async def verify_mock_handoff():
    provider = MockProvider()
    events = await collect(provider.stream_with_tools(
        [{"role": "user", "content": "Can I return the mouse I bought?"}],
        [SHIPMENT_STATUS_TOOL, RETURN_ELIGIBILITY_HANDOFF_TOOL],
        "auto",
    ))
    assert events == [ToolCallComplete(
        "mock-tool-call-2", "request_return_eligibility_check", {},
    )]
    text = "".join(await collect(provider.stream_chat([
        {"role": "tool", "content": json.dumps({
            "status": "handoff_ready",
            "action": "return_eligibility",
            "requires_user_confirmation": True,
        })},
    ])))
    assert text == (
        "I've prepared the return eligibility check. "
        "Click Start check and choose the purchase to continue."
    )
    return text


async def verify_orchestration():
    direct_provider = FakeProvider()
    direct_service, direct_messages, retriever, _ = make_service(direct_provider)
    direct_events = await collect(direct_service.stream_chat("hello", None, use_rag=True))
    direct_tokens = [event.content for event in direct_events if event.type == "token"]
    assert direct_tokens == ["direct ", "streamed ", "answer"]
    assert direct_provider.model_call_count == 1 and retriever.calls == 1
    assert direct_provider.first_messages[0]["content"].startswith(
        f"helpful\n\n{TOOL_STREAM_INSTRUCTION}\n\n[Knowledge Context]"
    )
    assert [event.type for event in direct_events] == [
        "conversation", "sources", "token", "token", "token",
    ]
    assert [message.role for message in direct_messages.created] == ["user", "assistant"]
    assert direct_messages.updated[-1].content == "direct streamed answer"
    assert direct_messages.updated[-1].status == MessageStatus.COMPLETED

    tool_call = ToolCallComplete(
        "call-42", "get_shipment_status", {"shipment_id": str(OWNED_SHIPMENT_ID)},
    )
    tool_provider = FakeProvider(tool_call)
    tool_service, tool_messages, tool_retriever, business = make_service(tool_provider)
    tool_events = await collect(tool_service.stream_chat("shipment?", None, use_rag=False))
    tool_tokens = [event.content for event in tool_events if event.type == "token"]
    assert tool_tokens == ["shipment is ", "in_transit"]
    assert tool_provider.model_call_count == 2
    assert len(business.calls) == 1
    assert [message.role for message in tool_messages.created] == ["user", "assistant"]
    assert tool_messages.updated[-1].content == "shipment is in_transit"
    assert tool_messages.updated[-1].status == MessageStatus.COMPLETED
    assert [message["role"] for message in tool_provider.final_messages[-2:]] == ["assistant", "tool"]
    assert tool_provider.final_messages[-2]["tool_calls"][0]["id"] == "call-42"
    assert tool_provider.final_messages[-1]["tool_call_id"] == "call-42"
    result = json.loads(tool_provider.final_messages[-1]["content"])
    assert result["logistics_exception"] == {"decision": True}
    assert "customer_id" not in result
    assert tool_retriever.calls == 0
    assert next(event for event in tool_events if event.type == "sources").sources == []

    handoff_call = ToolCallComplete(
        "call-handoff", "request_return_eligibility_check", {},
    )
    handoff_provider = FakeProvider(handoff_call)
    handoff_service, handoff_messages, _, handoff_business = make_service(handoff_provider)
    handoff_events = await collect(handoff_service.stream_chat(
        "Can I return the mouse I bought?", None, use_rag=False,
    ))
    assert [event.type for event in handoff_events] == [
        "conversation", "sources", "workflow_handoff", "token", "token",
    ]
    assert next(
        event for event in handoff_events if event.type == "workflow_handoff"
    ).kind == "return_eligibility"
    assert handoff_provider.model_call_count == 2
    assert handoff_business.calls == [] and handoff_business.rule_calls == []
    handoff_result = json.loads(handoff_provider.final_messages[-1]["content"])
    assert handoff_result == {
        "status": "handoff_ready",
        "action": "return_eligibility",
        "requires_user_confirmation": True,
    }
    assert [message.role for message in handoff_messages.created] == ["user", "assistant"]
    assert handoff_messages.updated[-1].content == "handoff is ready"
    assert handoff_messages.updated[-1].status == MessageStatus.COMPLETED

    rag_provider = FakeProvider(tool_call)
    rag_service, rag_messages, rag_retriever, _ = make_service(rag_provider)
    rag_events = await collect(rag_service.stream_chat("shipment exception?", None, use_rag=True))
    rag_result = json.loads(rag_provider.final_messages[-1]["content"])
    rag_sources = next(event for event in rag_events if event.type == "sources").sources
    assert rag_result["logistics_exception"] == result["logistics_exception"]
    assert rag_retriever.calls == 1
    assert [source.source for source in rag_sources] == ["logistics_exception.md"]
    assert "[Knowledge Context]" in rag_provider.final_messages[0]["content"]
    assert [message.role for message in rag_messages.created] == ["user", "assistant"]
    return (
        direct_tokens, tool_tokens, result, rag_result, handoff_result,
        tool_provider.model_call_count, len(rag_sources),
    )


async def main():
    await verify_context_budget()
    direct_provider_events, assembled_call = await verify_provider()
    ownership = await verify_business_tool()
    handoff_contract = verify_handoff_tool()
    mock_handoff_text = await verify_mock_handoff()
    (
        direct_tokens, tool_tokens, tool_result, rag_result, handoff_result,
        model_calls, rag_source_count,
    ) = await verify_orchestration()
    print(json.dumps({
        "provider_direct_chunk_count": len(direct_provider_events),
        "direct_orchestration_chunk_count": len(direct_tokens),
        "tool_name": assembled_call.name,
        "tool_call_id": assembled_call.id,
        "assembled_arguments": assembled_call.arguments,
        "tool_result": tool_result,
        "handoff_contract": handoff_contract,
        "handoff_result": handoff_result,
        "mock_handoff_text": mock_handoff_text,
        "model_call_count": model_calls,
        "rag_disabled_decision": tool_result["logistics_exception"]["decision"],
        "rag_enabled_decision": rag_result["logistics_exception"]["decision"],
        "rag_enabled_source_count": rag_source_count,
        "final_streamed_chunk_count": len(tool_tokens),
        "ownership": ownership,
        "persistence_roles": ["user", "assistant"],
        "rag_regression": "retriever called; direct stream preserved",
        "context_budget": "system suffix estimated before RAG/history allocation",
    }, indent=2))
    print("PASS: provider, bounded handoff, deterministic Rule composition, RAG authority, persistence, and SSE boundary")


if __name__ == "__main__":
    asyncio.run(main())
