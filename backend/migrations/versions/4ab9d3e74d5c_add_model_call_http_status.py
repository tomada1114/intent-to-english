"""Revision 4ab9d3e74d5c: add model call http status.

Revises: a41f21f8e037
Create Date: 2026-10-23 08:29:51.238191
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "4ab9d3e74d5c"
down_revision: str | Sequence[str] | None = "a41f21f8e037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Keep existing calls with an unknown provider HTTP status."""
    with op.batch_alter_table("model_calls", schema=None) as batch_op:
        batch_op.add_column(sa.Column("status", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Remove only the status column, preserving model-call accounting."""
    with op.batch_alter_table("model_calls", schema=None) as batch_op:
        batch_op.drop_column("status")
