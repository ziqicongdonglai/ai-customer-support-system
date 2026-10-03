"""Slice 4 deterministic business-rule checks on committed fixtures.

python -m app.scripts.verify_business_rules DATABASE_URL
All checks run in a PostgreSQL READ ONLY transaction.
"""
import asyncio
import sys
from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database.base import Base
from app.models.business import Order, OrderStatus, Shipment, ShipmentStatus
from app.repositories.business_repository import BusinessRepository
from app.scripts.seed_business_fixtures import REFERENCE_TIME, fixture_id, verify as verify_fixtures
from app.services.business_service import BusinessService, RuleResult


async def check_rules(connection):
    customer_a = fixture_id("customer-a")
    customer_b = fixture_id("customer-b")
    async with AsyncSession(bind=connection) as db:
        service = BusinessService(BusinessRepository(db))

        pending = await service.get_order(customer_a, fixture_id("a-pending"))
        transit = await service.get_order(customer_a, fixture_id("a-transit"))
        cancelled = await service.get_order(customer_b, fixture_id("b-cancelled"))
        no_shipment = Order(status=OrderStatus.ACTIVE)
        cancellation_cases = [
            ("active + pending", pending, RuleResult(True, "eligible")),
            ("non-pending shipment", transit, RuleResult(False, "shipment_not_pending")),
            ("non-active order", cancelled, RuleResult(False, "order_not_active")),
            ("active + no shipment", no_shipment, RuleResult(True, "eligible")),
        ]
        for name, order, expected in cancellation_cases:
            actual = service.check_cancellation_eligibility(order)
            assert actual == expected, (name, expected, actual)

        delivered = await service.get_order(customer_a, fixture_id("a-delivered"))
        older_delivered = await service.get_order(customer_a, fixture_id("a-older-delivered"))
        mouse = await service.get_order_item(customer_a, fixture_id("item-a-delivered-mouse"))
        mug = await service.get_order_item(customer_a, fixture_id("item-a-delivered-mug"))
        older_mouse = await service.get_order_item(customer_a, fixture_id("item-a-older-delivered"))
        pending_mouse = await service.get_order_item(customer_a, fixture_id("item-a-pending"))
        delivery_time = delivered.shipments[0].delivered_at
        return_cases = [
            ("inside window", mouse, delivered.shipments, REFERENCE_TIME,
             RuleResult(True, "eligible")),
            ("unsupported product", mug, delivered.shipments, REFERENCE_TIME,
             RuleResult(False, "product_not_eligible")),
            ("outside window", older_mouse, older_delivered.shipments, REFERENCE_TIME,
             RuleResult(False, "outside_return_window")),
            ("exact deadline", mouse, delivered.shipments, delivery_time + timedelta(days=7),
             RuleResult(True, "eligible")),
            ("after deadline", mouse, delivered.shipments,
             delivery_time + timedelta(days=7, microseconds=1),
             RuleResult(False, "outside_return_window")),
            ("ambiguous shipments", mouse, delivered.shipments * 2, REFERENCE_TIME,
             RuleResult(False, "insufficient_delivery_evidence")),
            ("shipment from another order", mouse, older_delivered.shipments, REFERENCE_TIME,
             RuleResult(False, "shipment_order_mismatch")),
            ("not delivered", pending_mouse, pending.shipments, REFERENCE_TIME,
             RuleResult(False, "not_delivered")),
        ]
        for name, item, shipments, now, expected in return_cases:
            actual = service.check_return_eligibility(item, shipments, now)
            assert actual == expected, (name, expected, actual)

        refunded_item = await service.get_order_item(customer_b, fixture_id("item-b-refunded"))
        duplicate_cases = [
            ("active request", mouse, RuleResult(True, "active_after_sales_exists")),
            ("only non-active", refunded_item, RuleResult(False, "no_active_after_sales")),
            ("no request", mug, RuleResult(False, "no_active_after_sales")),
        ]
        for name, item, expected in duplicate_cases:
            actual = service.has_active_after_sales(item)
            assert actual == expected, (name, expected, actual)

        stored = await service.get_shipment(customer_b, fixture_id("shipment-b-exception"))
        base = REFERENCE_TIME
        logistics_cases = [
            ("stored exception", stored, base, RuleResult(True, "stored_exception")),
            ("old non-delivered", Shipment(status=ShipmentStatus.IN_TRANSIT,
                                            updated_at=base - timedelta(hours=73)), base,
             RuleResult(True, "stale_non_delivered")),
            ("exactly 72 hours", Shipment(status=ShipmentStatus.IN_TRANSIT,
                                           updated_at=base - timedelta(hours=72)), base,
             RuleResult(False, "within_logistics_threshold")),
            ("beyond 72 hours", Shipment(status=ShipmentStatus.IN_TRANSIT,
                                          updated_at=base - timedelta(hours=72, microseconds=1)), base,
             RuleResult(True, "stale_non_delivered")),
            ("delivered", Shipment(status=ShipmentStatus.DELIVERED,
                                    updated_at=base - timedelta(days=10)), base,
             RuleResult(False, "delivered")),
            ("stale pending", Shipment(status=ShipmentStatus.PENDING,
                                        updated_at=base - timedelta(days=4)), base,
             RuleResult(True, "stale_non_delivered")),
        ]
        for name, shipment, now, expected in logistics_cases:
            actual = service.detect_logistics_exception(shipment, now)
            assert actual == expected, (name, expected, actual)

    print("PASS: cancellation 4; return 8 including exact deadline and cross-order evidence; duplicate 3; "
          "logistics 6 including strict 72-hour boundary and stale pending", flush=True)


async def main(url):
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            assert await connection.scalar(text("SHOW transaction_read_only")) == "on"
            await connection.run_sync(verify_fixtures)
            before = {
                table.name: (await connection.execute(select(table).order_by(table.c.id))).all()
                for table in Base.metadata.sorted_tables
            }
            await check_rules(connection)
            after = {
                table.name: (await connection.execute(select(table).order_by(table.c.id))).all()
                for table in Base.metadata.sorted_tables
            }
            assert before == after, "Rule checks changed stored data"
            print("PASS: PostgreSQL READ ONLY; all eight tables unchanged, including Conversation / Message",
                  flush=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
