"""Bootstrap MediChain tables and establish the Alembic revision baseline.

Existing databases keep all current tables and rows. SQLAlchemy create_all only
creates missing tables; it does not alter existing columns. Review existing
schemas and take a verified backup before applying this revision to a database
that already contains user data.
"""
from alembic import op

from app.db import Base


revision = "20261023_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = [table for table in Base.metadata.sorted_tables if table.name != "invoice_payment_proofs"]
    Base.metadata.create_all(bind=bind, checkfirst=True, tables=tables)


def downgrade() -> None:
    raise RuntimeError(
        "The schema baseline is intentionally irreversible. Restore a verified "
        "pre-migration backup to roll back without deleting application data."
    )
