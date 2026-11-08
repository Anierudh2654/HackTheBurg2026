"""Initial Track B schema from Doc 02 section 4."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table("documents",
        sa.Column("doc_id", sa.Text, primary_key=True), sa.Column("source_id", sa.Text, nullable=False),
        sa.Column("registry_entry_id", sa.Text), sa.Column("url", sa.Text, nullable=False),
        sa.Column("media_type", sa.Text, nullable=False), sa.Column("title", sa.Text), sa.Column("doc_type", sa.Text),
        sa.Column("doc_date", sa.Date), sa.Column("version_label", sa.Text), sa.Column("canon_version", sa.Text, nullable=False),
        sa.Column("char_length", sa.Integer, nullable=False), sa.Column("page_markers", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("source", postgresql.JSONB, nullable=False), sa.Column("registered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("documents_entry", "documents", ["registry_entry_id"])
    op.create_index("documents_date", "documents", ["doc_date"])
    op.create_table("chunks", sa.Column("chunk_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("doc_id", sa.Text, sa.ForeignKey("documents.doc_id"), nullable=False), sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("start", sa.Integer, nullable=False), sa.Column("end", sa.Integer, nullable=False), sa.Column("text", sa.Text, nullable=False),
        sa.Column("tsv", postgresql.TSVECTOR, nullable=False), sa.Column("embedding", Vector(384)))
    op.create_unique_constraint("uq_chunks_doc_ordinal", "chunks", ["doc_id", "ordinal"])
    op.execute("CREATE INDEX chunks_tsv ON chunks USING gin(tsv)")
    op.execute("CREATE INDEX chunks_emb ON chunks USING hnsw (embedding vector_cosine_ops)")
    op.create_table("nodes", sa.Column("node_id", sa.Text, primary_key=True), sa.Column("node_type", sa.Text, nullable=False),
        sa.Column("label", sa.Text, nullable=False), sa.Column("props", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("scope_frame", postgresql.JSONB), sa.Column("valid_from", sa.Date), sa.Column("valid_to", sa.Date),
        sa.Column("known_from", sa.Date, nullable=False), sa.Column("source_ids", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("origin", sa.Text, nullable=False), sa.Column("audited", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("node", postgresql.JSONB, nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("nodes_type", "nodes", ["node_type"])
    op.create_index("nodes_known", "nodes", ["known_from"])
    op.create_table("edges", sa.Column("edge_id", sa.Text, primary_key=True), sa.Column("src", sa.Text, nullable=False),
        sa.Column("dst", sa.Text, nullable=False), sa.Column("edge_type", sa.Text, nullable=False), sa.Column("valid_from", sa.Date),
        sa.Column("valid_to", sa.Date), sa.Column("known_from", sa.Date, nullable=False), sa.Column("origin", sa.Text, nullable=False),
        sa.Column("edge", postgresql.JSONB, nullable=False), sa.UniqueConstraint("src", "dst", "edge_type", name="uq_edges_relation"))
    op.create_index("edges_src", "edges", ["src", "edge_type"])
    op.create_index("edges_dst", "edges", ["dst", "edge_type"])
    op.create_table("node_documents", sa.Column("node_id", sa.Text, sa.ForeignKey("nodes.node_id"), primary_key=True),
        sa.Column("doc_id", sa.Text, sa.ForeignKey("documents.doc_id"), primary_key=True))
    op.create_table("extraction_jobs", sa.Column("job_id", sa.Text, primary_key=True), sa.Column("request", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.Text, nullable=False), sa.Column("result", postgresql.JSONB), sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_check_constraint("ck_extraction_jobs_status", "extraction_jobs", "status IN ('queued','running','done','failed')")
    op.create_table("gnn_models", sa.Column("model_version", sa.Text, primary_key=True), sa.Column("kind", sa.Text, nullable=False),
        sa.Column("trained_on_cutoff", sa.Date), sa.Column("metrics", postgresql.JSONB), sa.Column("path", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_table("ingest_runs", sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True), sa.Column("entry_id", sa.Text),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("fetched", sa.Integer, server_default="0"), sa.Column("skipped", sa.Integer, server_default="0"),
        sa.Column("failed", sa.Integer, server_default="0"), sa.Column("log", postgresql.JSONB))
    op.create_table("idempotency", sa.Column("key", sa.Text, primary_key=True), sa.Column("request_hash", sa.Text, nullable=False),
        sa.Column("response", postgresql.JSONB, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))


def downgrade() -> None:
    for table in ("idempotency", "ingest_runs", "gnn_models", "extraction_jobs", "node_documents", "edges", "nodes", "chunks", "documents"):
        op.drop_table(table)
