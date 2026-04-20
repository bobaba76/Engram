import os
from pathlib import Path

from config.defaults import DEFAULT_DATA_DIRNAME
from models.config_models import RuntimeConfig


DEFAULT_SCAN_EXCLUDED_DIRS = (
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "vendor",
    "dist",
    "build",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".turbo",
    ".cache",
    "coverage",
    "tmp",
    "temp",
    DEFAULT_DATA_DIRNAME,
)


def _get_int_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        return max(int(raw_value), 1)
    except ValueError:
        return default


def _get_bool_env(name: str, default: bool) -> bool:
    raw_value = os.environ.get(name, "").strip().lower()
    if not raw_value:
        return default
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    return default


def _load_scan_excluded_dirs() -> tuple[str, ...]:
    raw_value = os.environ.get("CODER_SCAN_EXCLUDED_DIRS", "")
    if not raw_value.strip():
        return DEFAULT_SCAN_EXCLUDED_DIRS
    parts = [part.strip() for part in raw_value.split(",") if part.strip()]
    return tuple(dict.fromkeys(parts))


def load_settings(project_root: Path | None = None) -> RuntimeConfig:
    root = project_root or Path(__file__).resolve().parent.parent
    data_dir = root / DEFAULT_DATA_DIRNAME
    data_dir.mkdir(parents=True, exist_ok=True)
    openrouter_api_key = os.environ.get("OPENROUTER_API_KEY", "")
    review_analysis_provider = os.environ.get("CODER_REVIEW_ANALYSIS_PROVIDER", "").strip()
    if not review_analysis_provider:
        review_analysis_provider = "openrouter-multi-agent" if openrouter_api_key else "heuristic-multi-agent"
    return RuntimeConfig(
        project_root=root,
        data_dir=data_dir,
        repo_root=root,
        duckdb_path=data_dir / "duckdb" / "codebrain.duckdb",
        kuzu_path=data_dir / "kuzu" / "graph.kuzu",
        lancedb_path=data_dir / "lancedb",
        manifest_path=data_dir / "manifests" / "current_manifest.json",
        scan_excluded_dirs=_load_scan_excluded_dirs(),
        review_analysis_provider=review_analysis_provider,
        review_analysis_model=os.environ.get("CODER_REVIEW_ANALYSIS_MODEL", "mistralai/devstral-small"),
        embedding_batch_size=_get_int_env("CODER_EMBED_BATCH_SIZE", 24),
        embedding_max_length=_get_int_env("CODER_EMBED_MAX_LENGTH", 512),
        embedding_device=os.environ.get("CODER_EMBED_DEVICE", "cuda").strip().lower() or "cuda",
        max_review_workers=_get_int_env("CODER_MAX_REVIEW_WORKERS", 3),
        max_concurrent_llm_reviews=_get_int_env("CODER_MAX_CONCURRENT_LLM_REVIEWS", 10),
        review_max_source_chars=_get_int_env("CODER_REVIEW_MAX_SOURCE_CHARS", 12000),
        review_max_chunks=_get_int_env("CODER_REVIEW_MAX_CHUNKS", 12),
        review_max_chunk_chars=_get_int_env("CODER_REVIEW_MAX_CHUNK_CHARS", 1200),
        review_max_symbols=_get_int_env("CODER_REVIEW_MAX_SYMBOLS", 40),
        review_max_graph_edges=_get_int_env("CODER_REVIEW_MAX_GRAPH_EDGES", 40),
        review_max_prior_findings=_get_int_env("CODER_REVIEW_MAX_PRIOR_FINDINGS", 12),
        review_group_size=_get_int_env("CODER_REVIEW_GROUP_SIZE", 4),
        review_group_max_source_chars=_get_int_env("CODER_REVIEW_GROUP_MAX_SOURCE_CHARS", 24000),
        review_run_legacy_heuristics_with_llm=_get_bool_env("CODER_REVIEW_RUN_LEGACY_HEURISTICS_WITH_LLM", False),
        openrouter_base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        openrouter_api_key=openrouter_api_key,
        openrouter_site_url=os.environ.get("OPENROUTER_SITE_URL", ""),
        openrouter_app_name=os.environ.get("OPENROUTER_APP_NAME", "Coder"),
    )
