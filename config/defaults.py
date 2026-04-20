from pathlib import Path


DEFAULT_DATA_DIRNAME = "data"
DEFAULT_LOG_DIRNAME = "logs"
DEFAULT_DUCKDB_FILENAME = "codebrain.duckdb"
DEFAULT_MANIFEST_FILENAME = "current_manifest.json"


def project_root_from_file(file_path: str) -> Path:
    return Path(file_path).resolve().parent.parent
