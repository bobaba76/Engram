from models.entity_models import FileRecord


def plan_incremental_work(files: list[FileRecord], existing_files: dict[str, dict[str, object]] | None = None) -> dict[str, list[str] | int]:
    existing_files = existing_files or {}
    file_paths = [file_record.path for file_record in files]
    changed_files = [
        file_record.path
        for file_record in files
        if existing_files.get(file_record.path, {}).get("sha256") != file_record.sha256
    ]
    deleted_files = sorted(path for path in existing_files if path not in set(file_paths))
    return {
        "files_to_parse": changed_files,
        "files_to_review": changed_files,
        "deleted_files": deleted_files,
        "unchanged_files": [path for path in file_paths if path not in set(changed_files)],
        "file_count": len(file_paths),
    }
