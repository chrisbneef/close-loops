"""add password_hash to users

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-28

Phase 8: auth. Adds a bcrypt password hash to the users table so the two
cofounders can log in. Nullable — users who never log in directly (e.g.
contractors who only receive delegated tasks) simply have no hash.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("password_hash", sa.String(255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("password_hash")
