"""PostgreSQL-backed graph store for deployed Track B instances."""
from __future__ import annotations

from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker
from ..contracts_local.models import Edge, Node
from ..graph.store import GraphStore
from .models import EdgeRow, NodeRow


class DatabaseGraphStore(GraphStore):
    def __init__(self, database_url: str):
        super().__init__()
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        with self.engine.connect() as connection:
            extension = connection.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).scalar()
            if extension is None or tuple(int(part) for part in extension.split(".")[:2]) < (0, 7):
                raise RuntimeError("pgvector extension >= 0.7 is required")
            tables = connection.execute(text("SELECT to_regclass('public.nodes')")).scalar()
            if tables is None:
                raise RuntimeError("graph database is not migrated; run `gba-graph migrate`")
        self.load()

    def load(self) -> None:
        with self.sessions() as session:
            for row in session.scalars(select(NodeRow)).all():
                self.nodes[row.node_id] = Node.model_validate(row.node)
            for row in session.scalars(select(EdgeRow)).all():
                self.edges[row.edge_id] = Edge.model_validate(row.edge)

    def add_node(self, node: Node) -> None:
        existing = self.nodes.get(node.node_id)
        if existing is not None:
            return super().add_node(node)
        super().add_node(node)
        payload = node.model_dump(mode="json")
        with self.sessions.begin() as session:
            session.execute(insert(NodeRow).values(node_id=node.node_id, node_type=node.node_type, label=node.label,
                props=node.props, scope_frame=node.scope_frame.model_dump(mode="json") if node.scope_frame else None,
                valid_from=node.valid_from, valid_to=node.valid_to, known_from=node.known_from,
                source_ids=node.source_ids, origin=node.origin, audited=node.audited, node=payload)
                .on_conflict_do_nothing(index_elements=[NodeRow.node_id]))

    def persist_node(self, node: Node) -> None:
        payload = node.model_dump(mode="json")
        with self.sessions.begin() as session:
            session.execute(text("UPDATE nodes SET source_ids=CAST(:source_ids AS jsonb), node=CAST(:node AS jsonb), updated_at=now() WHERE node_id=:node_id"),
                {"node_id": node.node_id, "source_ids": __import__("json").dumps(node.source_ids),
                 "node": __import__("json").dumps(payload, ensure_ascii=False)})

    def add_edge(self, edge: Edge) -> None:
        existing = self.edges.get(edge.edge_id)
        if existing is not None:
            return super().add_edge(edge)
        super().add_edge(edge)
        with self.sessions.begin() as session:
            session.execute(insert(EdgeRow).values(edge_id=edge.edge_id, src=edge.src, dst=edge.dst,
                edge_type=edge.edge_type, valid_from=edge.valid_from, valid_to=edge.valid_to,
                known_from=edge.known_from, origin=edge.origin, edge=edge.model_dump(mode="json"))
                .on_conflict_do_nothing(index_elements=[EdgeRow.edge_id]))
