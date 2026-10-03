from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ActiveWorkflowConflictException
from app.models.business import Customer
from app.models.conversation import Conversation
from app.models.workflow import Workflow, WorkflowStatus


ACTIVE_WORKFLOW_INDEX = "uq_workflows_one_active_per_conversation"


class WorkflowRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def conversation_exists(self, conversation_id: UUID) -> bool:
        return await self.db.get(Conversation, conversation_id) is not None

    async def customer_exists(self, customer_id: UUID) -> bool:
        return await self.db.get(Customer, customer_id) is not None

    async def create(
        self, status: str, conversation_id: UUID, customer_id: UUID,
    ) -> Workflow:
        workflow = Workflow(
            status=status,
            conversation_id=conversation_id,
            customer_id=customer_id,
        )
        self.db.add(workflow)
        try:
            await self.db.commit()
        except IntegrityError as error:
            await self.db.rollback()
            cause = getattr(error.orig, "__cause__", None)
            constraint_name = getattr(error.orig, "constraint_name", None) or getattr(
                cause, "constraint_name", None,
            )
            if constraint_name == ACTIVE_WORKFLOW_INDEX:
                raise ActiveWorkflowConflictException(
                    "Conversation already has an active workflow"
                ) from error
            raise
        await self.db.refresh(workflow)
        return workflow

    async def claim_for_resume(
        self, workflow_id: UUID, conversation_id: UUID, customer_id: UUID,
    ) -> bool:
        # 条件 UPDATE 是 WAITING → RUNNING 的原子执行权 claim；先读后写会让两个
        # 并发 Resume 都观察到 WAITING，并重复执行同一 continuation。
        # 单条条件 UPDATE 同时校验 Workflow、Conversation、trusted customer 和
        # WAITING 状态并抢占 Resume，避免两个并发请求先读后同时继续执行。
        result = await self.db.execute(
            update(Workflow)
            .where(
                Workflow.id == workflow_id,
                Workflow.conversation_id == conversation_id,
                Workflow.customer_id == customer_id,
                Workflow.status == WorkflowStatus.WAITING_FOR_CLARIFICATION,
            )
            .values(status=WorkflowStatus.RUNNING, updated_at=datetime.now(timezone.utc))
        )
        await self.db.commit()
        # 1 表示当前请求唯一取得执行权；0 统一视为 unavailable，避免泄露
        # Workflow 是否存在、binding 是否匹配或当前状态。
        return result.rowcount == 1

    async def complete(
        self, workflow_id: UUID, conversation_id: UUID, customer_id: UUID,
    ) -> bool:
        # COMPLETED 是 Workflow lifecycle 终态，不编码 eligible / ineligible / unavailable；
        # authoritative business outcome 由 BusinessService 的 deterministic rule 产生。
        # 只有已由当前绑定成功 claim 为 RUNNING 的 Workflow 才能进入终态，
        # 防止绕过 Resume claim 直接写成 COMPLETED。
        result = await self.db.execute(
            update(Workflow)
            .where(
                Workflow.id == workflow_id,
                Workflow.conversation_id == conversation_id,
                Workflow.customer_id == customer_id,
                Workflow.status == WorkflowStatus.RUNNING,
            )
            .values(status=WorkflowStatus.COMPLETED, updated_at=datetime.now(timezone.utc))
        )
        await self.db.commit()
        return result.rowcount == 1

    async def get_by_id(self, workflow_id: UUID) -> Workflow | None:
        return await self.db.scalar(select(Workflow).where(Workflow.id == workflow_id))
