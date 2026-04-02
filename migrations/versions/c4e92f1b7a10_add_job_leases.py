"""add job lease fields

Revision ID: c4e92f1b7a10
Revises: afa873aa5d99
Create Date: 2026-04-02 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "c4e92f1b7a10"
down_revision = "afa873aa5d99"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("processing_job"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("processing_job")}

    if "claimed_by" not in existing_columns:
        op.add_column("processing_job", sa.Column("claimed_by", sa.String(), nullable=True))

    if "claimed_at" not in existing_columns:
        op.add_column("processing_job", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))

    if "heartbeat_at" not in existing_columns:
        op.add_column("processing_job", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))

    if "attempt_count" not in existing_columns:
        op.add_column(
            "processing_job",
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        )
        op.execute("UPDATE processing_job SET attempt_count = 0 WHERE attempt_count IS NULL")


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("processing_job"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("processing_job")}

    if "attempt_count" in existing_columns:
        op.drop_column("processing_job", "attempt_count")

    if "heartbeat_at" in existing_columns:
        op.drop_column("processing_job", "heartbeat_at")

    if "claimed_at" in existing_columns:
        op.drop_column("processing_job", "claimed_at")

    if "claimed_by" in existing_columns:
        op.drop_column("processing_job", "claimed_by")
