"""add workflows

Revision ID: 0f6c4e2a319b
Revises: a3a8685f30b9
Create Date: 2026-09-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0f6c4e2a319b"
down_revision: Union[str, Sequence[str], None] = "a3a8685f30b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_workflows_one_active_per_conversation",
        "workflows",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('waiting_for_clarification', 'running')"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_workflows_one_active_per_conversation", table_name="workflows",
    )
    op.drop_table("workflows")
