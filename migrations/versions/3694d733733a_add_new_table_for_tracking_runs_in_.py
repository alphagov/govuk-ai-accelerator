"""Add new table for tracking runs in version two of the Ontology Generator

Revision ID: 3694d733733a
Revises: 9f3d7b6a1c21
Create Date: 2026-05-01 14:28:14.395644

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '3694d733733a'
down_revision = '9f3d7b6a1c21'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('v2_ontology_runs',
    sa.Column('run_id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('status', sa.Enum('PENDING', name='runstatus'), nullable=False),
    sa.Column('domain', sa.String(length=255), nullable=False),
    sa.Column('tasks', postgresql.ARRAY(sa.String(length=255)), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('run_id')
    )
    with op.batch_alter_table('processing_job', schema=None) as batch_op:
        batch_op.alter_column('created_at',
               existing_type=postgresql.TIMESTAMP(),
               type_=sa.DateTime(timezone=True),
               existing_nullable=False)


def downgrade():
    with op.batch_alter_table('processing_job', schema=None) as batch_op:
        batch_op.alter_column('created_at',
               existing_type=sa.DateTime(timezone=True),
               type_=postgresql.TIMESTAMP(),
               existing_nullable=False)

    op.drop_table('v2_ontology_runs')
