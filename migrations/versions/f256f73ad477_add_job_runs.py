"""add job_runs

Revision ID: f256f73ad477
Revises: 
Create Date: 2026-03-11 11:48:47.294319

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f256f73ad477'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table('processing_job'):
        op.create_table(
            'processing_job',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('status', sa.String(), nullable=False),
            sa.Column('domain', sa.String(), nullable=True),
            sa.Column('job_runs', sa.String(), nullable=True),
            sa.Column('error_message', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        return

    existing_columns = {column['name'] for column in inspector.get_columns('processing_job')}
    if 'job_runs' not in existing_columns:
        op.add_column('processing_job', sa.Column('job_runs', sa.String(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table('processing_job'):
        return

    existing_columns = {column['name'] for column in inspector.get_columns('processing_job')}
    if 'job_runs' in existing_columns:
        op.drop_column('processing_job', 'job_runs')
