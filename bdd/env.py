"""Environnement Alembic : la base vient de DATABASE_URL, les tables de lib/modeles.py."""
from alembic import context

from lib.bdd import get_engine
from lib.modeles import Base

target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=str(get_engine().url), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
