"""Encrypted receipts shared by API and worker without a shared filesystem."""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bank_receipts", sa.Column("receipt_ciphertext", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("bank_receipts", "receipt_ciphertext")
