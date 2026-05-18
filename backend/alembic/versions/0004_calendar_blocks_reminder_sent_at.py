"""add reminder_sent_at to calendar_blocks

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-17

Phase 6c: dedupes "have we pinged the user about this upcoming task yet?"
Set when the reminder_loop fires a push for a given block. When the scheduler
re-packs and a block gets deleted + re-created (new row), reminder_sent_at
resets to NULL so the new time gets a fresh ping.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("calendar_blocks") as batch:
        batch.add_column(sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("calendar_blocks") as batch:
        batch.drop_column("reminder_sent_at")
