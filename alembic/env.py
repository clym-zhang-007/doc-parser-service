"""Alembic 运行环境：绑定 SQLAlchemy 模型元数据与数据库 URL。"""

from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.models import Base, Job  # noqa: F401 — 注册 Job 到 metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """与 app.core.database 使用同一环境变量，便于 docker-compose / 本地一致。"""
    return os.getenv(
        "DATABASE_URL",
        "postgresql://doc_parser:doc_parser@postgres:5432/doc_parser",
    )


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(get_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
