"""Alembic env.py - 只管理 commission_db 中的表"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings
from app.core.database import Base

# 导入所有模型，确保 Base.metadata 包含它们
import app.models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 用运行时数据库 URL
settings = get_settings()

# 只迁移 commission_db 的表（Base），不包含 BusinessBase
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.commission_db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "format"},
    )
    with context.begin_transaction():
        context.execute("SET time_zone = '+08:00'")
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(settings.commission_db_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        connection.exec_driver_sql("SET time_zone = '+08:00'")
        # SQLAlchemy 2 starts an implicit transaction for the SET statement.
        # End that initialization transaction before Alembic establishes its
        # own commit boundary; otherwise successful DML migrations and the
        # alembic_version update are rolled back when the connection closes.
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
