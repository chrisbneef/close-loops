"""add day_started_at to users

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-03

Tracks the last time the user clicked Start Your Day. The dashboard's TODAY
section compares this to today's local date — if they differ, the section
shows the Start Your Day CTA instead of yesterday's plan.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("day_started_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("day_started_at")
