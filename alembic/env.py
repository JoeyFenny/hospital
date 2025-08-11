from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# Import DB URL from app settings; fall back to INI if not set
try:
    from app.config import settings  # type: ignore
except Exception:  # pragma: no cover
    settings = None  # type: ignore

if settings and getattr(settings, "database_url", None):
    # Do not force override; the get_url() will prefer DATABASE_URL env first
    # This keeps docker-compose's DATABASE_URL (host 'db') working
    pass

# If you want autogenerate support, set target_metadata to your
# model's MetaData object. We keep it optional here.
target_metadata = None

try:
    # Ensure models are imported so metadata is populated if used later
    import app.models  # noqa: F401
    from app.database import Base  # type: ignore

    target_metadata = Base.metadata
except Exception:
    # Autogenerate not required for initial setup
    pass


def get_url() -> str:
    # Prefer environment variable (set in docker-compose for container)
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    if settings and getattr(settings, "database_url", None):
        return settings.database_url
    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url:
        return ini_url
    # Fallback local default
    return "postgresql+asyncpg://postgres:postgres@localhost:5432/hospital"


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable: AsyncEngine = create_async_engine(
        get_url(),
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())


