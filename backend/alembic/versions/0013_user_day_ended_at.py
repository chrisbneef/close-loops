"""add day_ended_at to users

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-03

Mirror of day_started_at — pinned when the user clicks "End Your Day" on
the dashboard. Used by the day timeline to bracket today's window and to
detect gaps that the user can fill in retroactively.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("day_ended_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("day_ended_at")
