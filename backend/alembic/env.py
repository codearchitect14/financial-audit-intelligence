"""Alembic environment.

Runs against the synchronous engine. Migrations are a batch operation with no
concurrency to exploit, and keeping them synchronous avoids the event-loop
juggling that the async driver would otherwise force on every revision script.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from pgvector.sqlalchemy import Vector
from sqlalchemy import engine_from_config, pool

from fai.core.config import settings

# Importing the registry is what populates Base.metadata. Without it,
# autogenerate would compare the database against an empty schema and helpfully
# offer to drop every table.
from fai.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.sync_database_url)

target_metadata = Base.metadata


# Tables owned by an extension rather than by this schema history.
EXCLUDED_TABLES = {"spatial_ref_sys"}


def include_object(obj: object, name: str | None, type_: str, *_args: object) -> bool:
    """Exclude objects Alembic should not manage.

    pgvector creates its own index types and internal objects; those belong to
    the extension, not to this schema history.
    """
    return not (type_ == "table" and name in EXCLUDED_TABLES)


def render_item(type_: str, obj: object, autogen_context: object) -> str | bool:
    """Render pgvector columns with the import they need.

    Alembic autogenerate emits a fully qualified type name for third-party
    column types but does not add the corresponding import, so a generated
    revision referencing a vector column fails at run time with a NameError.
    Declaring the import here fixes every future revision rather than leaving
    it as a manual edit someone will eventually forget.
    """
    if type_ == "type" and isinstance(obj, Vector):
        autogen_context.imports.add("import pgvector.sqlalchemy")  # type: ignore[attr-defined]
        return f"pgvector.sqlalchemy.Vector(dim={obj.dim})"
    return False


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing it, for review before release."""
    context.configure(
        url=settings.sync_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Execute migrations against the configured database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_object=include_object,
            render_item=render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
