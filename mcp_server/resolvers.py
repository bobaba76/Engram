from pathlib import Path


def resolve_target(target: str, repo_root: Path) -> str:
    candidate = repo_root / target
    if candidate.exists():
        return str(candidate.relative_to(repo_root)).replace("\\", "/")
    return target
