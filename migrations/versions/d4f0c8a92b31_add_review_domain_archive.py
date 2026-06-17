"""add review domain archive

Revision ID: d4f0c8a92b31
Revises: b6f3a9d2c481
Create Date: 2026-06-17 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "d4f0c8a92b31"
down_revision = "b6f3a9d2c481"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("review_domain_archive"):
        return

    op.create_table(
        "review_domain_archive",
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column("source_job_id", sa.String(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_job_id"], ["processing_job.id"]),
        sa.PrimaryKeyConstraint("domain"),
    )
    op.create_index(
        "ix_review_domain_archive_source_job_id",
        "review_domain_archive",
        ["source_job_id"],
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("review_domain_archive"):
        return

    op.drop_index(
        "ix_review_domain_archive_source_job_id",
        table_name="review_domain_archive",
    )
    op.drop_table("review_domain_archive")
