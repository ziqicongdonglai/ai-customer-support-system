from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, NamedTuple
from uuid import UUID

from app.core.exceptions import ConfigurationException, NotFoundException
from app.models.business import (
    AfterSalesRequest,
    AfterSalesRequestStatus,
    Order,
    OrderItem,
    OrderStatus,
    Shipment,
    ShipmentStatus,
)
from app.repositories.business_repository import BusinessRepository


class RuleResult(NamedTuple):
    decision: bool
    reason: str


# 这是业务用例的应用层结果，刻意不依赖 FastAPI/Pydantic 的 HTTP schema。
class ReturnEligibilityResult(NamedTuple):
    outcome: Literal["eligible", "ineligible", "unavailable"]
    reason: str


class ReturnEligibilityCandidate(NamedTuple):
    order_item_id: UUID
    product_name: str
    quantity: int
    unit_price: Decimal
    order_created_at: datetime


class BusinessService:
    """Read boundary: customer_id must come from trusted application context, never LLM text.

    Missing and inaccessible IDs have the same NotFoundException. Rule methods make
    deterministic read-only decisions from explicitly supplied business state.
    """

    def __init__(self, business_repo: BusinessRepository):
        self.business_repo = business_repo

    async def list_return_eligibility_candidates(
        self, trusted_customer_id: UUID,
    ) -> list[ReturnEligibilityCandidate]:
        # Candidate Discovery 只帮助用户识别“哪次购买”，不回答“能否退货”；
        # 因此不按 eligibility rule 预过滤，也不把候选投影当作 Business State snapshot。
        items = await self.business_repo.list_return_eligibility_candidates(
            trusted_customer_id, limit=20,
        )
        if items is None:
            raise ConfigurationException("Demo customer is unavailable")
        # 该投影只帮助用户识别购买项；Resume 仍须重新验证归属并执行当前资格判断。
        return [
            ReturnEligibilityCandidate(
                order_item_id=item.id,
                product_name=item.product.name,
                quantity=item.quantity,
                unit_price=item.unit_price,
                order_created_at=item.order.created_at,
            )
            for item in items
        ]

    async def get_order(self, customer_id: UUID, order_id: UUID) -> Order:
        order = await self.business_repo.get_order(customer_id, order_id)
        if order is None:
            raise NotFoundException("Order not found")
        return order

    async def get_order_item(self, customer_id: UUID, order_item_id: UUID) -> OrderItem:
        item = await self.business_repo.get_order_item(customer_id, order_item_id)
        if item is None:
            raise NotFoundException("Order item not found")
        return item

    async def get_shipment(self, customer_id: UUID, shipment_id: UUID) -> Shipment:
        shipment = await self.business_repo.get_shipment(customer_id, shipment_id)
        if shipment is None:
            raise NotFoundException("Shipment not found")
        return shipment

    async def get_after_sales_request(self, customer_id: UUID, request_id: UUID) -> AfterSalesRequest:
        request = await self.business_repo.get_after_sales_request(customer_id, request_id)
        if request is None:
            raise NotFoundException("After-sales request not found")
        return request

    # BusinessService 统一负责 customer-scoped 当前事实读取与确定性规则执行；
    # WorkflowService 只决定何时调用该业务用例。
    async def evaluate_return_eligibility(
        self, customer_id: UUID, order_item_id: UUID, now: datetime,
    ) -> ReturnEligibilityResult:
        # 每次调用都通过 customer-scoped repository 读取 current Business State；
        # opaque order_item_id 既不是 ownership proof，也不是 eligibility proof。
        try:
            item = await self.get_order_item(customer_id, order_item_id)
            order = await self.get_order(customer_id, item.order_id)
        except NotFoundException:
            # 缺失与跨客户资源统一折叠为 unavailable，避免泄露存在性或归属关系。
            return ReturnEligibilityResult("unavailable", "order_item_unavailable")

        result = self.check_return_eligibility(item, order.shipments, now)
        return ReturnEligibilityResult(
            "eligible" if result.decision else "ineligible",
            result.reason,
        )

    def check_cancellation_eligibility(self, order: Order) -> RuleResult:
        if order.status != OrderStatus.ACTIVE:
            return RuleResult(False, "order_not_active")
        if any(shipment.status != ShipmentStatus.PENDING for shipment in order.shipments):
            return RuleResult(False, "shipment_not_pending")
        return RuleResult(True, "eligible")

    def check_return_eligibility(
        self, item: OrderItem, shipments: Sequence[Shipment], now: datetime,
    ) -> RuleResult:
        if not item.product.supports_no_reason_return:
            return RuleResult(False, "product_not_eligible")
        if len(shipments) != 1:
            return RuleResult(False, "insufficient_delivery_evidence")
        shipment = shipments[0]
        if shipment.order_id != item.order_id:
            return RuleResult(False, "shipment_order_mismatch")
        if shipment.status != ShipmentStatus.DELIVERED or shipment.delivered_at is None:
            return RuleResult(False, "not_delivered")
        if now.utcoffset() is None or shipment.delivered_at.utcoffset() is None:
            raise ValueError("Return evaluation requires timezone-aware timestamps")
        if now <= shipment.delivered_at + timedelta(days=7):
            return RuleResult(True, "eligible")
        return RuleResult(False, "outside_return_window")

    def has_active_after_sales(self, item: OrderItem) -> RuleResult:
        active_statuses = {
            AfterSalesRequestStatus.REQUESTED,
            AfterSalesRequestStatus.APPROVED,
            AfterSalesRequestStatus.RETURNING,
            AfterSalesRequestStatus.RECEIVED,
        }
        if any(request.status in active_statuses for request in item.after_sales_requests):
            return RuleResult(True, "active_after_sales_exists")
        return RuleResult(False, "no_active_after_sales")

    def detect_logistics_exception(self, shipment: Shipment, now: datetime) -> RuleResult:
        if shipment.status == ShipmentStatus.EXCEPTION:
            return RuleResult(True, "stored_exception")
        if shipment.status == ShipmentStatus.DELIVERED:
            return RuleResult(False, "delivered")
        if now.utcoffset() is None or shipment.updated_at.utcoffset() is None:
            raise ValueError("Logistics evaluation requires timezone-aware timestamps")
        if now - shipment.updated_at > timedelta(hours=72):
            return RuleResult(True, "stale_non_delivered")
        return RuleResult(False, "within_logistics_threshold")
