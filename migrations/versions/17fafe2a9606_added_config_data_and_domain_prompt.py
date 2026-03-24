"""Added config_data and domain_prompt

Revision ID: 17fafe2a9606
Revises: f256f73ad477
Create Date: 2026-03-19 13:17:00.175212

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '17fafe2a9606'
down_revision = 'f256f73ad477'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table('processing_job'):
        existing_columns = {column['name'] for column in inspector.get_columns('processing_job')}
        if 'config_data' not in existing_columns:
            op.add_column('processing_job', sa.Column('config_data', sa.String(), nullable=True))
        if 'domain_prompt' not in existing_columns:
            op.add_column('processing_job', sa.Column('domain_prompt', sa.String(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table('processing_job'):
        existing_columns = {column['name'] for column in inspector.get_columns('processing_job')}
        if 'domain_prompt' in existing_columns:
            op.drop_column('processing_job', 'domain_prompt')
        if 'config_data' in existing_columns:
            op.drop_column('processing_job', 'config_data')
