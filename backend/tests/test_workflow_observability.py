import asyncio
import logging
import re
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.core.context import request_id_context
from app.core.exceptions import (
    ActiveWorkflowConflictException,
    WorkflowPersistenceConflictException,
    WorkflowUnavailableException,
)
from app.core.logging import RequestIDFilter
from app.models.workflow import WorkflowStatus
from app.services.business_service import ReturnEligibilityResult
from app.services.workflow_service import WorkflowService


REQUEST_ID = "workflow-observability-request"
WORKFLOW_ID = UUID("11111111-1111-4111-8111-111111111111")
CONVERSATION_ID = UUID("22222222-2222-4222-8222-222222222222")
CUSTOMER_ID = UUID("33333333-3333-4333-8333-333333333333")
ORDER_ITEM_ID = UUID("44444444-4444-4444-8444-444444444444")
BUSINESS_REASON = "sensitive business reason sentinel"
EXCEPTION_TEXT = "sensitive persistence exception sentinel"


class FakeWorkflowRepository:
    def __init__(self, *, claim=True, complete=True, create_error=None, claim_error=None,
                 complete_error=None):
        self.claim = claim
        self.complete_result = complete
        self.create_error = create_error
        self.claim_error = claim_error
        self.complete_error = complete_error
        self.claim_calls = 0
        self.complete_calls = 0

    async def conversation_exists(self, conversation_id):
        return True

    async def customer_exists(self, customer_id):
        return True

    async def create(self, status, conversation_id, customer_id):
        if self.create_error:
            raise self.create_error
        return SimpleNamespace(id=WORKFLOW_ID, status=status)

    async def claim_for_resume(self, workflow_id, conversation_id, customer_id):
        self.claim_calls += 1
        if self.claim_error:
            raise self.claim_error
        return self.claim

    async def complete(self, workflow_id, conversation_id, customer_id):
        self.complete_calls += 1
        if self.complete_error:
            raise self.complete_error
        return self.complete_result


class FakeBusinessService:
    def __init__(self, outcome="eligible", error=None):
        self.result = ReturnEligibilityResult(outcome, BUSINESS_REASON)
        self.error = error
        self.calls = 0

    async def evaluate_return_eligibility(self, customer_id, order_item_id, now):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


@pytest.fixture(autouse=True)
def correlated_logs(caplog):
    caplog.set_level(logging.INFO)
    request_filter = RequestIDFilter()
    caplog.handler.addFilter(request_filter)
    token = request_id_context.set(REQUEST_ID)
    yield
    request_id_context.reset(token)
    caplog.handler.removeFilter(request_filter)


def messages(caplog):
    return [record.getMessage() for record in caplog.records if "event=workflow." in record.getMessage()]


def assert_correlated_and_timed(caplog):
    records = [record for record in caplog.records if "event=workflow." in record.getMessage()]
    assert records and {record.request_id for record in records} == {REQUEST_ID}
    assert re.search(r"duration_ms=\d+\.\d{3}", "\n".join(record.getMessage() for record in records))


def test_start_waiting_logs_durable_creation_without_business(caplog):
    repo = FakeWorkflowRepository()
    business = FakeBusinessService()
    response = asyncio.run(
        WorkflowService(repo, business).start(CONVERSATION_ID, CUSTOMER_ID, None)
    )
    logs = messages(caplog)

    assert response.status == WorkflowStatus.WAITING_FOR_CLARIFICATION
    assert "event=workflow.execution.started operation=start input_complete=false" in logs[0]
    assert "workflow_id=" not in logs[0]
    assert not any("workflow.business." in message for message in logs)
    assert any(
        f"event=workflow.created workflow_id={WORKFLOW_ID} "
        "status=waiting_for_clarification" in message
        for message in logs
    )
    assert f"workflow_id={WORKFLOW_ID}" in logs[-1]
    assert business.calls == 0
    assert_correlated_and_timed(caplog)


@pytest.mark.parametrize("outcome", ["eligible", "ineligible", "unavailable"])
def test_direct_start_logs_safe_business_outcome_before_durable_id(caplog, outcome):
    response = asyncio.run(
        WorkflowService(
            FakeWorkflowRepository(), FakeBusinessService(outcome),
        ).start(CONVERSATION_ID, CUSTOMER_ID, ORDER_ITEM_ID)
    )
    logs = messages(caplog)
    created_index = next(i for i, message in enumerate(logs) if "event=workflow.created" in message)

    assert response.status == WorkflowStatus.COMPLETED
    assert "input_complete=true" in logs[0]
    assert "event=workflow.business.started operation=start" in logs[1]
    assert f"outcome={outcome}" in logs[2]
    assert all("workflow_id=" not in message for message in logs[:created_index])
    assert "status=completed" in logs[created_index]
    assert_correlated_and_timed(caplog)


def test_resume_success_logs_ordered_lifecycle_with_one_workflow_id(caplog):
    response = asyncio.run(
        WorkflowService(FakeWorkflowRepository(), FakeBusinessService()).resume(
            WORKFLOW_ID, CONVERSATION_ID, CUSTOMER_ID, ORDER_ITEM_ID,
        )
    )
    logs = messages(caplog)

    assert response.status == WorkflowStatus.COMPLETED
    assert [message.split()[0] for message in logs] == [
        "event=workflow.execution.started",
        "event=workflow.claim.completed",
        "event=workflow.business.started",
        "event=workflow.business.completed",
        "event=workflow.completion.started",
        "event=workflow.completion.completed",
        "event=workflow.execution.completed",
    ]
    assert all(f"workflow_id={WORKFLOW_ID}" in message for message in logs)
    assert "outcome=claimed" in logs[1]
    assert "outcome=completed" in logs[-2]
    assert_correlated_and_timed(caplog)


def test_claim_unavailable_stops_before_business_and_completion(caplog):
    repo = FakeWorkflowRepository(claim=False)
    business = FakeBusinessService()

    with pytest.raises(WorkflowUnavailableException):
        asyncio.run(
            WorkflowService(repo, business).resume(
                WORKFLOW_ID, CONVERSATION_ID, CUSTOMER_ID, ORDER_ITEM_ID,
            )
        )
    logs = messages(caplog)

    assert any("event=workflow.claim.completed" in message and "outcome=unavailable" in message for message in logs)
    assert "outcome=unavailable failure_stage=claim" in logs[-1]
    assert not any("workflow.business." in message or "workflow.completion." in message for message in logs)
    assert business.calls == repo.complete_calls == 0


def test_failure_after_claim_is_localized_without_recovery(caplog):
    failure = RuntimeError(BUSINESS_REASON)
    repo = FakeWorkflowRepository()

    with pytest.raises(RuntimeError) as caught:
        asyncio.run(
            WorkflowService(repo, FakeBusinessService(error=failure)).resume(
                WORKFLOW_ID, CONVERSATION_ID, CUSTOMER_ID, ORDER_ITEM_ID,
            )
        )
    logs = messages(caplog)

    assert caught.value is failure
    assert any("outcome=claimed" in message for message in logs)
    assert any("event=workflow.business.started" in message for message in logs)
    assert any("event=workflow.business.completed" in message and "outcome=failed" in message for message in logs)
    assert not any("event=workflow.completion.started" in message for message in logs)
    assert "outcome=unexpected_error failure_stage=business" in logs[-1]
    assert repo.complete_calls == 0


def test_completion_conflict_preserves_existing_exception(caplog):
    repo = FakeWorkflowRepository(complete=False)

    with pytest.raises(WorkflowPersistenceConflictException):
        asyncio.run(
            WorkflowService(repo, FakeBusinessService()).resume(
                WORKFLOW_ID, CONVERSATION_ID, CUSTOMER_ID, ORDER_ITEM_ID,
            )
        )
    logs = messages(caplog)

    assert any("event=workflow.completion.started" in message for message in logs)
    assert any("event=workflow.completion.completed" in message and "outcome=conflict" in message for message in logs)
    assert "outcome=handled_error failure_stage=completion" in logs[-1]


def test_claim_persistence_failure_is_safe_and_reraised_unchanged(caplog):
    failure = RuntimeError(EXCEPTION_TEXT)

    with pytest.raises(RuntimeError) as caught:
        asyncio.run(
            WorkflowService(
                FakeWorkflowRepository(claim_error=failure), FakeBusinessService(),
            ).resume(WORKFLOW_ID, CONVERSATION_ID, CUSTOMER_ID, ORDER_ITEM_ID)
        )
    logs = "\n".join(messages(caplog))

    assert caught.value is failure
    assert "event=workflow.claim.completed" in logs and "outcome=failed" in logs
    assert "outcome=unexpected_error failure_stage=claim" in logs
    assert EXCEPTION_TEXT not in logs


def test_semantic_logs_exclude_sensitive_identifiers_and_payloads(caplog):
    asyncio.run(
        WorkflowService(FakeWorkflowRepository(), FakeBusinessService()).resume(
            WORKFLOW_ID, CONVERSATION_ID, CUSTOMER_ID, ORDER_ITEM_ID,
        )
    )
    logs = "\n".join(messages(caplog))

    assert REQUEST_ID not in logs  # request_id belongs to the formatter/record, not message payload.
    assert f"workflow_id={WORKFLOW_ID}" in logs
    for sensitive in (CONVERSATION_ID, CUSTOMER_ID, ORDER_ITEM_ID):
        assert str(sensitive) not in logs
    assert BUSINESS_REASON not in logs


def test_active_workflow_conflict_is_expected_creation_outcome(caplog):
    conflict = ActiveWorkflowConflictException("sensitive conflict detail")

    with pytest.raises(ActiveWorkflowConflictException) as caught:
        asyncio.run(
            WorkflowService(
                FakeWorkflowRepository(create_error=conflict), FakeBusinessService(),
            ).start(CONVERSATION_ID, CUSTOMER_ID, None)
        )
    logs = "\n".join(messages(caplog))

    assert caught.value is conflict
    assert "outcome=active_conflict failure_stage=creation" in logs
    assert "workflow_id=" not in logs
    assert str(conflict) not in logs
