import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


migration = importlib.import_module("migrations.versions.f256f73ad477_add_job_runs")


def _run_upgrade(connection, monkeypatch):
    context = MigrationContext.configure(connection)
    monkeypatch.setattr(migration, "op", Operations(context))
    migration.upgrade()


def test_upgrade_adds_job_runs_to_existing_processing_job_table(monkeypatch):
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "processing_job",
        metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("domain", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    with engine.begin() as connection:
        metadata.create_all(connection)

        _run_upgrade(connection, monkeypatch)

        column_names = {
            column["name"] for column in sa.inspect(connection).get_columns("processing_job")
        }

    assert "job_runs" in column_names


def test_upgrade_creates_processing_job_table_on_fresh_database(monkeypatch):
    engine = sa.create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        _run_upgrade(connection, monkeypatch)

        column_names = {
            column["name"] for column in sa.inspect(connection).get_columns("processing_job")
        }

    assert column_names == {
        "id",
        "status",
        "domain",
        "job_runs",
        "error_message",
        "created_at",
    }
