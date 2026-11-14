"""Create the document intelligence schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("extracted_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "validation_issues",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("invoice_number", sa.String(length=160), nullable=True),
        sa.Column("supplier_name", sa.String(length=255), nullable=True),
        sa.Column("invoice_total", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("embedding", Vector(dim=1536), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_invoice_number", "documents", ["invoice_number"])
    op.create_index("ix_documents_invoice_supplier", "documents", ["invoice_number", "supplier_name"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"])
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index("ix_documents_supplier_name", "documents", ["supplier_name"])
    op.create_table(
        "processing_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_processing_attempts_document_id", "processing_attempts", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_processing_attempts_document_id", table_name="processing_attempts")
    op.drop_table("processing_attempts")
    op.drop_index("ix_documents_supplier_name", table_name="documents")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_index("ix_documents_sha256", table_name="documents")
    op.drop_index("ix_documents_invoice_supplier", table_name="documents")
    op.drop_index("ix_documents_invoice_number", table_name="documents")
    op.drop_table("documents")
