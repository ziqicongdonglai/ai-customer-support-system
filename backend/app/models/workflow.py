import uuid
from datetime import datetime, timezone

from sqlalchemy import UUID, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class WorkflowStatus:
    WAITING_FOR_CLARIFICATION = "waiting_for_clarification"
    RUNNING = "running"
    COMPLETED = "completed"


class Workflow(Base):
    __tablename__ = "workflows"
    __table_args__ = (
        # 数据库约束是并发 Start 的最终一致性边界：同一 Conversation 只能有一个
        # WAITING/RUNNING Workflow；COMPLETED 不受限，可保留多条历史记录。
        Index(
            "uq_workflows_one_active_per_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text(
                "status IN ('waiting_for_clarification', 'running')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    status: Mapped[str] = mapped_column(String(32))
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
