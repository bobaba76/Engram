from __future__ import annotations

from pathlib import Path

from storage.manifest_store import ManifestStore


MANIFEST_RELATIVE_PATH = Path("data") / "manifests" / "current_manifest.json"
MAX_NESTED_REPO_DEPTH = 3
MAX_PARENT_SIBLING_DEPTH = 2


def _read_manifest(repo_root: Path) -> dict[str, object]:
    return ManifestStore(repo_root / MANIFEST_RELATIVE_PATH).read_current()


def _has_manifest(repo_root: Path) -> bool:
    return (repo_root / MANIFEST_RELATIVE_PATH).exists()


def _iter_nested_indexed_roots(root: Path, *, max_depth: int = MAX_NESTED_REPO_DEPTH):
    root = root.resolve()
    stack: list[tuple[Path, int]] = [(root, 0)]
    seen: set[Path] = {root}
    while stack:
        current, depth = stack.pop()
        if depth >= max_depth:
            continue
        try:
            children = sorted(current.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or child.name.startswith(".") or child.name in {"data", "node_modules", "__pycache__"}:
                continue
            resolved = child.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if _has_manifest(resolved):
                yield resolved
            stack.append((resolved, depth + 1))


def _iter_indexed_repo_roots(active_repo_root: Path):
    resolved_root = active_repo_root.resolve()
    seen: set[Path] = set()
    yield resolved_root
    seen.add(resolved_root)
    for nested in _iter_nested_indexed_roots(resolved_root):
        if nested not in seen:
            seen.add(nested)
            yield nested
    parent = resolved_root.parent
    for child in sorted(parent.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir() or child.resolve() == resolved_root:
            continue
        if child.name.startswith(".") or child.name in {"data", "node_modules", "__pycache__"}:
            continue
        manifest = _read_manifest(child)
        if not manifest:
            continue
        child_root = child.resolve()
        if child_root not in seen:
            seen.add(child_root)
            yield child_root
        for nested in _iter_nested_indexed_roots(child_root, max_depth=MAX_PARENT_SIBLING_DEPTH):
            if nested not in seen:
                seen.add(nested)
                yield nested


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
