from __future__ import annotations

from pathlib import Path

from storage.manifest_store import ManifestStore


MANIFEST_RELATIVE_PATH = Path("data") / "manifests" / "current_manifest.json"


def _read_manifest(repo_root: Path) -> dict[str, object]:
    return ManifestStore(repo_root / MANIFEST_RELATIVE_PATH).read_current()


def _iter_indexed_repo_roots(active_repo_root: Path):
    resolved_root = active_repo_root.resolve()
    yield resolved_root
    parent = resolved_root.parent
    for child in sorted(parent.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir() or child.resolve() == resolved_root:
            continue
        manifest = _read_manifest(child)
        if not manifest:
            continue
        yield child.resolve()


def _repo_payload(repo_root: Path, manifest: dict[str, object]) -> dict[str, object]:
    manifest_path = repo_root / MANIFEST_RELATIVE_PATH
    return {
        "name": repo_root.name,
        "path": str(repo_root.resolve()),
        "indexed_at": manifest_path.stat().st_mtime if manifest_path.exists() else None,
        "status": manifest.get("status", "missing"),
        "run_id": manifest.get("run_id", ""),
        "counts": manifest.get("counts", {}),
        "versions": manifest.get("versions", {}),
        "manifest": manifest,
        "is_active": False,
    }


def resolve_indexed_repo(active_repo_root: Path, repo: str | Path | None = None) -> Path:
    resolved_root = active_repo_root.resolve()
    requested = str(repo or "").strip()
    if not requested:
        return resolved_root
    requested_path = Path(requested).expanduser()
    candidate_paths: list[Path] = []
    if requested_path.is_absolute():
        candidate_paths.append(requested_path.resolve())
    else:
        candidate_paths.append((resolved_root.parent / requested_path).resolve())
        candidate_paths.append((resolved_root / requested_path).resolve())
    requested_name = requested_path.name.lower()
    for repo_root in _iter_indexed_repo_roots(resolved_root):
        if repo_root in candidate_paths:
            return repo_root
        if repo_root.name.lower() == requested.lower() or repo_root.name.lower() == requested_name:
            return repo_root
        try:
            relative_to_parent = repo_root.relative_to(resolved_root.parent).as_posix().lower()
            if relative_to_parent == requested.replace("\\", "/").lower():
                return repo_root
        except ValueError:
            pass
    raise ValueError(f"Unknown indexed repo: {requested}")


def list_indexed_repos(active_repo_root: Path) -> dict[str, object]:
    repos: list[dict[str, object]] = []
    resolved_root = active_repo_root.resolve()
    active_manifest = _read_manifest(resolved_root)
    if active_manifest:
        active_repo = _repo_payload(resolved_root, active_manifest)
        active_repo["is_active"] = True
        repos.append(active_repo)
    for child in _iter_indexed_repo_roots(resolved_root):
        if child == resolved_root:
            continue
        manifest = _read_manifest(child)
        repos.append(_repo_payload(child, manifest))
    return {
        "root": str(resolved_root),
        "active_repo": str(resolved_root),
        "repo_count": len(repos),
        "repos": repos,
        "compact_summary": {
            "target": str(resolved_root),
            "repo_count": len(repos),
            "active_repo": resolved_root.name,
            "top_repos": [repo["name"] for repo in repos[:8]],
        },
    }
