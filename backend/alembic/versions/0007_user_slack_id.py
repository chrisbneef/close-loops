"""add slack_user_id to users

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-19

Phase: Slack slash-command intake. Maps the Slack user who runs `/loop ...`
to the Cadence user, so the decomposition's requester (and thus self/partner
owner routing) is correct. Falls back to the first cofounder if unmapped.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("slack_user_id", sa.String(64), nullable=True))
        batch.create_unique_constraint("uq_users_slack_user_id", ["slack_user_id"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_slack_user_id", type_="unique")
        batch.drop_column("slack_user_id")
