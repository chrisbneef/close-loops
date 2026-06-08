"""make interruptions.task_id nullable for free-standing pauses

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-03

Until now every Interruption was anchored to a Task — pauses were always
"paused from working on X." The gap-fill flow at end of day lets the user
log a free-standing pause (lunch, school run, etc.) that isn't tied to any
specific task; for those we leave task_id NULL.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("interruptions") as batch:
        batch.alter_column("task_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("interruptions") as batch:
        batch.alter_column("task_id", existing_type=sa.Integer(), nullable=False)
