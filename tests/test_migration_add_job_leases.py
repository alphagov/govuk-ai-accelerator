import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


migration = importlib.import_module("migrations.versions.c4e92f1b7a10_add_job_leases")


def _run_upgrade(connection, monkeypatch):
    context = MigrationContext.configure(connection)
    monkeypatch.setattr(migration, "op", Operations(context))
    migration.upgrade()


def test_upgrade_adds_lease_columns_to_existing_processing_job_table(monkeypatch):
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
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    with engine.begin() as connection:
        metadata.create_all(connection)
        _run_upgrade(connection, monkeypatch)

        column_names = {
            column["name"] for column in sa.inspect(connection).get_columns("processing_job")
        }

    assert {"claimed_by", "claimed_at", "heartbeat_at", "attempt_count"} <= column_names
