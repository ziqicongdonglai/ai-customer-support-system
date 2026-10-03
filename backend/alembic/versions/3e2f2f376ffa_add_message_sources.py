"""add message sources

Revision ID: 3e2f2f376ffa
Revises: c8119a930c88
Create Date: 2026-08-26 15:03:38.313430

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3e2f2f376ffa'
down_revision: Union[str, Sequence[str], None] = 'c8119a930c88'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "messages",
        sa.Column(
            "sources",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    # server_default 只用于迁移旧数据。
    # 迁移完成后移除，之后由 ORM default=list 负责新 Message 的默认值。
    op.alter_column(
        "messages",
        "sources",
        server_default=None,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column(
        "messages",
        "sources",
    )
    # ### end Alembic commands ###
