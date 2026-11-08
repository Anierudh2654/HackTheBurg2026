"""Application-scoped service dependencies."""
from dataclasses import dataclass, field
from ..config import get_settings
from ..documents import DocumentRepository
from ..graph.store import GraphStore
from ..registry import Registry
from ..storage import BlobStore
from ..trajectory import TrajectoryWriter
from ..extract.jobs import ExtractionJobs
from ..gnn.serve import GNNScorer


@dataclass
class AppState:
    graph: GraphStore = field(default_factory=GraphStore)
    registry: Registry | None = None
    blob: BlobStore | None = None
    documents: DocumentRepository | None = None
    jobs: ExtractionJobs = field(default_factory=ExtractionJobs)
    idempotency: dict[str, tuple[str, float, object]] = field(default_factory=dict)
    sessions: object | None = None
    scorer: GNNScorer | None = None
    settings_loaded: bool = False

    def initialise(self) -> None:
        if self.settings_loaded:
            return
        settings = get_settings()
        self.registry = Registry.load(settings.registry_path)
        self.blob = BlobStore(settings.blob_url, settings.blob_s3_key, settings.blob_s3_secret)
        self.scorer = GNNScorer(settings.gnn_model_dir, settings.gnn_active_model)
        sessions = None
        if settings.database_url:
            from ..db.repository import DatabaseGraphStore
            self.graph = DatabaseGraphStore(settings.database_url)
            sessions = self.graph.sessions
        self.documents = DocumentRepository(self.blob, self.graph, sessions, self.registry)
        self.sessions = sessions
        self.jobs.sessions = sessions
        if sessions is not None:
            self.jobs.recover_running()
        self.settings_loaded = True

    def trajectory(self, run_id: str) -> TrajectoryWriter:
        return TrajectoryWriter(get_settings().trajectory_dir, run_id)


state = AppState()
