"""add 'paused' task status + interruptions table

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-19

Interrupt-with-reason flow: when the user hits Pause on the widget, we want to
preserve momentum (timer resumes from where it left off, not zero) AND capture
the reason so weekly reports can surface "you were interrupted N times this
week for these reasons." This commit adds both pieces:

  - 'paused' status on tasks (CHECK constraint update)
  - interruptions table: one row per pause/resume cycle, with reason text
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_STATUSES = ("pending", "scheduled", "in_progress", "paused", "done", "decayed")
OLD_STATUSES = ("pending", "scheduled", "in_progress", "done", "decayed")


def upgrade() -> None:
    # Replace the CHECK constraint with the new status set (adds 'paused').
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("ck_tasks_status", type_="check")
        batch.create_check_constraint(
            "ck_tasks_status",
            "status IN " + repr(NEW_STATUSES),
        )

    op.create_table(
        "interruptions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("task_id", sa.Integer, sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resumed_at", sa.DateTime(timezone=True)),
        sa.Column("reason", sa.String(500), nullable=False, server_default=""),
    )
    op.create_index("ix_interruptions_user", "interruptions", ["user_id", "paused_at"])
    op.create_index("ix_interruptions_task", "interruptions", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_interruptions_task", table_name="interruptions")
    op.drop_index("ix_interruptions_user", table_name="interruptions")
    op.drop_table("interruptions")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("ck_tasks_status", type_="check")
        batch.create_check_constraint(
            "ck_tasks_status",
            "status IN " + repr(OLD_STATUSES),
        )
