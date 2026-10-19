"""Revision a41f21f8e037: drop todos.

Revises: de3f10d569ec
Create Date: 2026-10-19 09:37:07.000000

The template's sample table leaves the schema; sessions replace it. The
downgrade recreates it exactly as f58f944d0d8e created it, empty.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "a41f21f8e037"
down_revision: str | Sequence[str] | None = "de3f10d569ec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    op.drop_table("todos")


def downgrade() -> None:
    """Downgrade the schema to the revision before this one."""
    op.create_table(
        "todos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("is_completed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_todos")),
    )
