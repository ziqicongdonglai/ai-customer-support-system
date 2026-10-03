import asyncio

import pytest
from fastapi import HTTPException

from app.api.routes import health


class FakeDatabase:
    def __init__(self, revision=None, error=None):
        self.revision = revision
        self.error = error
        self.queries = []

    async def scalar(self, query):
        self.queries.append(str(query))
        if self.error:
            raise self.error
        return self.revision


def test_readiness_only_requires_matching_revision(monkeypatch):
    database = FakeDatabase("head")
    monkeypatch.setattr(health, "get_repository_migration_head", lambda: "head")

    assert asyncio.run(health.health_ready(database)) == {"status": "ready"}
    assert database.queries == ["SELECT version_num FROM alembic_version"]


def test_readiness_rejects_stale_revision(monkeypatch):
    monkeypatch.setattr(health, "get_repository_migration_head", lambda: "head")

    with pytest.raises(HTTPException) as error:
        asyncio.run(health.health_ready(FakeDatabase("previous")))

    assert error.value.status_code == 503
    assert error.value.detail == "Service not ready"


def test_readiness_rejects_missing_revision(monkeypatch):
    monkeypatch.setattr(health, "get_repository_migration_head", lambda: "head")

    with pytest.raises(HTTPException) as error:
        asyncio.run(health.health_ready(FakeDatabase()))

    assert error.value.status_code == 503


def test_readiness_rejects_database_failure(monkeypatch):
    monkeypatch.setattr(health, "get_repository_migration_head", lambda: "head")

    with pytest.raises(HTTPException) as error:
        asyncio.run(health.health_ready(FakeDatabase(error=RuntimeError("unavailable"))))

    assert error.value.status_code == 503


def test_readiness_rejects_non_unique_repository_head(monkeypatch):
    def fail():
        raise RuntimeError("multiple heads")

    monkeypatch.setattr(health, "get_repository_migration_head", fail)

    with pytest.raises(HTTPException) as error:
        asyncio.run(health.health_ready(FakeDatabase("head")))

    assert error.value.status_code == 503
