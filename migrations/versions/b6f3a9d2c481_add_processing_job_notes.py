"""add processing job notes

Revision ID: b6f3a9d2c481
Revises: 9f3d7b6a1c21
Create Date: 2026-06-15 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "b6f3a9d2c481"
down_revision = "9f3d7b6a1c21"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("processing_job_note"):
        return

    op.create_table(
        "processing_job_note",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["processing_job.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_processing_job_note_job_id",
        "processing_job_note",
        ["job_id"],
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("processing_job_note"):
        return

    op.drop_index("ix_processing_job_note_job_id", table_name="processing_job_note")
    op.drop_table("processing_job_note")
