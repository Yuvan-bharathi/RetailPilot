"""supplier_product.moq may be 0 (no minimum order quantity) (D-47).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# names are short: the metadata naming convention renders "moq" as ck_supplier_product_moq


def upgrade() -> None:
    op.drop_constraint("moq", "supplier_product", type_="check")
    op.create_check_constraint("moq", "supplier_product", "moq >= 0")


def downgrade() -> None:
    op.drop_constraint("moq", "supplier_product", type_="check")
    op.create_check_constraint("moq", "supplier_product", "moq >= 1")
