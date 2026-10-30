"""Alembic environment: migrate payments_db using DATABASE_URL."""
import os
from logging.config import fileConfig
from alembic import context
from sqlalchemy import create_engine
from app.domain.models import Base

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)

URL = os.environ.get("DATABASE_URL", "sqlite:///./payments.db")


def run_offline() -> None:
    context.configure(url=URL, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    with create_engine(URL, pool_pre_ping=True).connect() as conn:
        context.configure(connection=conn, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()


run_offline() if context.is_offline_mode() else run_online()
