"""Deterministic Slice 2 business facts; run after `alembic upgrade head`.

python -m app.scripts.seed_business_fixtures DATABASE_URL [--verify]
Reruns restore only these fixed fixture IDs to the values below, without deleting rows.
--verify runs twice in separate transactions and checks preservation / repeatability.
The reference timeline is fixed; its ages are history, not eligibility or timeout policy.
"""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session

from app.database.base import Base
from app.models.business import (
    AfterSalesRequest, AfterSalesRequestStatus, Customer, Order, OrderItem, OrderStatus,
    PaymentStatus, Product, Shipment, ShipmentStatus,
)


REFERENCE_TIME = datetime(2026, 9, 3, 12, tzinfo=timezone.utc)
EXPECTED_COUNTS = {Customer: 2, Product: 2, Order: 7, OrderItem: 8, Shipment: 6, AfterSalesRequest: 3}


def fixture_id(label):
    return uuid5(NAMESPACE_URL, f"https://project-offer.invalid/fixtures/slice2/{label}")


def fixture_rows():
    t = REFERENCE_TIME
    return [
        Customer(id=fixture_id("customer-a"), name="Demo Customer A", email="a@example.invalid"),
        Customer(id=fixture_id("customer-b"), name="Demo Customer B", email="b@example.invalid"),
        Product(id=fixture_id("mouse"), name="Demo Mouse", category="electronics",
                price=Decimal("39.90"), supports_no_reason_return=True),
        Product(id=fixture_id("engraved-mug"), name="Demo Engraved Mug", category="customized",
                price=Decimal("89.00"), supports_no_reason_return=False),
        Order(id=fixture_id("a-pending"), customer_id=fixture_id("customer-a"),
              status=OrderStatus.ACTIVE, payment_status=PaymentStatus.PENDING,
              created_at=t - timedelta(hours=1)),
        Order(id=fixture_id("a-transit"), customer_id=fixture_id("customer-a"),
              status=OrderStatus.ACTIVE, payment_status=PaymentStatus.PAID,
              created_at=t - timedelta(days=5)),
        Order(id=fixture_id("a-delivered"), customer_id=fixture_id("customer-a"),
              status=OrderStatus.COMPLETED, payment_status=PaymentStatus.PAID,
              created_at=t - timedelta(days=6)),
        Order(id=fixture_id("a-older-delivered"), customer_id=fixture_id("customer-a"),
              status=OrderStatus.COMPLETED, payment_status=PaymentStatus.PAID,
              created_at=t - timedelta(days=120)),
        Order(id=fixture_id("b-exception"), customer_id=fixture_id("customer-b"),
              status=OrderStatus.ACTIVE, payment_status=PaymentStatus.PAID,
              created_at=t - timedelta(days=60)),
        Order(id=fixture_id("b-cancelled"), customer_id=fixture_id("customer-b"),
              status=OrderStatus.CANCELLED, payment_status=PaymentStatus.PENDING,
              created_at=t - timedelta(days=10)),
        Order(id=fixture_id("b-refunded"), customer_id=fixture_id("customer-b"),
              status=OrderStatus.COMPLETED, payment_status=PaymentStatus.REFUNDED,
              created_at=t - timedelta(days=90)),
        OrderItem(id=fixture_id("item-a-pending"), order_id=fixture_id("a-pending"),
                  product_id=fixture_id("mouse"), quantity=1, unit_price=Decimal("39.90")),
        OrderItem(id=fixture_id("item-a-transit"), order_id=fixture_id("a-transit"),
                  product_id=fixture_id("mouse"), quantity=2, unit_price=Decimal("39.90")),
        OrderItem(id=fixture_id("item-a-delivered-mouse"), order_id=fixture_id("a-delivered"),
                  product_id=fixture_id("mouse"), quantity=1, unit_price=Decimal("39.90")),
        OrderItem(id=fixture_id("item-a-delivered-mug"), order_id=fixture_id("a-delivered"),
                  product_id=fixture_id("engraved-mug"), quantity=1, unit_price=Decimal("89.00")),
        OrderItem(id=fixture_id("item-a-older-delivered"), order_id=fixture_id("a-older-delivered"),
                  product_id=fixture_id("mouse"), quantity=1, unit_price=Decimal("29.90")),
        OrderItem(id=fixture_id("item-b-exception"), order_id=fixture_id("b-exception"),
                  product_id=fixture_id("mouse"), quantity=1, unit_price=Decimal("39.90")),
        OrderItem(id=fixture_id("item-b-cancelled"), order_id=fixture_id("b-cancelled"),
                  product_id=fixture_id("engraved-mug"), quantity=1, unit_price=Decimal("89.00")),
        OrderItem(id=fixture_id("item-b-refunded"), order_id=fixture_id("b-refunded"),
                  product_id=fixture_id("mouse"), quantity=1, unit_price=Decimal("29.90")),
        Shipment(id=fixture_id("shipment-a-pending"), order_id=fixture_id("a-pending"),
                 tracking_number=None, status=ShipmentStatus.PENDING,
                 updated_at=t - timedelta(minutes=30), delivered_at=None),
        Shipment(id=fixture_id("shipment-a-transit"), order_id=fixture_id("a-transit"),
                 tracking_number="DEMO-A-TRANSIT", status=ShipmentStatus.IN_TRANSIT,
                 updated_at=t - timedelta(days=1), delivered_at=None),
        Shipment(id=fixture_id("shipment-a-delivered"), order_id=fixture_id("a-delivered"),
                 tracking_number="DEMO-A-DELIVERED", status=ShipmentStatus.DELIVERED,
                 updated_at=t - timedelta(days=2), delivered_at=t - timedelta(days=2)),
        Shipment(id=fixture_id("shipment-a-older-delivered"), order_id=fixture_id("a-older-delivered"),
                 tracking_number="DEMO-A-OLDER", status=ShipmentStatus.DELIVERED,
                 updated_at=t - timedelta(days=110), delivered_at=t - timedelta(days=110)),
        Shipment(id=fixture_id("shipment-b-exception"), order_id=fixture_id("b-exception"),
                 tracking_number="DEMO-B-EXCEPTION", status=ShipmentStatus.EXCEPTION,
                 updated_at=t - timedelta(days=50), delivered_at=None),
        Shipment(id=fixture_id("shipment-b-refunded"), order_id=fixture_id("b-refunded"),
                 tracking_number="DEMO-B-REFUNDED", status=ShipmentStatus.DELIVERED,
                 updated_at=t - timedelta(days=85), delivered_at=t - timedelta(days=85)),
        # "return" is a sample type, not a newly frozen type vocabulary.
        AfterSalesRequest(id=fixture_id("request-a-rejected"), order_id=fixture_id("a-delivered"),
                          order_item_id=fixture_id("item-a-delivered-mouse"), type="return",
                          reason="No longer needed", status=AfterSalesRequestStatus.REJECTED,
                          created_at=t - timedelta(hours=36)),
        AfterSalesRequest(id=fixture_id("request-a-requested"), order_id=fixture_id("a-delivered"),
                          order_item_id=fixture_id("item-a-delivered-mouse"), type="return",
                          reason="No longer needed; packaging details provided", status=AfterSalesRequestStatus.REQUESTED,
                          created_at=t - timedelta(hours=12)),
        AfterSalesRequest(id=fixture_id("request-b-refunded"), order_id=fixture_id("b-refunded"),
                          order_item_id=fixture_id("item-b-refunded"), type="return",
                          reason="Historical return request", status=AfterSalesRequestStatus.REFUNDED,
                          created_at=t - timedelta(days=84)),
    ]


def seed(connection):
    with Session(connection) as session:
        for row in fixture_rows():
            session.merge(row)
        session.flush()


def verify(connection):
    expected = fixture_rows()
    ids = [row.id for row in expected]
    assert len(set(ids)) == 28
    with Session(connection) as session:
        records = {
            model: session.scalars(select(model).where(model.id.in_(ids))).all()
            for model in EXPECTED_COUNTS
        }
        assert {model: len(rows) for model, rows in records.items()} == EXPECTED_COUNTS
        for row in expected:
            actual = session.get(type(row), row.id)
            assert all(getattr(actual, c.name) == getattr(row, c.name) for c in row.__table__.columns)
        assert {p.supports_no_reason_return for p in records[Product]} == {True, False}
        assert {o.customer_id for o in records[Order]} == {c.id for c in records[Customer]}
        assert {o.status for o in records[Order]} == {OrderStatus.ACTIVE, OrderStatus.COMPLETED, OrderStatus.CANCELLED}
        assert any(len(o.order_items) > 1 for o in records[Order])
        assert any(o.payment_status == PaymentStatus.REFUNDED for o in records[Order])
        for order in records[Order]:
            assert order.customer in records[Customer] and order in order.customer.orders
        for item in records[OrderItem]:
            assert item.order in records[Order] and item.product in records[Product]
        assert {s.status for s in records[Shipment]} == {
            ShipmentStatus.PENDING, ShipmentStatus.IN_TRANSIT, ShipmentStatus.DELIVERED, ShipmentStatus.EXCEPTION,
        }
        for shipment in records[Shipment]:
            assert shipment.order in records[Order]
            assert shipment.order.created_at <= shipment.updated_at <= REFERENCE_TIME
            if shipment.delivered_at is not None:
                assert shipment.order.created_at <= shipment.delivered_at <= shipment.updated_at
        assert {r.status for r in records[AfterSalesRequest]} == {
            AfterSalesRequestStatus.REQUESTED, AfterSalesRequestStatus.REJECTED, AfterSalesRequestStatus.REFUNDED,
        }
        for request in records[AfterSalesRequest]:
            assert request.order in records[Order] and request.order_item in records[OrderItem]
            assert request.order_item.order_id == request.order_id
            assert request in request.order.after_sales_requests and request in request.order_item.after_sales_requests
            assert request.order.created_at <= request.created_at <= REFERENCE_TIME
    print("PASS: 2 customers, 2 products, 7 orders, 8 items, 6 shipments, 3 requests; "
          "exact facts, ownership, relationships and cross-order consistency", flush=True)


async def main(url, verify_twice):
    engine = create_async_engine(url)
    ids = [row.id for row in fixture_rows()]
    tables = Base.metadata.sorted_tables
    # ponytail: full snapshots suit this small demo DB; use targeted checks if data volume grows.
    try:
        async with engine.connect() as connection:
            preserved = await connection.run_sync(lambda c: {
                table.name: c.execute(select(table).where(table.c.id.not_in(ids)).order_by(table.c.id)).all()
                for table in tables
            })
        counts = None
        for run in range(2 if verify_twice else 1):
            async with engine.begin() as connection:
                await connection.run_sync(seed)
                await connection.run_sync(verify)
                unchanged = await connection.run_sync(lambda c: {
                    table.name: c.execute(select(table).where(table.c.id.not_in(ids)).order_by(table.c.id)).all()
                    for table in tables
                })
                assert unchanged == preserved, "Non-fixture data changed"
                current_counts = await connection.run_sync(lambda c: {
                    table.name: c.scalar(select(func.count()).select_from(table)) for table in tables
                })
                if counts is not None:
                    assert current_counts == counts, "Second run changed record counts"
                counts = current_counts
            print(f"PASS: committed run {run + 1}; non-fixture data unchanged; {counts}", flush=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database_url", help="Explicit PostgreSQL URL with Slice 1 migration applied")
    parser.add_argument("--verify", action="store_true", help="Run twice to verify repeatability")
    args = parser.parse_args()
    asyncio.run(main(args.database_url, args.verify))
