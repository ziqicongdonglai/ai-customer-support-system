from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager, joinedload, raiseload, selectinload

from app.models.business import AfterSalesRequest, Customer, Order, OrderItem, Shipment


class BusinessRepository:
    """Customer-scoped reads; only explicitly requested relationships are loaded."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_return_eligibility_candidates(
        self, customer_id: UUID, limit: int,
    ) -> list[OrderItem] | None:
        # trusted customer ownership 在 SQL read boundary 强制执行；候选发现只扩大
        # 可识别的 owned purchases，不把 Product/Shipment 条件误当作 eligibility 判断。
        if await self.db.get(Customer, customer_id) is None:
            return None
        # ownership 必须由 SQL 保证；候选发现只负责识别购买项，故意不按任何
        # 配送状态、商品属性或资格结果过滤。
        return list((await self.db.scalars(
            select(OrderItem)
            .join(OrderItem.order)
            .where(Order.customer_id == customer_id)
            .options(
                contains_eager(OrderItem.order),
                joinedload(OrderItem.product),
                raiseload("*"),
            )
            .order_by(Order.created_at.desc(), OrderItem.id.asc())
            .limit(limit)
        )).all())

    async def get_order(self, customer_id: UUID, order_id: UUID) -> Order | None:
        return await self.db.scalar(
            select(Order)
            .where(Order.id == order_id, Order.customer_id == customer_id)
            # selectinload：预加载订单的多个集合关系，
            # 避免把 Items、Shipments、Requests 全部 JOIN 后造成行数相乘。
            # joinedload：加载单个 OrderItem 对应的 Product，适合这一多对一关系。
            # raiseload("*")：阻止未声明关系触发隐式 lazy query，明确当前返回图的读取边界。
            .options(
                selectinload(Order.order_items).joinedload(OrderItem.product),
                selectinload(Order.shipments),
                selectinload(Order.after_sales_requests),
                raiseload("*"),
            )
        )

    async def get_order_item(self, customer_id: UUID, order_item_id: UUID) -> OrderItem | None:
        return await self.db.scalar(
            select(OrderItem)
            .join(OrderItem.order)
            .where(OrderItem.id == order_item_id, Order.customer_id == customer_id)
            .options(
                joinedload(OrderItem.product),
                selectinload(OrderItem.after_sales_requests),
                raiseload("*"),
            )
        )

    async def get_shipment(self, customer_id: UUID, shipment_id: UUID) -> Shipment | None:
        return await self.db.scalar(
            select(Shipment)
            .join(Shipment.order)
            .where(Shipment.id == shipment_id, Order.customer_id == customer_id)
            .options(raiseload("*"))
        )

    async def get_after_sales_request(
        self, customer_id: UUID, request_id: UUID,
    ) -> AfterSalesRequest | None:
        return await self.db.scalar(
            select(AfterSalesRequest)
            .join(AfterSalesRequest.order)
            .where(AfterSalesRequest.id == request_id, Order.customer_id == customer_id)
            .options(raiseload("*"))
        )
