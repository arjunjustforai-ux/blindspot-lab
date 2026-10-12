"""tutor messages record the learner-model context shown beside each answer

Revision ID: 0002_tutor_learner_context
Revises: 0001_initial
Create Date: 2026-10-12 01:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_tutor_learner_context"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tutor_messages", sa.Column("learner_context", postgresql.JSONB(astext_type=sa.Text()),
                                              nullable=False, server_default=sa.text("'{}'::jsonb")))


def downgrade() -> None:
    op.drop_column("tutor_messages", "learner_context")
