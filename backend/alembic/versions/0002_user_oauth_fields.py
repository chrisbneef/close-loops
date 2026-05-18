"""add email + google_refresh_token to users

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-17

Phase 4 needs per-user Google OAuth: each cofounder has their own calendar,
so each User row stores its own refresh token. Email is the natural lookup
key for /oauth/google/start (we resolve user by email match against the
Google id_token sub claim's email field).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("email", sa.String(255), nullable=True))
        batch.add_column(sa.Column("google_refresh_token", sa.Text, nullable=True))
        batch.create_unique_constraint("uq_users_email", ["email"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_email", type_="unique")
        batch.drop_column("google_refresh_token")
        batch.drop_column("email")
