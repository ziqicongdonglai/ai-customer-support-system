"""Slice 1 check on an EMPTY disposable PostgreSQL database (no test framework).

Run from the backend root:
python -m app.scripts.verify_business_persistence postgresql+asyncpg://.../offer_slice1_validation
The database name must start with offer_slice1_validation. All test data is disposable.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session, configure_mappers

from app.database.base import Base
from app.models import (
    AfterSalesRequest, Conversation, Customer, Message, Order, OrderItem, Product, Shipment,
)
from app.models.business import AfterSalesRequestStatus, OrderStatus, PaymentStatus, ShipmentStatus


BUSINESS_TABLES = {
    "customers", "products", "orders", "order_items", "shipments", "after_sales_requests",
}
LEGACY_TABLES = {"conversations", "messages", "alembic_version"}
CURRENT_TABLES = BUSINESS_TABLES | LEGACY_TABLES | {"workflows"}
LEGACY_ID = uuid.uuid4()
STAMP = datetime(2026, 9, 3, 8, 30, tzinfo=timezone(timedelta(hours=8)))


def verify_business(connection):
    assert set(inspect(connection).get_table_names()) == CURRENT_TABLES
    assert not compare_metadata(MigrationContext.configure(connection), Base.metadata)
    with Session(connection) as session:
        customer = Customer(name="Slice check", email="slice@example.invalid")
        product = Product(name="Check product", category="check", price=Decimal("19.99"),
                          supports_no_reason_return=True)
        order = Order(customer=customer, status=OrderStatus.COMPLETED, payment_status=PaymentStatus.PAID)
        item = OrderItem(order=order, product=product, quantity=2, unit_price=Decimal("12.34"))
        shipment = Shipment(order=order, status=ShipmentStatus.DELIVERED, updated_at=STAMP, delivered_at=STAMP)
        pending = Shipment(order=order, status=ShipmentStatus.PENDING, updated_at=STAMP)
        request = AfterSalesRequest(order=order, order_item=item, type="return",
                                    reason="Verification only", status=AfterSalesRequestStatus.REQUESTED)
        session.add_all([customer, product, order, item, shipment, pending, request])
        session.flush()
        order_id, shipment_id, pending_id = order.id, shipment.id, pending.id
        session.expunge_all()
        order = session.get(Order, order_id)
        item = order.order_items[0]
        request = order.after_sales_requests[0]
        shipment = session.get(Shipment, shipment_id)
        pending = session.get(Shipment, pending_id)
        assert order.customer.orders == [order]
        assert item.order is order and item.product.order_items == [item]
        assert len(order.shipments) == 2 and all(s.order is order for s in order.shipments)
        assert request.order is order and request.order_item is item
        assert item.after_sales_requests == [request]
        assert item.unit_price == Decimal("12.34") and isinstance(item.unit_price, Decimal)
        assert item.product.price == Decimal("19.99") and isinstance(item.product.price, Decimal)
        assert pending.tracking_number is None and pending.delivered_at is None
        assert shipment.delivered_at == STAMP and shipment.updated_at == STAMP
        for timestamp in (order.created_at, request.created_at, shipment.updated_at, shipment.delivered_at):
            assert timestamp.utcoffset() == timedelta(0)
        shipment.tracking_number = "verification-tracking"
        session.flush()
        session.refresh(shipment)
        assert shipment.updated_at == STAMP
        for table_name in sorted(BUSINESS_TABLES):
            table = Base.metadata.tables[table_name]
            for foreign_key in table.foreign_keys:
                assert foreign_key.ondelete is None
                try:
                    with session.begin_nested():
                        session.execute(table.update().values({foreign_key.parent.name: uuid.uuid4()}))
                except IntegrityError as error:
                    assert error.orig.sqlstate == "23503", error
                else:
                    raise AssertionError(f"Invalid FK accepted: {foreign_key}")
        try:
            with session.begin_nested():
                session.execute(Order.__table__.delete().where(Order.id == order.id))
        except IntegrityError as error:
            assert error.orig.sqlstate == "23503", error
        else:
            raise AssertionError("Referenced order deletion was accepted")
    print("PASS: six tables, metadata, relationships, Decimal, UTC, nullable shipment fields, "
          "multiple shipments, logistics timestamp, six FKs and deletion integrity", flush=True)


async def check_database(url, stage):
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            tables = set(await connection.run_sync(lambda c: inspect(c).get_table_names()))
            if stage == "empty":
                assert not tables, "Refusing to migrate a non-empty validation database"
                return
            if stage == "seed_legacy":
                await connection.execute(Conversation.__table__.insert().values(id=LEGACY_ID, title="Slice 1"))
                await connection.execute(Message.__table__.insert().values(
                    conversation_id=LEGACY_ID, role="user", content="Preserve legacy data",
                ))
                return
            if stage == "downgraded":
                assert tables == LEGACY_TABLES, tables
            else:
                await connection.run_sync(verify_business)
            def verify_legacy(sync_connection):
                with Session(sync_connection) as session:
                    conversation = session.get(Conversation, LEGACY_ID)
                    assert conversation.title == "Slice 1"
                    message = conversation.messages[0]
                    assert message.content == "Preserve legacy data"
                    assert message.status == "completed" and message.sources == []
                    assert message.conversation is conversation
            await connection.run_sync(verify_legacy)
            print(f"PASS: {stage}; Conversation / Message data and relationships preserved", flush=True)
    finally:
        await engine.dispose()


def main():
    url = sys.argv[1]
    target = make_url(url)
    if target.drivername != "postgresql+asyncpg" or not (target.database or "").startswith("offer_slice1_validation"):
        raise SystemExit("Use an empty disposable PostgreSQL database named offer_slice1_validation...")
    os.environ["DATABASE_URL"] = url
    configure_mappers()
    assert set(Base.metadata.tables) == CURRENT_TABLES - {"alembic_version"}
    asyncio.run(check_database(url, "empty"))
    config = Config("alembic.ini")
    command.upgrade(config, "3e2f2f376ffa")
    asyncio.run(check_database(url, "seed_legacy"))
    command.upgrade(config, "head")
    asyncio.run(check_database(url, "upgraded"))
    command.downgrade(config, "3e2f2f376ffa")
    asyncio.run(check_database(url, "downgraded"))
    command.upgrade(config, "head")
    asyncio.run(check_database(url, "re-upgraded"))


if __name__ == "__main__":
    main()
