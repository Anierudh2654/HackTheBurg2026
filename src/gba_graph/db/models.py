"""SQLAlchemy schema matching Track B Doc 02 migration 0001."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pgvector.sqlalchemy import Vector


class Base(DeclarativeBase):
    pass


class DocumentRow(Base):
    __tablename__ = "documents"
    doc_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    registry_entry_id: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    doc_type: Mapped[str | None] = mapped_column(Text)
    doc_date: Mapped[date | None] = mapped_column(Date)
    version_label: Mapped[str | None] = mapped_column(Text)
    canon_version: Mapped[str] = mapped_column(Text, nullable=False)
    char_length: Mapped[int] = mapped_column(Integer, nullable=False)
    page_markers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    source: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NodeRow(Base):
    __tablename__ = "nodes"
    node_id: Mapped[str] = mapped_column(Text, primary_key=True)
    node_type: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    props: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    scope_frame: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    known_from: Mapped[date] = mapped_column(Date, nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    audited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    node: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class EdgeRow(Base):
    __tablename__ = "edges"
    edge_id: Mapped[str] = mapped_column(Text, primary_key=True)
    src: Mapped[str] = mapped_column(Text, nullable=False)
    dst: Mapped[str] = mapped_column(Text, nullable=False)
    edge_type: Mapped[str] = mapped_column(Text, nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    known_from: Mapped[date] = mapped_column(Date, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    edge: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    __table_args__ = (UniqueConstraint("src", "dst", "edge_type", name="uq_edges_relation"),)


class ChunkRow(Base):
    __tablename__ = "chunks"
    chunk_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(Text, ForeignKey("documents.doc_id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    start: Mapped[int] = mapped_column(Integer, nullable=False)
    end: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    tsv: Mapped[Any] = mapped_column(TSVECTOR, nullable=False)
    embedding: Mapped[Any | None] = mapped_column(Vector(384))
    __table_args__ = (UniqueConstraint("doc_id", "ordinal", name="uq_chunks_doc_ordinal"),)


class NodeDocumentRow(Base):
    __tablename__ = "node_documents"
    node_id: Mapped[str] = mapped_column(Text, ForeignKey("nodes.node_id"), primary_key=True)
    doc_id: Mapped[str] = mapped_column(Text, ForeignKey("documents.doc_id"), primary_key=True)


class ExtractionJobRow(Base):
    __tablename__ = "extraction_jobs"
    job_id: Mapped[str] = mapped_column(Text, primary_key=True)
    request: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GNNModelRow(Base):
    __tablename__ = "gnn_models"
    model_version: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    trained_on_cutoff: Mapped[date | None] = mapped_column(Date)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IngestRunRow(Base):
    __tablename__ = "ingest_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entry_id: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    log: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)


class IdempotencyRow(Base):
    __tablename__ = "idempotency"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
