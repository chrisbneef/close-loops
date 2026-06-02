"""add completion_notes to execution_log

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-02

Captures what the user wrote when marking a task done — typically a link to
a Drive doc / folder / Loom showing the deliverable, plus any short context.
Surfaced on Done cards and in the period reports' completed-tasks list.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("execution_log") as batch:
        batch.add_column(sa.Column("completion_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("execution_log") as batch:
        batch.drop_column("completion_notes")
