from dataclasses import dataclass, field
from pathlib import Path
from typing import Tuple


@dataclass(slots=True)
class VersionConfig:
    parser_version: str = "1"
    graph_version: str = "1"
    chunking_version: str = "1"
    reviewer_bundle_version: str = "1"


@dataclass(slots=True)
class RuntimeConfig:
    project_root: Path
    data_dir: Path
    repo_root: Path
    duckdb_path: Path
    kuzu_path: Path
    lancedb_path: Path
    manifest_path: Path
    scan_excluded_dirs: Tuple[str, ...] = ()
    languages: Tuple[str, ...] = ("python", "typescript", "tsx")
    python_extensions: Tuple[str, ...] = (".py",)
    typescript_extensions: Tuple[str, ...] = (".ts", ".tsx", ".js", ".jsx")
    embedding_provider: str = "local"
    embedding_model: str = "jinaai/jina-embeddings-v2-base-code"
    embedding_batch_size: int = 24
    embedding_max_length: int = 512
    embedding_max_batch_tokens: int = 12000
    embedding_device: str = "auto"
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_retry_attempts: int = 3
    embedding_retry_backoff_seconds: float = 1.0
    embedding_max_concurrent_batches: int = 4
    process_extraction_enabled: bool = True
    process_max_depth: int = 3
    process_max_entrypoints: int = 600
    process_max_flows_per_entrypoint: int = 6
    process_max_records: int = 2500
    process_max_relationships: int = 5000
    llm_features_enabled: bool = False
    reviewer_model: str = "heuristic-v1"
    review_enabled: bool = True
    review_analysis_provider: str = "heuristic-multi-agent"
    review_analysis_model: str = "mistralai/devstral-small"
    review_max_source_chars: int = 12000
    review_max_chunks: int = 12
    review_max_chunk_chars: int = 1200
    review_max_symbols: int = 40
    review_max_graph_edges: int = 40
    review_max_prior_findings: int = 12
    review_group_size: int = 4
    review_group_max_source_chars: int = 24000
    review_run_legacy_heuristics_with_llm: bool = False
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str = ""
    openrouter_site_url: str = ""
    openrouter_app_name: str = "Coder"
    reviewer_prompt_version: str = "1"
    synthesizer_prompt_version: str = "1"
    max_review_workers: int = 3
    max_concurrent_llm_reviews: int = 10
    review_retry_attempts: int = 3
    review_retry_backoff_seconds: float = 1.0
    start_mcp_after_index: bool = True
    agents_file_enabled: bool = True
    versions: VersionConfig = field(default_factory=VersionConfig)

    def __post_init__(self) -> None:
        if self.embedding_batch_size < 1:
            raise ValueError(f"embedding_batch_size must be >= 1, got {self.embedding_batch_size}")
        if self.embedding_max_length < 1:
            raise ValueError(f"embedding_max_length must be >= 1, got {self.embedding_max_length}")
        if self.embedding_max_batch_tokens < 1:
            raise ValueError(f"embedding_max_batch_tokens must be >= 1, got {self.embedding_max_batch_tokens}")
        if self.embedding_retry_attempts < 0:
            raise ValueError(f"embedding_retry_attempts must be >= 0, got {self.embedding_retry_attempts}")
        if self.embedding_max_concurrent_batches < 1:
            raise ValueError(f"embedding_max_concurrent_batches must be >= 1, got {self.embedding_max_concurrent_batches}")
        if self.process_max_depth < 1:
            raise ValueError(f"process_max_depth must be >= 1, got {self.process_max_depth}")
        if self.process_max_entrypoints < 1:
            raise ValueError(f"process_max_entrypoints must be >= 1, got {self.process_max_entrypoints}")
        if self.process_max_records < 1:
            raise ValueError(f"process_max_records must be >= 1, got {self.process_max_records}")
        if self.review_max_source_chars < 1:
            raise ValueError(f"review_max_source_chars must be >= 1, got {self.review_max_source_chars}")
        if self.max_review_workers < 1:
            raise ValueError(f"max_review_workers must be >= 1, got {self.max_review_workers}")
        if self.max_concurrent_llm_reviews < 1:
            raise ValueError(f"max_concurrent_llm_reviews must be >= 1, got {self.max_concurrent_llm_reviews}")
        valid_devices = {"auto", "cpu", "cuda", "mps"}
        if self.embedding_device not in valid_devices:
            raise ValueError(f"embedding_device must be one of {valid_devices}, got {self.embedding_device!r}")
        valid_providers = {"local", "openai", "openai-compatible"}
        if self.embedding_provider not in valid_providers:
            raise ValueError(f"embedding_provider must be one of {valid_providers}, got {self.embedding_provider!r}")

    def safe_dict(self) -> dict[str, object]:
        """Return a dict representation with API keys masked."""
        from dataclasses import asdict
        d = asdict(self)
        for key in ("embedding_api_key", "openrouter_api_key"):
            val = d.get(key, "")
            if val and isinstance(val, str) and len(val) > 4:
                d[key] = val[:2] + "***" + val[-2:]
            elif val:
                d[key] = "***"
        return d
