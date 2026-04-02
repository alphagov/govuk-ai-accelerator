import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


migration = importlib.import_module("migrations.versions.9f3d7b6a1c21_add_last_progress_at")


def _run_upgrade(connection, monkeypatch):
    context = MigrationContext.configure(connection)
    monkeypatch.setattr(migration, "op", Operations(context))
    migration.upgrade()


def test_upgrade_adds_last_progress_at_to_existing_processing_job_table(monkeypatch):
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "processing_job",
        metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("pipeline", sa.String(), nullable=True),
        sa.Column("domain", sa.String(), nullable=True),
        sa.Column("job_runs", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("claimed_by", sa.String(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    with engine.begin() as connection:
        metadata.create_all(connection)
        _run_upgrade(connection, monkeypatch)

        column_names = {
            column["name"] for column in sa.inspect(connection).get_columns("processing_job")
        }

    assert "last_progress_at" in column_names
