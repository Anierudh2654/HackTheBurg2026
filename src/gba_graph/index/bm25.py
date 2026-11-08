"""BM25-style local ranking; production indexes the same text in PostgreSQL tsvector."""
from .hybrid import lexical_rank

__all__ = ["lexical_rank"]
