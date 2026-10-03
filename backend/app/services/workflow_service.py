import logging
import time
from datetime import datetime, timezone
from uuid import UUID

from app.core.exceptions import (
    ActiveWorkflowConflictException,
    ConfigurationException,
    ConversationNotFoundException,
    WorkflowPersistenceConflictException,
    WorkflowUnavailableException,
)
from app.models.workflow import WorkflowStatus
from app.repositories.workflow_repository import WorkflowRepository
from app.schemas.workflow import ReturnEligibilityResponse, WorkflowResponse
from app.services.business_service import BusinessService, ReturnEligibilityResult


CLARIFICATION = "Please provide order_item_id."
logger = logging.getLogger(__name__)


class WorkflowService:
    def __init__(
        self, workflow_repo: WorkflowRepository, business_service: BusinessService,
    ):
        self.workflow_repo = workflow_repo
        self.business_service = business_service

    async def start(
        self,
        conversation_id: UUID,
        trusted_customer_id: UUID,
        order_item_id: UUID | None,
    ) -> WorkflowResponse:
        execution_started = time.perf_counter()
        failure_stage = "precondition"
        input_complete = order_item_id is not None
        logger.info(
            "event=workflow.execution.started operation=start input_complete=%s",
            str(input_complete).lower(),
        )
        try:
            # conversation_id 用于绑定当前 Chat 与 Workflow，但它本身不是 ownership proof；
            # customer identity 由 application trusted context 注入，不接受 LLM 或前端自报。
            if not await self.workflow_repo.conversation_exists(conversation_id):
                raise ConversationNotFoundException("Conversation not found")
            if not await self.workflow_repo.customer_exists(trusted_customer_id):
                raise ConfigurationException("Demo customer is unavailable")

            result = None
            if order_item_id is None:
                # WAITING 只表示缺少继续执行所需的 purchase identifier；
                # 此时尚未运行 eligibility deterministic rule，也没有业务结论。
                status = WorkflowStatus.WAITING_FOR_CLARIFICATION
            else:
                # 完整输入无需经历 Resume claim；先评估再落 COMPLETED，
                # 避免意外评估失败时留下错误的终态记录。
                failure_stage = "business"
                business_started = time.perf_counter()
                logger.info("event=workflow.business.started operation=start")
                try:
                    result = await self.business_service.evaluate_return_eligibility(
                        trusted_customer_id, order_item_id, datetime.now(timezone.utc),
                    )
                except Exception:
                    logger.info(
                        "event=workflow.business.completed operation=start "
                        "outcome=failed duration_ms=%.3f",
                        (time.perf_counter() - business_started) * 1000,
                    )
                    raise
                logger.info(
                    "event=workflow.business.completed operation=start outcome=%s "
                    "duration_ms=%.3f",
                    result.outcome,
                    (time.perf_counter() - business_started) * 1000,
                )
                status = WorkflowStatus.COMPLETED

            failure_stage = "creation"
            creation_started = time.perf_counter()
            # Start 在 create 成功前还没有 durable Workflow；只有 persistence 成功返回后，
            # workflow_id 才能作为生命周期 correlation 写入日志。
            workflow = await self.workflow_repo.create(
                status, conversation_id, trusted_customer_id,
            )
            logger.info(
                "event=workflow.created workflow_id=%s status=%s duration_ms=%.3f",
                workflow.id,
                workflow.status,
                (time.perf_counter() - creation_started) * 1000,
            )
            response = WorkflowResponse(
                workflow_id=workflow.id,
                status=workflow.status,
                clarification=CLARIFICATION if order_item_id is None else None,
                return_eligibility=self._response_result(result),
            )
            logger.info(
                "event=workflow.execution.completed operation=start outcome=completed "
                "workflow_id=%s duration_ms=%.3f",
                workflow.id,
                (time.perf_counter() - execution_started) * 1000,
            )
            return response
        except ActiveWorkflowConflictException:
            logger.info(
                "event=workflow.execution.completed operation=start "
                "outcome=active_conflict failure_stage=%s duration_ms=%.3f",
                failure_stage,
                (time.perf_counter() - execution_started) * 1000,
            )
            raise
        except ConversationNotFoundException:
            logger.info(
                "event=workflow.execution.completed operation=start outcome=not_found "
                "failure_stage=%s duration_ms=%.3f",
                failure_stage,
                (time.perf_counter() - execution_started) * 1000,
            )
            raise
        except ConfigurationException:
            logger.warning(
                "event=workflow.execution.completed operation=start "
                "outcome=configuration_error failure_stage=%s duration_ms=%.3f",
                failure_stage,
                (time.perf_counter() - execution_started) * 1000,
            )
            raise
        except Exception:
            logger.warning(
                "event=workflow.execution.completed operation=start "
                "outcome=unexpected_error failure_stage=%s duration_ms=%.3f",
                failure_stage,
                (time.perf_counter() - execution_started) * 1000,
            )
            raise

    async def resume(
        self,
        workflow_id: UUID,
        conversation_id: UUID,
        trusted_customer_id: UUID,
        order_item_id: UUID,
    ) -> WorkflowResponse:
        execution_started = time.perf_counter()
        failure_stage = "claim"
        logger.info(
            "event=workflow.execution.started operation=resume workflow_id=%s",
            workflow_id,
        )
        try:
            # claim 同时绑定 Workflow、Conversation 与 trusted customer，避免把一次 Resume
            # 错配到其他 Conversation 或 customer 的 Workflow。
            claim_started = time.perf_counter()
            try:
                claimed = await self.workflow_repo.claim_for_resume(
                    workflow_id, conversation_id, trusted_customer_id,
                )
            except Exception:
                logger.info(
                    "event=workflow.claim.completed workflow_id=%s outcome=failed "
                    "duration_ms=%.3f",
                    workflow_id,
                    (time.perf_counter() - claim_started) * 1000,
                )
                raise
            if not claimed:
                logger.info(
                    "event=workflow.claim.completed workflow_id=%s outcome=unavailable "
                    "duration_ms=%.3f",
                    workflow_id,
                    (time.perf_counter() - claim_started) * 1000,
                )
                raise WorkflowUnavailableException("Workflow unavailable")
            # repository 返回 True 表示 guarded WAITING → RUNNING 已持久化；
            # 此时当前 Resume request 才取得 durable execution ownership。
            logger.info(
                "event=workflow.claim.completed workflow_id=%s outcome=claimed "
                "duration_ms=%.3f",
                workflow_id,
                (time.perf_counter() - claim_started) * 1000,
            )

            # claim 成功后 RUNNING 已成为 durable state；后续 business / completion
            # 失败可能使 Workflow 保持 RUNNING。本 Slice 只提供诊断 evidence，
            # 不执行 retry / rollback to WAITING / timeout / recovery。
            failure_stage = "business"
            business_started = time.perf_counter()
            logger.info(
                "event=workflow.business.started operation=resume workflow_id=%s",
                workflow_id,
            )
            try:
                result = await self.business_service.evaluate_return_eligibility(
                    trusted_customer_id, order_item_id, datetime.now(timezone.utc),
                )
            except Exception:
                logger.info(
                    "event=workflow.business.completed operation=resume workflow_id=%s "
                    "outcome=failed duration_ms=%.3f",
                    workflow_id,
                    (time.perf_counter() - business_started) * 1000,
                )
                raise
            logger.info(
                "event=workflow.business.completed operation=resume workflow_id=%s "
                "outcome=%s duration_ms=%.3f",
                workflow_id,
                result.outcome,
                (time.perf_counter() - business_started) * 1000,
            )

            failure_stage = "completion"
            completion_started = time.perf_counter()
            logger.info(
                "event=workflow.completion.started workflow_id=%s", workflow_id,
            )
            try:
                completed = await self.workflow_repo.complete(
                    workflow_id, conversation_id, trusted_customer_id,
                )
            except Exception:
                logger.info(
                    "event=workflow.completion.completed workflow_id=%s outcome=failed "
                    "duration_ms=%.3f",
                    workflow_id,
                    (time.perf_counter() - completion_started) * 1000,
                )
                raise
            if not completed:
                logger.info(
                    "event=workflow.completion.completed workflow_id=%s outcome=conflict "
                    "duration_ms=%.3f",
                    workflow_id,
                    (time.perf_counter() - completion_started) * 1000,
                )
                raise WorkflowPersistenceConflictException(
                    "Claimed workflow could not be completed"
                )
            logger.info(
                "event=workflow.completion.completed workflow_id=%s outcome=completed "
                "duration_ms=%.3f",
                workflow_id,
                (time.perf_counter() - completion_started) * 1000,
            )
            response = WorkflowResponse(
                workflow_id=workflow_id,
                status=WorkflowStatus.COMPLETED,
                clarification=None,
                return_eligibility=self._response_result(result),
            )
            logger.info(
                "event=workflow.execution.completed operation=resume outcome=completed "
                "workflow_id=%s duration_ms=%.3f",
                workflow_id,
                (time.perf_counter() - execution_started) * 1000,
            )
            return response
        except WorkflowUnavailableException:
            logger.info(
                "event=workflow.execution.completed operation=resume outcome=unavailable "
                "failure_stage=%s workflow_id=%s duration_ms=%.3f",
                failure_stage,
                workflow_id,
                (time.perf_counter() - execution_started) * 1000,
            )
            raise
        except WorkflowPersistenceConflictException:
            logger.warning(
                "event=workflow.execution.completed operation=resume outcome=handled_error "
                "failure_stage=%s workflow_id=%s duration_ms=%.3f",
                failure_stage,
                workflow_id,
                (time.perf_counter() - execution_started) * 1000,
            )
            raise
        except ConfigurationException:
            logger.warning(
                "event=workflow.execution.completed operation=resume "
                "outcome=configuration_error failure_stage=%s workflow_id=%s "
                "duration_ms=%.3f",
                failure_stage,
                workflow_id,
                (time.perf_counter() - execution_started) * 1000,
            )
            raise
        except Exception:
            logger.warning(
                "event=workflow.execution.completed operation=resume "
                "outcome=unexpected_error failure_stage=%s workflow_id=%s "
                "duration_ms=%.3f",
                failure_stage,
                workflow_id,
                (time.perf_counter() - execution_started) * 1000,
            )
            raise

    # 仅把应用层业务结果映射为 HTTP schema；字段虽相同，二者属于不同层。
    # 映射不依赖 WorkflowService 实例状态，因此保持为 staticmethod。
    @staticmethod
    def _response_result(
        result: ReturnEligibilityResult | None,
    ) -> ReturnEligibilityResponse | None:
        return ReturnEligibilityResponse(**result._asdict()) if result else None
