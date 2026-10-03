from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.demo_principal import DEMO_CUSTOMER_ID
from app.core.dependencies import get_business_service, get_workflow_service
from app.schemas.workflow import (
    ReturnEligibilityCandidateListResponse,
    ReturnEligibilityCandidateResponse,
    WorkflowResumeRequest,
    WorkflowResponse,
    WorkflowStartRequest,
)
from app.services.business_service import BusinessService
from app.services.workflow_service import WorkflowService


router = APIRouter(prefix="/workflows", tags=["Workflow"])


@router.get(
    "/return-eligibility/candidates",
    response_model=ReturnEligibilityCandidateListResponse,
)
async def list_return_eligibility_candidates(
    service: BusinessService = Depends(get_business_service),
) -> ReturnEligibilityCandidateListResponse:
    # Demo principal 由 application boundary 注入；不得由请求体、LLM 或 candidate ID 指定。
    candidates = await service.list_return_eligibility_candidates(DEMO_CUSTOMER_ID)
    return ReturnEligibilityCandidateListResponse(candidates=[
        ReturnEligibilityCandidateResponse(**candidate._asdict())
        for candidate in candidates
    ])


@router.post("", response_model=WorkflowResponse)
async def start_workflow(
    request: WorkflowStartRequest,
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowResponse:
    # POST /workflows 是 durable Workflow 的显式创建点；仅打开前端面板不会到达这里。
    return await service.start(
        request.conversation_id, DEMO_CUSTOMER_ID, request.order_item_id,
    )


@router.post("/{workflow_id}/resume", response_model=WorkflowResponse)
async def resume_workflow(
    workflow_id: UUID,
    request: WorkflowResumeRequest,
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowResponse:
    return await service.resume(
        workflow_id,
        request.conversation_id,
        DEMO_CUSTOMER_ID,
        request.order_item_id,
    )
