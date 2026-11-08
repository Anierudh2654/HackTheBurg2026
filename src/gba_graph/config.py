"""Track B runtime configuration."""
from functools import lru_cache
from pathlib import Path
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gba_env: str = "dev"
    service_token: str = ""
    graph_api_url: str = "http://localhost:8101"
    blob_url: str = "file://./.blobs"
    blob_s3_key: str = ""
    blob_s3_secret: str = ""
    trajectory_dir: Path = Path("./trajectory")
    registry_path: Path = Path("./config/registry.yaml")
    database_url: str = ""
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_dim: int = 384
    rerank_model: str = ""
    gnn_model_dir: Path = Path("./models")
    gnn_active_model: str = "baseline-text-v0"
    gnn_flag_threshold: float = 0.3
    ingest_user_agent: str = ""
    agent_user_agent: str = ""
    extract_chunk_chars: int = 6000
    extract_max_docs_per_job: int = 10
    as_of_leakage_mode: str = "strict"
    llm_mode: str = "replay"
    llm_cache_dir: Path = Path("./.llm_cache")
    llm_provider: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model_extractor: str = ""
    llm_model_judge: str = ""
    courtlistener_token: str = ""

    @model_validator(mode="after")
    def validate_runtime(self) -> "Settings":
        if self.ingest_user_agent == "":
            self.ingest_user_agent = self.agent_user_agent
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
