import time
import uuid
from sqlalchemy import BigInteger, String, ForeignKey, UniqueConstraint, ForeignKeyConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, declared_attr


def now() -> int:
    return int(time.time())


def uid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[int] = mapped_column(BigInteger, default=now, index=True)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=now, onupdate=now)


class Scoped(Record):
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)

    @declared_attr.directive
    def __table_args__(cls):
        return (UniqueConstraint("tenant_id", "id"),)


def scoped_constraints(*constraints):
    return (UniqueConstraint("tenant_id", "id"), *constraints)


def tenant_fk(field: str, table: str):
    return ForeignKeyConstraint(["tenant_id", field], [f"{table}.tenant_id", f"{table}.id"])
