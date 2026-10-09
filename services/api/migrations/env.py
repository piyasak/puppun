"""Alembic environment. The URL comes from the caller's config or DATABASE_URL, never from alembic.ini."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, text

from clipflow_api.db import checked_schema, driver_url
from clipflow_api.models import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    url = config.get_main_option("sqlalchemy.url") or os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return driver_url(url)


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # DB_SCHEMA: tables and alembic_version live in their own schema, never `public` (E-49).
    schema = checked_schema(os.environ.get("DB_SCHEMA", ""))
    engine = create_engine(_url())
    with engine.connect() as connection:
        if schema:
            connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                          version_table_schema=schema or None)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
