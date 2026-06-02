"""add recurrence to tasks

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-02

Daily / weekly / monthly recurring tasks. When a task with a recurrence value
is marked done, a fresh copy is spawned (subtasks reset to uncompleted, deadline
shifted forward by the interval) so the next occurrence shows up on the board.
NULL = one-shot task (the default).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("recurrence", sa.String(16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("recurrence")
