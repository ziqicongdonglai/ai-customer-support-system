import uuid

from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import JSONB

from sqlalchemy import (
    UUID,
    Text,
    String,
    DateTime,
    ForeignKey,
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.database.base import Base


class MessageStatus:
    PENDING = "pending"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"

class Message(Base):

    __tablename__ = "messages"


    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "conversations.id",
            # conversation 删除 自动删除所有关联message
            ondelete="CASCADE",
        ),
        nullable=False,
    )


    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )


    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )


    model: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )


    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default=MessageStatus.COMPLETED,
    )

    sources: Mapped[list[dict]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )


    conversation = relationship(
        "Conversation",
        back_populates="messages",
    )