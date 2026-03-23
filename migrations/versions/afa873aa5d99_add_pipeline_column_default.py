"""add pipeline column with default

Revision ID: afa873aa5d99
Revises: f256f73ad477
Create Date: 2026-03-23 08:46:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'afa873aa5d99'
down_revision = 'f256f73ad477'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table('processing_job'):
        existing_columns = {column['name'] for column in inspector.get_columns('processing_job')}
        if 'pipeline' not in existing_columns:
            op.add_column('processing_job', sa.Column('pipeline', sa.String(), nullable=True, server_default='ontology'))
            # For existing rows, ensure they are set to 'ontology'
            op.execute("UPDATE processing_job SET pipeline = 'ontology' WHERE pipeline IS NULL")


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table('processing_job'):
        existing_columns = {column['name'] for column in inspector.get_columns('processing_job')}
        if 'pipeline' in existing_columns:
            op.drop_column('processing_job', 'pipeline')
