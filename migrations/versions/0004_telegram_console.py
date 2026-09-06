"""Durable private Telegram dialogs, callbacks and polling offsets."""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    for name, columns, constraints in [
        (
            "console_states",
            [
                sa.Column("bot_key", sa.String(36), nullable=False),
                sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
                sa.Column("data", sa.JSON(), nullable=False),
                sa.Column("expires_at", sa.BigInteger(), nullable=False),
            ],
            [sa.UniqueConstraint("bot_key", "telegram_user_id")],
        ),
        (
            "console_buttons",
            [
                sa.Column("bot_key", sa.String(36), nullable=False),
                sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
                sa.Column("action", sa.String(40), nullable=False),
                sa.Column("data", sa.JSON(), nullable=False),
                sa.Column("expires_at", sa.BigInteger(), nullable=False),
                sa.Column("used_at", sa.BigInteger(), nullable=True),
            ],
            [],
        ),
        (
            "poll_cursors",
            [
                sa.Column("bot_key", sa.String(36), nullable=False),
                sa.Column("next_offset", sa.BigInteger(), nullable=False),
            ],
            [sa.UniqueConstraint("bot_key")],
        ),
    ]:
        op.create_table(
            name,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.Column("updated_at", sa.BigInteger(), nullable=False),
            *columns,
            *constraints,
        )
        op.create_index(f"ix_{name}_created_at", name, ["created_at"])
        if name != "poll_cursors":
            op.create_index(f"ix_{name}_expires_at", name, ["expires_at"])


def downgrade():
    for name in ["poll_cursors", "console_buttons", "console_states"]:
        op.drop_table(name)
