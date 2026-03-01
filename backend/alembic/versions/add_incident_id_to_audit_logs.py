"""add incident_id to audit_logs

Revision ID: a1b2c3d4e5f6
Revises: dcad2b764ffd
Create Date: 2026-03-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "dcad2b764ffd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("incident_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_logs", "incident_id")
