from contextlib import contextmanager
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session, with_loader_criteria
from sqlalchemy.pool import StaticPool
from .models.base import Scoped
from .errors import DomainError


class TenantSession(Session):
    """Application scope is mandatory; PostgreSQL RLS is a second boundary."""


@event.listens_for(TenantSession, "do_orm_execute")
def apply_scope(state):
    tenant_id = state.session.info.get("tenant_id")
    if not tenant_id:
        raise DomainError("TENANT_REQUIRED", "Selecciona un espacio de trabajo.", 403)
    if state.is_select:
        state.statement = state.statement.options(
            with_loader_criteria(Scoped, lambda cls: cls.tenant_id == tenant_id, include_aliases=True)
        )
    elif state.is_update or state.is_delete:
        # Bulk writes bypass before_flush; disallow them on scoped API sessions.
        raise DomainError("BULK_WRITE_FORBIDDEN", "Usa el servicio de dominio.", 403)


@event.listens_for(TenantSession, "before_flush")
def enforce_write_scope(session, *_):
    for obj in session.new | session.dirty | session.deleted:
        if isinstance(obj, Scoped) and obj.tenant_id != session.info.get("tenant_id"):
            raise DomainError("TENANT_MISMATCH", "Recurso no disponible.", 404)


class Database:
    def __init__(self, settings):
        self.on_jobs = lambda: None
        self.on_bots = lambda: None

        def engine(url):
            kwargs = {"pool_pre_ping": True}
            if url.startswith("sqlite"):
                kwargs["connect_args"] = {"check_same_thread": False}
                if ":memory:" in url:
                    kwargs["poolclass"] = StaticPool
            result = create_engine(url, **kwargs)
            if url.startswith("sqlite"):

                @event.listens_for(result, "connect")
                def sqlite_fk(connection, _):
                    connection.execute("PRAGMA foreign_keys=ON")

            return result

        self.engine = engine(settings.database_url.get_secret_value())
        self.system_engine = (
            engine(settings.system_database_url.get_secret_value())
            if settings.system_database_url
            else self.engine
        )

    @contextmanager
    def system(self):
        """Only trusted webhook routing, identity bootstrap, workers and audited owner operations."""
        with Session(self.system_engine, expire_on_commit=False) as session:
            with session.begin():
                yield session
            if session.info.get("jobs_enqueued"):
                self.on_jobs()
            if session.info.get("bots_changed"):
                self.on_bots()

    @contextmanager
    def tenant(self, tenant_id):
        with (
            TenantSession(self.engine, expire_on_commit=False, info={"tenant_id": tenant_id}) as session,
            session.begin(),
        ):
            if self.engine.dialect.name == "postgresql":
                session.connection().execute(
                    text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": tenant_id}
                )
            yield session
        if session.info.get("jobs_enqueued"):
            self.on_jobs()
        if session.info.get("bots_changed"):
            self.on_bots()

    def verify_production_boundary(self):
        """Fail deployment if the API credential can bypass or dismantle tenant RLS."""
        from .models import Base

        if self.engine.dialect.name != "postgresql":
            raise RuntimeError("PostgreSQL is required")
        expected = {table.name for table in Base.metadata.tables.values() if "tenant_id" in table.c}
        with self.engine.connect() as connection:
            dangerous = connection.scalar(
                text("""
                SELECT EXISTS (SELECT 1 FROM pg_roles
                WHERE (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb)
                AND pg_has_role(current_user, oid, 'MEMBER'))
            """)
            )
            rows = connection.execute(
                text("""
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                       pg_has_role(current_user, c.relowner, 'MEMBER') AS can_own
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r'
            """)
            ).all()
            protected = {
                name for name, enabled, forced, can_own in rows if enabled and forced and not can_own
            }
            if dangerous or not expected.issubset(protected):
                raise RuntimeError("API database role or tenant RLS is unsafe")
            for private_table in [
                "console_states",
                "console_buttons",
                "poll_cursors",
                "auth_sessions",
                "platform_settings",
            ]:
                if connection.scalar(
                    text(
                        "SELECT has_table_privilege(current_user, :table_name, 'SELECT,INSERT,UPDATE,DELETE')"
                    ),
                    {"table_name": private_table},
                ):
                    raise RuntimeError("Private routing tables must be inaccessible to the API database role")


def get_scoped(session, model, entity_id, tenant_id):
    obj = session.scalar(select(model).where(model.id == entity_id, model.tenant_id == tenant_id))
    if obj is None:
        raise DomainError("NOT_FOUND", "Recurso no disponible.", 404)
    return obj
