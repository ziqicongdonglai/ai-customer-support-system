"""Verify Mission 5 Phase 2 Slice 1 against an empty disposable PostgreSQL database.

Run from the backend root:
python -m app.scripts.verify_workflow postgresql+asyncpg://.../offer_phase2_slice1_validation
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
from sqlalchemy import delete, func, inspect, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.demo_principal import DEMO_CUSTOMER_ID
from app.core.exceptions import (
    ActiveWorkflowConflictException,
    WorkflowUnavailableException,
)
from app.database.base import Base
from app.models import Conversation, Customer, Order, OrderItem, Product, Shipment, Workflow
from app.models.business import OrderStatus, PaymentStatus, ShipmentStatus
from app.models.workflow import WorkflowStatus
from app.repositories.business_repository import BusinessRepository
from app.repositories.workflow_repository import WorkflowRepository
from app.services.business_service import BusinessService
from app.services.workflow_service import WorkflowService


OTHER_CUSTOMER_ID = uuid.uuid4()
ELIGIBLE_PRODUCT_ID = uuid.uuid4()
INELIGIBLE_PRODUCT_ID = uuid.uuid4()
FRESH_PRODUCT_ID = uuid.uuid4()
ELIGIBLE_ORDER_ID = uuid.uuid4()
INELIGIBLE_ORDER_ID = uuid.uuid4()
OUTSIDE_ORDER_ID = uuid.uuid4()
FRESH_ORDER_ID = uuid.uuid4()
CROSS_CUSTOMER_ORDER_ID = uuid.uuid4()
ELIGIBLE_ITEM_ID = uuid.uuid4()
INELIGIBLE_ITEM_ID = uuid.uuid4()
OUTSIDE_ITEM_ID = uuid.uuid4()
FRESH_ITEM_ID = uuid.uuid4()
CROSS_CUSTOMER_ITEM_ID = uuid.uuid4()
UNKNOWN_ITEM_ID = uuid.uuid4()


async def with_service(session_factory, operation):
    async with session_factory() as session:
        return await operation(WorkflowService(
            WorkflowRepository(session),
            BusinessService(BusinessRepository(session)),
        ))


async def expect_unavailable(operation):
    try:
        await operation
    except WorkflowUnavailableException as error:
        assert str(error) == "Workflow unavailable"
    else:
        raise AssertionError("Expected Workflow unavailable")


def business_rows(now: datetime):
    products = [
        Product(id=ELIGIBLE_PRODUCT_ID, name="Eligible", category="test",
                price=Decimal("10.00"), supports_no_reason_return=True),
        Product(id=INELIGIBLE_PRODUCT_ID, name="Ineligible", category="test",
                price=Decimal("10.00"), supports_no_reason_return=False),
        Product(id=FRESH_PRODUCT_ID, name="Freshness", category="test",
                price=Decimal("10.00"), supports_no_reason_return=True),
    ]
    order_specs = [
        (ELIGIBLE_ORDER_ID, DEMO_CUSTOMER_ID, ELIGIBLE_ITEM_ID,
         ELIGIBLE_PRODUCT_ID, now - timedelta(days=1)),
        (INELIGIBLE_ORDER_ID, DEMO_CUSTOMER_ID, INELIGIBLE_ITEM_ID,
         INELIGIBLE_PRODUCT_ID, now - timedelta(days=1)),
        (OUTSIDE_ORDER_ID, DEMO_CUSTOMER_ID, OUTSIDE_ITEM_ID,
         ELIGIBLE_PRODUCT_ID, now - timedelta(days=8)),
        (FRESH_ORDER_ID, DEMO_CUSTOMER_ID, FRESH_ITEM_ID,
         FRESH_PRODUCT_ID, now - timedelta(days=1)),
        (CROSS_CUSTOMER_ORDER_ID, OTHER_CUSTOMER_ID, CROSS_CUSTOMER_ITEM_ID,
         ELIGIBLE_PRODUCT_ID, now - timedelta(days=1)),
    ]
    rows = [*products]
    for order_id, customer_id, item_id, product_id, delivered_at in order_specs:
        rows.extend([
            Order(id=order_id, customer_id=customer_id, status=OrderStatus.COMPLETED,
                  payment_status=PaymentStatus.PAID, created_at=delivered_at - timedelta(days=1)),
            OrderItem(id=item_id, order_id=order_id, product_id=product_id,
                      quantity=1, unit_price=Decimal("10.00")),
            Shipment(id=uuid.uuid4(), order_id=order_id, tracking_number=None,
                     status=ShipmentStatus.DELIVERED, updated_at=delivered_at,
                     delivered_at=delivered_at),
        ])
    return rows


async def verify_runtime(url: str) -> None:
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    conversations = [Conversation(title=f"Slice 1 {index}") for index in range(14)]
    now = datetime.now(timezone.utc)
    try:
        async with sessions() as session:
            session.add_all([
                Customer(
                    id=DEMO_CUSTOMER_ID,
                    name="Demo Customer A",
                    email="a@example.invalid",
                ),
                Customer(
                    id=OTHER_CUSTOMER_ID,
                    name="Demo Customer B",
                    email="b@example.invalid",
                ),
                *business_rows(now),
                *conversations,
            ])
            await session.commit()

        c = [conversation.id for conversation in conversations]

        waiting = await with_service(
            sessions,
            lambda service: service.start(c[0], DEMO_CUSTOMER_ID, None),
        )
        assert waiting.status == WorkflowStatus.WAITING_FOR_CLARIFICATION
        assert waiting.clarification and "order_item_id" in waiting.clarification
        assert waiting.return_eligibility is None

        async with sessions() as fresh_session:
            persisted = await WorkflowRepository(fresh_session).get_by_id(waiting.workflow_id)
            assert persisted is not None
            assert persisted.status == WorkflowStatus.WAITING_FOR_CLARIFICATION
            assert persisted.created_at.utcoffset() is not None
            assert persisted.updated_at.utcoffset() is not None

        complete = await with_service(
            sessions,
            lambda service: service.start(c[1], DEMO_CUSTOMER_ID, ELIGIBLE_ITEM_ID),
        )
        assert complete.status == WorkflowStatus.COMPLETED
        assert complete.clarification is None
        assert complete.return_eligibility.outcome == "eligible"
        assert complete.return_eligibility.reason == "eligible"

        product_ineligible = await with_service(
            sessions,
            lambda service: service.start(c[7], DEMO_CUSTOMER_ID, INELIGIBLE_ITEM_ID),
        )
        assert product_ineligible.return_eligibility.outcome == "ineligible"
        assert product_ineligible.return_eligibility.reason == "product_not_eligible"

        outside_window = await with_service(
            sessions,
            lambda service: service.start(c[8], DEMO_CUSTOMER_ID, OUTSIDE_ITEM_ID),
        )
        assert outside_window.return_eligibility.outcome == "ineligible"
        assert outside_window.return_eligibility.reason == "outside_return_window"

        unknown = await with_service(
            sessions,
            lambda service: service.start(c[9], DEMO_CUSTOMER_ID, UNKNOWN_ITEM_ID),
        )
        cross_customer = await with_service(
            sessions,
            lambda service: service.start(c[10], DEMO_CUSTOMER_ID, CROSS_CUSTOMER_ITEM_ID),
        )
        assert unknown.return_eligibility == cross_customer.return_eligibility
        assert unknown.return_eligibility.outcome == "unavailable"
        assert unknown.return_eligibility.reason == "order_item_unavailable"

        async def concurrent_start():
            try:
                return await with_service(
                    sessions,
                    lambda service: service.start(c[2], DEMO_CUSTOMER_ID, None),
                )
            except ActiveWorkflowConflictException:
                return None

        starts = await asyncio.gather(concurrent_start(), concurrent_start())
        assert sum(result is not None for result in starts) == 1

        completed_with_active = await with_service(
            sessions,
            lambda service: service.start(c[0], DEMO_CUSTOMER_ID, ELIGIBLE_ITEM_ID),
        )
        another_completed = await with_service(
            sessions,
            lambda service: service.start(c[0], DEMO_CUSTOMER_ID, ELIGIBLE_ITEM_ID),
        )
        assert completed_with_active.status == another_completed.status == WorkflowStatus.COMPLETED

        resumed = await with_service(
            sessions,
            lambda service: service.resume(
                waiting.workflow_id, c[0], DEMO_CUSTOMER_ID, ELIGIBLE_ITEM_ID,
            ),
        )
        assert resumed.status == WorkflowStatus.COMPLETED
        assert resumed.return_eligibility.outcome == "eligible"

        waiting_ineligible = await with_service(
            sessions,
            lambda service: service.start(c[11], DEMO_CUSTOMER_ID, None),
        )
        resumed_ineligible = await with_service(
            sessions,
            lambda service: service.resume(
                waiting_ineligible.workflow_id, c[11], DEMO_CUSTOMER_ID,
                INELIGIBLE_ITEM_ID,
            ),
        )
        assert resumed_ineligible.return_eligibility.outcome == "ineligible"
        assert resumed_ineligible.return_eligibility.reason == "product_not_eligible"

        waiting_unavailable = await with_service(
            sessions,
            lambda service: service.start(c[12], DEMO_CUSTOMER_ID, None),
        )
        resumed_unavailable = await with_service(
            sessions,
            lambda service: service.resume(
                waiting_unavailable.workflow_id, c[12], DEMO_CUSTOMER_ID,
                UNKNOWN_ITEM_ID,
            ),
        )
        assert resumed_unavailable.return_eligibility.outcome == "unavailable"
        assert resumed_unavailable.return_eligibility.reason == "order_item_unavailable"

        waiting_fresh = await with_service(
            sessions,
            lambda service: service.start(c[13], DEMO_CUSTOMER_ID, None),
        )
        async with sessions() as session:
            await session.execute(
                update(Product)
                .where(Product.id == FRESH_PRODUCT_ID)
                .values(supports_no_reason_return=False)
            )
            await session.commit()
        resumed_fresh = await with_service(
            sessions,
            lambda service: service.resume(
                waiting_fresh.workflow_id, c[13], DEMO_CUSTOMER_ID, FRESH_ITEM_ID,
            ),
        )
        assert resumed_fresh.return_eligibility.outcome == "ineligible"
        assert resumed_fresh.return_eligibility.reason == "product_not_eligible"

        await expect_unavailable(with_service(
            sessions,
            lambda service: service.resume(uuid.uuid4(), c[0], DEMO_CUSTOMER_ID, ELIGIBLE_ITEM_ID),
        ))

        bound = await with_service(
            sessions,
            lambda service: service.start(c[3], DEMO_CUSTOMER_ID, None),
        )
        await expect_unavailable(with_service(
            sessions,
            lambda service: service.resume(bound.workflow_id, c[4], DEMO_CUSTOMER_ID, ELIGIBLE_ITEM_ID),
        ))
        await expect_unavailable(with_service(
            sessions,
            lambda service: service.resume(bound.workflow_id, c[3], OTHER_CUSTOMER_ID, ELIGIBLE_ITEM_ID),
        ))

        running = await with_service(
            sessions,
            lambda service: service.start(c[4], DEMO_CUSTOMER_ID, None),
        )
        async with sessions() as session:
            assert await WorkflowRepository(session).claim_for_resume(
                running.workflow_id, c[4], DEMO_CUSTOMER_ID,
            )
        await expect_unavailable(with_service(
            sessions,
            lambda service: service.resume(
                running.workflow_id, c[4], DEMO_CUSTOMER_ID, ELIGIBLE_ITEM_ID,
            ),
        ))
        await expect_unavailable(with_service(
            sessions,
            lambda service: service.resume(
                complete.workflow_id, c[1], DEMO_CUSTOMER_ID, ELIGIBLE_ITEM_ID,
            ),
        ))

        race = await with_service(
            sessions,
            lambda service: service.start(c[5], DEMO_CUSTOMER_ID, None),
        )

        async def concurrent_resume():
            try:
                return await with_service(
                    sessions,
                    lambda service: service.resume(
                        race.workflow_id, c[5], DEMO_CUSTOMER_ID, ELIGIBLE_ITEM_ID,
                    ),
                )
            except WorkflowUnavailableException:
                return None

        resumes = await asyncio.gather(concurrent_resume(), concurrent_resume())
        assert sum(result is not None for result in resumes) == 1
        winner = next(result for result in resumes if result is not None)
        assert winner.return_eligibility.outcome == "eligible"

        isolated = await with_service(
            sessions,
            lambda service: service.start(c[6], DEMO_CUSTOMER_ID, None),
        )
        async with sessions() as session:
            rows = await session.scalar(
                select(func.count()).select_from(Workflow).where(
                    Workflow.conversation_id == c[2],
                    Workflow.status.in_((
                        WorkflowStatus.WAITING_FOR_CLARIFICATION,
                        WorkflowStatus.RUNNING,
                    )),
                )
            )
            assert rows == 1
            assert (await session.get(Workflow, isolated.workflow_id)).status == (
                WorkflowStatus.WAITING_FOR_CLARIFICATION
            )
            completed_rows = await session.scalar(
                select(func.count()).select_from(Workflow).where(
                    Workflow.conversation_id == c[0],
                    Workflow.status == WorkflowStatus.COMPLETED,
                )
            )
            assert completed_rows == 3

            await session.execute(delete(Conversation).where(Conversation.id == c[6]))
            await session.commit()
        async with sessions() as session:
            assert await session.get(Workflow, isolated.workflow_id) is None

        print(
            "PASS: business A1-A5, Resume B1-B6, current-state freshness; durable "
            "fresh-session state, bindings, partial unique index, one-winner Resume, "
            "isolation and cascade",
            flush=True,
        )
    finally:
        await engine.dispose()


async def verify_schema(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            def check(sync_connection):
                inspector = inspect(sync_connection)
                assert "workflows" in inspector.get_table_names()
                indexes = {index["name"]: index for index in inspector.get_indexes("workflows")}
                index = indexes["uq_workflows_one_active_per_conversation"]
                assert index["unique"]
                assert index["column_names"] == ["conversation_id"]
                assert not compare_metadata(
                    MigrationContext.configure(sync_connection), Base.metadata,
                )
            await connection.run_sync(check)
        print("PASS: migration schema, partial unique index and ORM metadata", flush=True)
    finally:
        await engine.dispose()


async def verify_http(url: str) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    paths = app.openapi()["paths"]
    assert "post" in paths["/chat"]
    assert "post" in paths["/chat/stream"]
    assert "post" in paths["/workflows"]
    assert "post" in paths["/workflows/{workflow_id}/resume"]

    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine)() as session:
            active_conversation_id = await session.scalar(
                select(Workflow.conversation_id).where(
                    Workflow.status == WorkflowStatus.WAITING_FOR_CLARIFICATION
                ).limit(1)
            )
    finally:
        await engine.dispose()
    assert active_conversation_id is not None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        eligible = await client.post(
            "/workflows",
            json={
                "conversation_id": str(active_conversation_id),
                "order_item_id": str(ELIGIBLE_ITEM_ID),
            },
        )
        assert eligible.status_code == 200
        assert eligible.json()["return_eligibility"] == {
            "outcome": "eligible", "reason": "eligible",
        }
        unknown_business = await client.post(
            "/workflows",
            json={
                "conversation_id": str(active_conversation_id),
                "order_item_id": str(UNKNOWN_ITEM_ID),
            },
        )
        cross_customer_business = await client.post(
            "/workflows",
            json={
                "conversation_id": str(active_conversation_id),
                "order_item_id": str(CROSS_CUSTOMER_ITEM_ID),
            },
        )
        assert unknown_business.status_code == cross_customer_business.status_code == 200
        assert unknown_business.json()["return_eligibility"] == (
            cross_customer_business.json()["return_eligibility"]
        ) == {"outcome": "unavailable", "reason": "order_item_unavailable"}

        invalid = await client.post("/workflows", json={"conversation_id": "bad"})
        assert invalid.status_code == 422
        missing = await client.post("/workflows", json={"conversation_id": str(uuid.uuid4())})
        assert missing.status_code == 404 and missing.json()["code"] == 1003
        conflict = await client.post(
            "/workflows", json={"conversation_id": str(active_conversation_id)},
        )
        assert conflict.status_code == 409 and conflict.json()["code"] == 1004
        unavailable = await client.post(
            f"/workflows/{uuid.uuid4()}/resume",
            json={"conversation_id": str(uuid.uuid4()), "order_item_id": str(ELIGIBLE_ITEM_ID)},
        )
        assert unavailable.status_code == 404
        assert unavailable.json()["message"] == "Workflow unavailable"

        engine = create_async_engine(url)
        try:
            async with async_sessionmaker(engine)() as session:
                await session.execute(delete(Workflow))
                await session.execute(delete(Shipment))
                await session.execute(delete(OrderItem))
                await session.execute(delete(Order))
                await session.execute(delete(Product))
                await session.execute(
                    delete(Customer).where(Customer.id == DEMO_CUSTOMER_ID)
                )
                await session.commit()
        finally:
            await engine.dispose()

        missing_demo = await client.post(
            "/workflows", json={"conversation_id": str(active_conversation_id)},
        )
        assert missing_demo.status_code == 500
        assert missing_demo.json()["code"] == 1002
        assert str(DEMO_CUSTOMER_ID) not in missing_demo.text
    print(
        "PASS: HTTP terminal business result, ownership-safe unavailable, routes, "
        "validation, Start 404/409, missing Demo 500, and collapsed Resume 404",
        flush=True,
    )


async def assert_empty(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
            assert not tables, "Refusing to migrate a non-empty validation database"
    finally:
        await engine.dispose()


async def assert_downgraded(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
            assert "workflows" not in tables
            assert {"conversations", "customers", "alembic_version"} <= set(tables)
    finally:
        await engine.dispose()
    print("PASS: migration downgrade removed only workflows", flush=True)


def main() -> None:
    url = sys.argv[1]
    target = make_url(url)
    if target.drivername != "postgresql+asyncpg" or not (
        target.database or ""
    ).startswith("offer_phase2_slice1_validation"):
        raise SystemExit(
            "Use an empty disposable PostgreSQL database named "
            "offer_phase2_slice1_validation..."
        )

    os.environ["DATABASE_URL"] = url
    asyncio.run(assert_empty(url))
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    asyncio.run(verify_schema(url))
    asyncio.run(verify_runtime(url))
    asyncio.run(verify_http(url))
    command.downgrade(config, "a3a8685f30b9")
    asyncio.run(assert_downgraded(url))
    command.upgrade(config, "head")
    asyncio.run(verify_schema(url))


if __name__ == "__main__":
    main()
