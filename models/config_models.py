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
    embedding_model: str = "jinaai/jina-embeddings-v2-base-code"
    embedding_batch_size: int = 24
    embedding_max_length: int = 512
    embedding_device: str = "cuda"
    reviewer_model: str = "heuristic-v1"
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
    versions: VersionConfig = field(default_factory=VersionConfig)
