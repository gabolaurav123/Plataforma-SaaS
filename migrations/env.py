import os
from alembic import context
from sqlalchemy import create_engine, pool
from platform_app.models import Base
from platform_app.config import get_settings

config = context.config
settings = get_settings()
url = (
    os.environ.get("MIGRATION_DATABASE_URL")
    or (settings.system_database_url or settings.database_url).get_secret_value()
)
target_metadata = Base.metadata
if context.is_offline_mode():
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"}
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=engine.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()
