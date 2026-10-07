"""G2-05 (partial): migrations apply on an empty database, match the models, and roll back."""

from __future__ import annotations

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from clipflow_api.models import Base


def test_upgrade_matches_models_then_downgrade_and_upgrade_again(database_url, alembic_config):
    # Runs on the session database before or after the app fixture; both orders leave it at head.
    cfg = alembic_config(database_url)
    command.upgrade(cfg, "head")
    engine = create_engine(database_url)
    try:
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
        assert diff == [], f"models and migrations differ: {diff}"

        command.downgrade(cfg, "base")
        assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
        command.upgrade(cfg, "head")
        assert {"workspaces", "users", "environments"} <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
