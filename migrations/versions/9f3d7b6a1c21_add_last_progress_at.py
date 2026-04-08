"""add last_progress_at

Revision ID: 9f3d7b6a1c21
Revises: c4e92f1b7a10
Create Date: 2026-04-02 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "9f3d7b6a1c21"
down_revision = "c4e92f1b7a10"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("processing_job"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("processing_job")}

    if "last_progress_at" not in existing_columns:
        op.add_column(
            "processing_job",
            sa.Column("last_progress_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("processing_job"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("processing_job")}

    if "last_progress_at" in existing_columns:
        op.drop_column("processing_job", "last_progress_at")
