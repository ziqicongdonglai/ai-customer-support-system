from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class WorkflowStartRequest(BaseModel):
    conversation_id: UUID
    order_item_id: UUID | None = None


class WorkflowResumeRequest(BaseModel):
    conversation_id: UUID
    order_item_id: UUID


# ReturnEligibilityResult 的 HTTP/API 表示，不作为 BusinessService 应用层结果。
class ReturnEligibilityResponse(BaseModel):
    outcome: Literal["eligible", "ineligible", "unavailable"]
    reason: str


class ReturnEligibilityCandidateResponse(BaseModel):
    order_item_id: UUID
    product_name: str
    quantity: int
    unit_price: Decimal
    order_created_at: datetime


class ReturnEligibilityCandidateListResponse(BaseModel):
    candidates: list[ReturnEligibilityCandidateResponse]


class WorkflowResponse(BaseModel):
    workflow_id: UUID
    status: str
    clarification: str | None
    return_eligibility: ReturnEligibilityResponse | None
