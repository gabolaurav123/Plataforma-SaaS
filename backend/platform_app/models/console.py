"""Private routing state. Only the trusted Telegram worker may access these tables."""

from sqlalchemy import String, BigInteger, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, Record


class ConsoleState(Record, Base):
    __tablename__ = "console_states"
    __table_args__ = (UniqueConstraint("bot_key", "telegram_user_id"),)
    bot_key: Mapped[str] = mapped_column(String(36))
    telegram_user_id: Mapped[int] = mapped_column(BigInteger)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True)


class ConsoleButton(Record, Base):
    __tablename__ = "console_buttons"
    bot_key: Mapped[str] = mapped_column(String(36))
    telegram_user_id: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True)
    used_at: Mapped[int | None] = mapped_column(BigInteger)


class PollCursor(Record, Base):
    __tablename__ = "poll_cursors"
    bot_key: Mapped[str] = mapped_column(String(36), unique=True)
    next_offset: Mapped[int] = mapped_column(BigInteger, default=0)
