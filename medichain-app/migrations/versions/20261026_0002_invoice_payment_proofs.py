"""Store patient-submitted payment evidence for manual admin review."""
from alembic import op
import sqlalchemy as sa


revision = "20261026_0002"
down_revision = "20261023_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoice_payment_proofs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("submitted_by", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("rejection_reason", sa.String(length=500), server_default="", nullable=False),
        sa.Column("submitted_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invoice_payment_proofs_invoice_id", "invoice_payment_proofs", ["invoice_id"])
    op.create_index("ix_invoice_payment_proofs_status", "invoice_payment_proofs", ["status"])


def downgrade() -> None:
    raise RuntimeError(
        "Payment proof history is retained as audit evidence. Restore a verified "
        "pre-migration backup to remove this table without losing records."
    )
