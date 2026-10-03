"""Verify Mission 5 Phase 2 Slice 2 against an empty disposable PostgreSQL database.

Run from the backend root:
python -m app.scripts.verify_candidate_discovery postgresql+asyncpg://.../offer_phase2_slice2_validation
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.engine import make_url

if len(sys.argv) != 2:
    raise SystemExit(
        "Usage: python -m app.scripts.verify_candidate_discovery "
        "postgresql+asyncpg://.../offer_phase2_slice2_validation"
    )

VALIDATION_URL = sys.argv[1]
target = make_url(VALIDATION_URL)
if target.drivername != "postgresql+asyncpg" or not (
    target.database or ""
).startswith("offer_phase2_slice2_validation"):
    raise SystemExit(
        "Use an empty disposable PostgreSQL database named "
        "offer_phase2_slice2_validation..."
    )

# 在导入 app 模块前校验并固定 disposable database URL，
# 避免验证脚本误用默认开发数据库。
os.environ["DATABASE_URL"] = VALIDATION_URL

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes.workflows import router as workflow_router
from app.core.demo_principal import DEMO_CUSTOMER_ID
from app.core.dependencies import get_business_service
from app.core.exceptions import ConfigurationException
from app.core.handlers import add_exception_handlers
from app.database.base import Base
from app.models import Customer, Order, OrderItem, Product, Workflow
from app.models.business import OrderStatus, PaymentStatus
from app.repositories.business_repository import BusinessRepository
from app.scripts.seed_business_fixtures import REFERENCE_TIME, fixture_id, seed
from app.services.business_service import BusinessService


EMPTY_CUSTOMER_ID = uuid.uuid4()


def candidate_app(service: BusinessService) -> FastAPI:
    app = FastAPI()
    app.include_router(workflow_router)
    add_exception_handlers(app)
    app.dependency_overrides[get_business_service] = lambda: service
    return app


async def get_http_candidates(service: BusinessService, query: str = ""):
    async with AsyncClient(
        transport=ASGITransport(app=candidate_app(service)), base_url="http://test",
    ) as client:
        return await client.get(f"/workflows/return-eligibility/candidates{query}")


async def verify_missing_and_empty(url: str) -> None:
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            service = BusinessService(BusinessRepository(session))
            try:
                await service.list_return_eligibility_candidates(DEMO_CUSTOMER_ID)
            except ConfigurationException as error:
                assert str(error) == "Demo customer is unavailable"
            else:
                raise AssertionError("Missing Demo customer was treated as an empty customer")
            response = await get_http_candidates(service)
            assert response.status_code == 500 and response.json()["code"] == 1002

        async with sessions() as session:
            session.add_all([
                Customer(
                    id=DEMO_CUSTOMER_ID,
                    name="Demo Customer A",
                    email="a@example.invalid",
                ),
                Customer(
                    id=EMPTY_CUSTOMER_ID,
                    name="Empty Customer",
                    email="empty@example.invalid",
                ),
            ])
            await session.commit()
            empty = await BusinessService(
                BusinessRepository(session)
            ).list_return_eligibility_candidates(EMPTY_CUSTOMER_ID)
            assert empty == []
            response = await get_http_candidates(BusinessService(BusinessRepository(session)))
            assert response.status_code == 200 and response.json() == {"candidates": []}
        print("PASS: missing Demo customer preserves configuration error; existing empty customer and HTTP return []")
    finally:
        await engine.dispose()


async def verify_population_and_http(url: str) -> None:
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(seed)

        a, b = fixture_id("customer-a"), fixture_id("customer-b")
        a_ids = {
            fixture_id("item-a-pending"),
            fixture_id("item-a-transit"),
            fixture_id("item-a-delivered-mouse"),
            fixture_id("item-a-delivered-mug"),
            fixture_id("item-a-older-delivered"),
        }
        b_ids = {
            fixture_id("item-b-exception"),
            fixture_id("item-b-cancelled"),
            fixture_id("item-b-refunded"),
        }
        async with sessions() as session:
            service = BusinessService(BusinessRepository(session))
            candidates_a = await service.list_return_eligibility_candidates(a)
            candidates_b = await service.list_return_eligibility_candidates(b)
            assert {candidate.order_item_id for candidate in candidates_a} == a_ids
            assert {candidate.order_item_id for candidate in candidates_b} == b_ids
            assert not ({candidate.order_item_id for candidate in candidates_a} & b_ids)
            assert [candidate.order_item_id for candidate in candidates_a] == [
                fixture_id("item-a-pending"),
                fixture_id("item-a-transit"),
                *sorted([
                    fixture_id("item-a-delivered-mouse"),
                    fixture_id("item-a-delivered-mug"),
                ]),
                fixture_id("item-a-older-delivered"),
            ]
            assert sum(candidate.product_name == "Demo Mouse" for candidate in candidates_a) == 4
            assert {candidate.product_name for candidate in candidates_a if candidate.order_created_at == REFERENCE_TIME - timedelta(days=6)} == {
                "Demo Mouse", "Demo Engraved Mug",
            }
            transit = next(
                candidate for candidate in candidates_a
                if candidate.order_item_id == fixture_id("item-a-transit")
            )
            assert transit.quantity == 2

            outcomes = {
                label: await service.evaluate_return_eligibility(a, fixture_id(label), REFERENCE_TIME)
                for label in (
                    "item-a-delivered-mug",
                    "item-a-older-delivered",
                    "item-a-pending",
                )
            }
            assert outcomes["item-a-delivered-mug"].reason == "product_not_eligible"
            assert outcomes["item-a-older-delivered"].reason == "outside_return_window"
            assert outcomes["item-a-pending"].reason == "not_delivered"

            response = await get_http_candidates(service)
            assert response.status_code == 200
            payload = response.json()
            assert set(payload) == {"candidates"} and len(payload["candidates"]) == 5
            first = payload["candidates"][0]
            assert set(first) == {
                "order_item_id", "product_name", "quantity", "unit_price", "order_created_at",
            }
            assert uuid.UUID(first["order_item_id"]) == fixture_id("item-a-pending")
            assert first["unit_price"] == "39.90"
            assert datetime.fromisoformat(first["order_created_at"].replace("Z", "+00:00")).utcoffset() is not None
            ignored_identity = await get_http_candidates(service, f"?customer_id={b}")
            assert ignored_identity.json() == payload
        print("PASS: ownership/isolation, repeated products, multi-item order, quantity, no eligibility filtering, ordering")
        print("PASS: HTTP envelope, trusted Demo customer, UUID/Decimal/timezone serialization")
    finally:
        await engine.dispose()


async def verify_freshness_and_limit(url: str) -> None:
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    boundary_item_ids = []
    try:
        async with sessions() as session:
            product = await session.get(Product, fixture_id("mouse"))
            product.name = "Current Demo Mouse"
            for index in range(21):
                order = Order(
                    id=uuid.uuid4(),
                    customer_id=DEMO_CUSTOMER_ID,
                    status=OrderStatus.ACTIVE,
                    payment_status=PaymentStatus.PAID,
                    created_at=REFERENCE_TIME + timedelta(days=30 - index),
                )
                candidate_id = uuid.uuid4()
                boundary_item_ids.append(candidate_id)
                session.add_all([
                    order,
                    OrderItem(
                        id=candidate_id,
                        order=order,
                        product_id=fixture_id("mouse"),
                        quantity=3 if index == 0 else 1,
                        unit_price=Decimal("41.50" if index == 0 else "39.90"),
                    ),
                ])
            for index in range(25):
                order = Order(
                    id=uuid.uuid4(),
                    customer_id=fixture_id("customer-b"),
                    status=OrderStatus.ACTIVE,
                    payment_status=PaymentStatus.PAID,
                    created_at=REFERENCE_TIME + timedelta(days=100 + index),
                )
                session.add_all([
                    order,
                    OrderItem(
                        id=uuid.uuid4(),
                        order=order,
                        product_id=fixture_id("mouse"),
                        quantity=1,
                        unit_price=Decimal("39.90"),
                    ),
                ])
            await session.commit()

        async with sessions() as session:
            service = BusinessService(BusinessRepository(session))
            candidates = await service.list_return_eligibility_candidates(DEMO_CUSTOMER_ID)
            assert len(candidates) == 20
            assert [candidate.order_item_id for candidate in candidates] == boundary_item_ids[:20]
            assert boundary_item_ids[20] not in {candidate.order_item_id for candidate in candidates}
            assert all(candidate.product_name == "Current Demo Mouse" for candidate in candidates)
            assert candidates[0].quantity == 3
            assert candidates[0].unit_price == Decimal("41.50")
            response = await get_http_candidates(service, "?limit=1")
            assert response.status_code == 200 and len(response.json()["candidates"]) == 20

        async with sessions() as session:
            service = BusinessService(BusinessRepository(session))
            fresh = await service.list_return_eligibility_candidates(DEMO_CUSTOMER_ID)
            assert fresh == await service.list_return_eligibility_candidates(DEMO_CUSTOMER_ID)
            assert await session.scalar(select(Workflow.id).limit(1)) is None
        print("PASS: current-state projection, deterministic repeated reads, customer-scoped newest 20, 21st omitted")
    finally:
        await engine.dispose()


async def verify_schema_and_empty_database(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
            assert not tables, "Refusing to migrate a non-empty validation database"
    finally:
        await engine.dispose()


async def verify_metadata(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            def check(sync_connection):
                assert not compare_metadata(
                    MigrationContext.configure(sync_connection), Base.metadata,
                ), "Migration metadata drift"

            await connection.run_sync(check)
        print("PASS: no migration metadata drift")
    finally:
        await engine.dispose()


def main() -> None:
    url = VALIDATION_URL
    asyncio.run(verify_schema_and_empty_database(url))
    command.upgrade(Config("alembic.ini"), "head")
    asyncio.run(verify_metadata(url))
    asyncio.run(verify_missing_and_empty(url))
    asyncio.run(verify_population_and_http(url))
    asyncio.run(verify_freshness_and_limit(url))


if __name__ == "__main__":
    main()
