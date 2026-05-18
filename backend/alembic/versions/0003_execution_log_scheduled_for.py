"""add scheduled_for to execution_log

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-17

Phase 6a: preserves "when the brain wanted me to do this" across reschedules.
A task can get pushed Mon→Wed→Fri before the user actually does it Sunday;
without this column we'd lose the scheduled-vs-actual drift history that
weekly reports want to surface.

Captured at /tasks/{id}/done time by reading the current calendar_block.start
for the task BEFORE the reschedule wipes the block.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("execution_log") as batch:
        batch.add_column(sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("execution_log") as batch:
        batch.drop_column("scheduled_for")
