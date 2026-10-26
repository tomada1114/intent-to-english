"""Revision f8a1fa8d2567: add submission attempt correlation.

Revises: 4ab9d3e74d5c
Create Date: 2026-10-26 11:45:01.643442
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "f8a1fa8d2567"
down_revision: str | Sequence[str] | None = "4ab9d3e74d5c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Retain legacy rows with null correlation and add durable early cancellations."""
    op.create_table(
        "submission_cancellations",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_submission_cancellations_session_id_sessions"),
        ),
        sa.PrimaryKeyConstraint(
            "session_id",
            "base_version",
            "attempt_id",
            name=op.f("pk_submission_cancellations"),
        ),
    )
    with op.batch_alter_table("submissions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("attempt_id", sa.Uuid(), nullable=True))
        batch_op.create_unique_constraint(
            batch_op.f("uq_submissions_session_id"), ["session_id", "attempt_id"]
        )


def downgrade() -> None:
    """Remove correlation metadata while preserving submissions and call records."""
    with op.batch_alter_table("submissions", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("uq_submissions_session_id"), type_="unique"
        )
        batch_op.drop_column("attempt_id")

    op.drop_table("submission_cancellations")
