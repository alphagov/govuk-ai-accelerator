"""jobs

Revision ID: 53eeffd73fc3
Revises: cf7607613eec
Create Date: 2026-04-29 16:42:44.057923

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '53eeffd73fc3'
down_revision = 'cf7607613eec'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("v2_ontology_runs",
                    sa.Column("run_id", sa.UUID(as_uuid=True) , primary_key=True, nullable=False, server_default=sa.func("gen_random_uuid()")),
                    sa.Column("status", sa.Enum('pending', name='status'), nullable=False),
                    sa.Column("domain", sa.String(length=255), nullable=False),
                    sa.Column("tasks", sa.ARRAY(sa.String), nullable=False),
                    sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func("now()"))
                    )
    pass


def downgrade():
    op.drop_table('v2_ontology_runs')
    pass
