import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.core.config import settings
from app.core.exceptions import NotFoundException, ProviderException
from app.providers.base import ToolCallComplete
from app.rag.models import RetrievedChunk
from app.services.business_service import BusinessService
from app.services.chat_service import ChatService, DEMO_CUSTOMER_ID, TOOL_STREAM_INSTRUCTION
from app.services.context_builder import ContextBuilder


OWNED_SHIPMENT_ID = UUID("639e5619-a77b-5323-89ac-94e1f7a58214")
NON_EXCEPTION_SHIPMENT_ID = UUID("20000000-0000-4000-8000-000000000002")
CROSS_CUSTOMER_SHIPMENT_ID = UUID("4ed0ea70-39bb-5e2a-bd8a-4e636e219bcf")
MISSING_SHIPMENT_ID = UUID("00000000-0000-4000-8000-000000000001")


# 用最小 Fake 固定历史、策略和 token 估算，只验证 ContextBuilder 的预算顺序，
# 不引入真实消息持久化或 tokenizer。
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


# 用 FakeBusinessService 隔离数据库，只验证 ChatService 如何组合业务状态、
# 确定性规则与 ownership hiding。
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


def test_context_budget_counts_tool_instruction_before_rag_and_history():
    async def run():
        # 用同一组确定性输入对比普通 system prompt 与 Tool instruction，
        # 防止后者绕过 RAG/history 的 token budget。
        suffix = TOOL_STREAM_INSTRUCTION
        suffixed_system = f"{settings.default_system_prompt}\n\n{suffix}"
        chunk = RetrievedChunk("chunk", "document", "knowledge", 1.0, {})

        default_strategy = BudgetStrategy()
        default_result = await ContextBuilder(
            BudgetMessageRepository(),
            default_strategy,
            BudgetTokenCounter(suffixed_system),
        ).build(UUID(int=1), retrieved_chunks=[chunk])
        assert default_result.messages[0]["content"].startswith(
            f"{settings.default_system_prompt}\n\n[Knowledge Context]"
        )
        assert default_result.used_chunks == [chunk]
        assert default_strategy.max_tokens == [settings.max_context_tokens - 4]

        suffix_strategy = BudgetStrategy()
        suffix_counter = BudgetTokenCounter(suffixed_system)
        suffix_result = await ContextBuilder(
            BudgetMessageRepository(), suffix_strategy, suffix_counter
        ).build(UUID(int=1), retrieved_chunks=[chunk], system_suffix=suffix)
        assert suffix_result.messages[0]["content"] == suffixed_system
        assert suffix_result.used_chunks == []
        assert suffix_counter.calls[0] == suffixed_system
        assert suffix_strategy.max_tokens == [1]

    asyncio.run(run())


def test_shipment_status_tool_composes_rule_and_hides_ownership():
    async def run():
        business_service = FakeBusinessService()
        service = ChatService(
            provider=None,
            conversation_repo=None,
            message_repo=None,
            context_builder=None,
            retriever=None,
            business_service=business_service,
        )
        # 固定 now，避免 72 小时物流规则随测试执行日期变化。
        fixed_now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
        results = {}
        for label, shipment_id in (
            ("exception", OWNED_SHIPMENT_ID),
            ("non-exception", NON_EXCEPTION_SHIPMENT_ID),
            ("cross-customer", CROSS_CUSTOMER_SHIPMENT_ID),
            ("missing", MISSING_SHIPMENT_ID),
        ):
            results[label] = await service._execute_shipment_status_tool(
                ToolCallComplete(
                    "call-safe", "get_shipment_status", {"shipment_id": str(shipment_id)}
                ),
                now=fixed_now,
            )

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
        # 跨客户与不存在的资源必须保持相同投影，避免泄露资源存在性或归属。
        assert results["cross-customer"] == results["missing"] == {
            "available": False
        }
        assert all(
            customer_id == DEMO_CUSTOMER_ID
            for customer_id, _ in business_service.calls
        )
        assert len(business_service.rule_calls) == 2

    asyncio.run(run())


def test_return_eligibility_handoff_is_bounded():
    # Handoff 只确认 AI 识别到用户意图；用户确认前不能创建 durable Workflow。
    result = ChatService._execute_return_eligibility_handoff_tool(
        ToolCallComplete("call-handoff", "request_return_eligibility_check", {})
    )
    assert result == {
        "status": "handoff_ready",
        "action": "return_eligibility",
        "requires_user_confirmation": True,
    }
    assert "workflow_id" not in result

    # LLM 不能在 handoff 阶段注入 purchase identity 或其他业务参数。
    with pytest.raises(ProviderException):
        ChatService._execute_return_eligibility_handoff_tool(
            ToolCallComplete(
                "call-invalid",
                "request_return_eligibility_check",
                {"order_item_id": "no"},
            )
        )
