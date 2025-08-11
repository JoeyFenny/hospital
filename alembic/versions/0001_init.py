"""Initial schema: providers, procedures, ratings; text & spatial indexes

Revision ID: 0001_init
Revises: 
Create Date: 2025-08-11 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extensions required for indexes/search
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    op.execute("CREATE EXTENSION IF NOT EXISTS cube;")
    op.execute("CREATE EXTENSION IF NOT EXISTS earthdistance;")

    # providers
    op.create_table(
        "providers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("provider_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("state", sa.String(length=8), nullable=True),
        sa.Column("zip_code", sa.String(length=16), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.UniqueConstraint("provider_id", name="uq_provider_provider_id"),
    )
    op.create_index("idx_providers_zip", "providers", ["zip_code"])
    op.create_index("idx_providers_state", "providers", ["state"])
    # Functional GiST index for spatial filtering
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_providers_ll_earth ON providers USING gist (ll_to_earth(latitude, longitude));"
    )

    # procedures
    op.create_table(
        "procedures",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("provider_id", sa.String(length=32), nullable=False),
        sa.Column("ms_drg_definition", sa.String(length=255), nullable=False),
        sa.Column("total_discharges", sa.Integer(), nullable=True),
        sa.Column("average_covered_charges", sa.Numeric(14, 2), nullable=True),
        sa.Column("average_total_payments", sa.Numeric(14, 2), nullable=True),
        sa.Column("average_medicare_payments", sa.Numeric(14, 2), nullable=True),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["providers.provider_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "provider_id",
            "ms_drg_definition",
            name="uq_procedure_per_provider_drg",
        ),
    )
    op.create_index("idx_procedures_drg", "procedures", ["ms_drg_definition"])
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_procedures_drg_trgm ON procedures USING GIN (ms_drg_definition gin_trgm_ops);"
    )

    # ratings
    op.create_table(
        "ratings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("provider_id", sa.String(length=32), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["providers.provider_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("provider_id", name="uq_rating_per_provider"),
    )


def downgrade() -> None:
    # Drop dependent objects first
    op.execute("DROP INDEX IF EXISTS idx_procedures_drg_trgm;")
    op.drop_index("idx_procedures_drg", table_name="procedures")
    op.drop_table("procedures")

    op.drop_table("ratings")

    op.execute("DROP INDEX IF EXISTS idx_providers_ll_earth;")
    op.drop_index("idx_providers_state", table_name="providers")
    op.drop_index("idx_providers_zip", table_name="providers")
    op.drop_table("providers")


