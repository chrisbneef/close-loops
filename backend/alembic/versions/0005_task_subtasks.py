"""add task_subtasks for SOP-style checklists

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-17

Phase 8 — subtasks are checklist items WITHIN a single task (not separate
schedulable tasks). User example: "Edit Google ad video" task has subtasks
[cut video, upload to YouTube, get Michael's links, upload to Drive] —
mechanical SOP steps you check off as you go, but the parent task is still
one calendar block.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_subtasks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("task_id", sa.Integer, sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("completed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_task_subtasks_task", "task_subtasks", ["task_id", "position"])


def downgrade() -> None:
    op.drop_index("ix_task_subtasks_task", table_name="task_subtasks")
    op.drop_table("task_subtasks")
