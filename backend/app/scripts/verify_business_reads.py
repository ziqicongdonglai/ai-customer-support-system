"""Slice 3 check on PostgreSQL with Slice 1 schema and Slice 2 fixtures already present.

python -m app.scripts.verify_business_reads DATABASE_URL
All checks run in a PostgreSQL READ ONLY transaction; no seeding or migration occurs here.
"""
import asyncio
import sys
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.exceptions import NotFoundException
from app.database.base import Base
from app.models.business import OrderStatus, PaymentStatus, ShipmentStatus
from app.repositories.business_repository import BusinessRepository
from app.scripts.seed_business_fixtures import REFERENCE_TIME, fixture_id, verify as verify_fixtures
from app.services.business_service import BusinessService


async def check_reads(connection):
    a, b = fixture_id("customer-a"), fixture_id("customer-b")
    missing = fixture_id("missing")
    owned = {}
    async with AsyncSession(bind=connection) as db:
        repo = BusinessRepository(db)
        service = BusinessService(repo)
        cases = [
            ("order", repo.get_order, service.get_order,
             "a-delivered", "b-refunded", "Order not found"),
            ("item", repo.get_order_item, service.get_order_item,
             "item-a-delivered-mouse", "item-b-refunded", "Order item not found"),
            ("shipment", repo.get_shipment, service.get_shipment,
             "shipment-a-delivered", "shipment-b-refunded", "Shipment not found"),
            ("request", repo.get_after_sales_request, service.get_after_sales_request,
             "request-a-requested", "request-b-refunded", "After-sales request not found"),
        ]
        for kind, repo_get, service_get, a_label, b_label, message in cases:
            # Prime both customers' objects in the same identity map before testing denial.
            for actor, label in ((a, a_label), (b, b_label)):
                result = await service_get(actor, fixture_id(label))
                assert result.id == fixture_id(label)
                owned[kind, actor] = result
            for actor, target in ((a, fixture_id(b_label)), (b, fixture_id(a_label)),
                                  (a, missing), (b, missing), (missing, fixture_id(a_label))):
                assert await repo_get(actor, target) is None
                try:
                    await service_get(actor, target)
                except NotFoundException as error:
                    assert type(error) is NotFoundException and str(error) == message
                else:
                    raise AssertionError(f"{kind}: inaccessible or missing data was returned")
            print(f"PASS: {kind}; A/B own IDs succeed; cross-customer and unknown IDs/context "
                  "produce identical not-found results, including cached IDs", flush=True)
        pending = await service.get_order(a, fixture_id("a-pending"))
        cancelled = await service.get_order(b, fixture_id("b-cancelled"))
        mug_item = await service.get_order_item(a, fixture_id("item-a-delivered-mug"))

    # Detached results prove the promised relationships need no additional database IO.
    order = owned["order", a]
    assert order.customer_id == a and order.status == OrderStatus.COMPLETED
    assert order.payment_status == PaymentStatus.PAID
    assert {i.id for i in order.order_items} == {
        fixture_id("item-a-delivered-mouse"), fixture_id("item-a-delivered-mug"),
    }
    assert {i.product.id for i in order.order_items} == {fixture_id("mouse"), fixture_id("engraved-mug")}
    assert {i.product.supports_no_reason_return for i in order.order_items} == {True, False}
    assert all(i.order_id == order.id for i in order.order_items)
    assert [s.id for s in order.shipments] == [fixture_id("shipment-a-delivered")]
    assert {r.id for r in order.after_sales_requests} == {
        fixture_id("request-a-rejected"), fixture_id("request-a-requested"),
    }
    assert all(r.order_id == order.id and r.order_item_id == fixture_id("item-a-delivered-mouse")
               for r in order.after_sales_requests)
    item = owned["item", a]
    assert item.order_id == order.id and item.product.id == fixture_id("mouse")
    assert item.unit_price == item.product.price == Decimal("39.90")
    assert {r.id for r in item.after_sales_requests} == {r.id for r in order.after_sales_requests}
    shipment = owned["shipment", a]
    assert shipment.order_id == order.id and shipment.status == ShipmentStatus.DELIVERED
    assert shipment.delivered_at == REFERENCE_TIME - timedelta(days=2)
    assert shipment.tracking_number == "DEMO-A-DELIVERED"
    request = owned["request", a]
    assert request.order_id == order.id and request.order_item_id == item.id
    assert owned["order", b].customer_id == b
    assert owned["order", b].payment_status == PaymentStatus.REFUNDED
    assert pending.after_sales_requests == [] and pending.shipments[0].tracking_number is None
    assert cancelled.shipments == [] and mug_item.after_sales_requests == []
    try:
        item.product.order_items
    except InvalidRequestError:
        pass
    else:
        raise AssertionError("Unrequested product-to-orders traversal was available")
    print("PASS: detached order/item/product/shipment/history facts; empty histories; "
          "unrequested relationship traversal blocked", flush=True)


async def main(url):
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            assert await connection.scalar(text("SHOW transaction_read_only")) == "on"
            await connection.run_sync(verify_fixtures)
            # ponytail: full snapshots fit the small validation DB; scope them if data volume grows.
            before = {
                table.name: (await connection.execute(select(table).order_by(table.c.id))).all()
                for table in Base.metadata.sorted_tables
            }
            await check_reads(connection)
            after = {
                table.name: (await connection.execute(select(table).order_by(table.c.id))).all()
                for table in Base.metadata.sorted_tables
            }
            assert before == after, "Read checks changed stored data"
            print("PASS: PostgreSQL READ ONLY; all eight tables unchanged (rows and values), "
                  "including Conversation / Message", flush=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
