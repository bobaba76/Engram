"""Git diff operations and diff text parsing for change detection."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

HUNK_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@", re.MULTILINE)


def _run_git(repo_root: Path, args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=15,
            stdin=subprocess.DEVNULL,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout


def _find_git_root(repo_root: Path) -> Path | None:
    """Search for a .git directory in repo_root, its parents, and immediate subdirectories.

    Handles cases where the indexed repo root is a wrapper directory and the
    actual git repo is nested inside (e.g. SalesDash/SalesDash/.git).
    """
    candidate = repo_root
    # Search upward from repo_root
    for _ in range(5):
        if (candidate / ".git").exists():
            return candidate
        if candidate.parent == candidate:
            break
        candidate = candidate.parent
    # Search immediate subdirectories (one level deep)
    try:
        for child in repo_root.iterdir():
            if child.is_dir() and (child / ".git").exists():
                return child
    except OSError:
        pass
    return None


def _git_top_level(repo_root: Path) -> Path:
    output = _run_git(repo_root, ["rev-parse", "--show-toplevel"]).strip()
    if output:
        return Path(output).resolve()
    # Fallback: search for .git in subdirectories or parents
    git_root = _find_git_root(repo_root)
    if git_root is not None:
        output = _run_git(git_root, ["rev-parse", "--show-toplevel"]).strip()
        if output:
            return Path(output).resolve()
    return repo_root


def _normalize_status_path(repo_root: Path, git_top: Path, path: str) -> str:
    direct = repo_root / path
    if direct.exists():
        return path
    from_top = git_top / path
    try:
        return str(from_top.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except ValueError:
        return path


def _untracked_files(repo_root: Path) -> list[str]:
    output = _run_git(repo_root, ["status", "--porcelain=v1", "-uall", "--"])
    files: list[str] = []
    git_top = _git_top_level(repo_root)
    for line in output.splitlines():
        if not line.startswith("?? "):
            continue
        path = line[3:].strip().strip('"').replace("\\", "/")
        if path:
            files.append(_normalize_status_path(repo_root, git_top, path))
    return sorted(dict.fromkeys(files))


def _synthetic_untracked_diff(repo_root: Path, files: list[str]) -> str:
    parts: list[str] = []
    for file_path in files:
        absolute = repo_root / file_path
        if not absolute.is_file():
            continue
        try:
            line_count = len(absolute.read_text(encoding="utf-8", errors="ignore").splitlines())
        except OSError:
            line_count = 1
        line_count = max(line_count, 1)
        parts.extend(
            [
                f"diff --git a/{file_path} b/{file_path}",
                "new file mode 100644",
                "index 0000000..0000000",
                "--- /dev/null",
                f"+++ b/{file_path}",
                f"@@ -0,0 +1,{line_count} @@",
            ]
        )
    return "\n".join(parts)


def _diff_output(repo_root: Path, scope: str, base_ref: str | None = None) -> str:
    normalized = scope if scope in {"unstaged", "staged", "all", "compare"} else "unstaged"
    # Resolve the actual git root — may differ from repo_root if repo_root
    # is a wrapper directory with a nested git repo.
    git_root = repo_root
    if not _run_git(repo_root, ["rev-parse", "--git-dir"]):
        discovered = _find_git_root(repo_root)
        if discovered is not None:
            git_root = discovered
    if normalized == "staged":
        return _run_git(git_root, ["diff", "--cached", "--unified=0", "--no-color"])
    if normalized == "all":
        staged = _run_git(git_root, ["diff", "--cached", "--unified=0", "--no-color"])
        unstaged = _run_git(git_root, ["diff", "--unified=0", "--no-color"])
        untracked = _synthetic_untracked_diff(repo_root, _untracked_files(git_root))
        return "\n".join(part for part in (staged, unstaged, untracked) if part.strip())
    if normalized == "compare":
        compare_ref = (base_ref or "HEAD").strip() or "HEAD"
        return _run_git(git_root, ["diff", f"{compare_ref}...HEAD", "--unified=0", "--no-color"])
    unstaged = _run_git(git_root, ["diff", "--unified=0", "--no-color"])
    untracked = _synthetic_untracked_diff(repo_root, _untracked_files(git_root))
    return "\n".join(part for part in (unstaged, untracked) if part.strip())


def _parse_changed_lines(diff_text: str) -> dict[str, set[int]]:
    changed: dict[str, set[int]] = {}
    current_file = ""
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
            changed.setdefault(current_file, set())
            continue
        if not current_file:
            continue
        match = HUNK_PATTERN.match(line)
        if match is None:
            continue
        start = int(match.group("start"))
        count = int(match.group("count") or "1")
        if count == 0:
            continue
        changed[current_file].update(range(start, start + count))
    return changed
