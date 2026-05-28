"""allow 'whiteboard' task status

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-28

Adds 'whiteboard' to the tasks.status CHECK constraint — a parked-idea backlog
column shown first on the Kanban. Whiteboard tasks are deliberately outside the
scheduler's ACTIVE_STATUSES, so they never get a calendar block or surface as a
next action until promoted to 'pending'.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = "status IN ('pending', 'scheduled', 'in_progress', 'paused', 'done', 'decayed')"
_NEW = "status IN ('whiteboard', 'pending', 'scheduled', 'in_progress', 'paused', 'done', 'decayed')"


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("ck_tasks_status", type_="check")
        batch.create_check_constraint("ck_tasks_status", _NEW)


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("ck_tasks_status", type_="check")
        batch.create_check_constraint("ck_tasks_status", _OLD)
