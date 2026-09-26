import sys
from pathlib import Path

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.db import Base, engine
from backend import models  # noqa: F401

config = context.config
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=str(engine.url), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
