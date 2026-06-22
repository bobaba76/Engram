from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path


VALID_SCOPES = {"unstaged", "staged", "all", "compare"}


def _run_git(repo_root: Path, args: list[str], timeout: int) -> tuple[str, str, int]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return "", f"git {' '.join(args)} timed out after {timeout}s", 124
    except OSError as exc:
        return "", f"git {' '.join(args)} failed: {exc}", 127
    return completed.stdout, completed.stderr, completed.returncode


def _diff(repo_root: Path, scope: str, base_ref: str, timeout: int) -> tuple[str, list[str]]:
    warnings: list[str] = []
    normalized = scope if scope in VALID_SCOPES else "unstaged"
    commands: list[list[str]]
    if normalized == "staged":
        commands = [["diff", "--cached", "--unified=0", "--no-color"]]
    elif normalized == "all":
        commands = [
            ["diff", "--cached", "--unified=0", "--no-color"],
            ["diff", "--unified=0", "--no-color"],
        ]
    elif normalized == "compare":
        compare_ref = (base_ref or "HEAD").strip() or "HEAD"
        commands = [["diff", f"{compare_ref}...HEAD", "--unified=0", "--no-color"]]
    else:
        commands = [["diff", "--unified=0", "--no-color"]]

    parts: list[str] = []
    for command in commands:
        stdout, stderr, returncode = _run_git(repo_root, command, timeout)
        if returncode != 0:
            warning = stderr.strip() or stdout.strip() or f"git {' '.join(command)} exited {returncode}"
            warnings.append(warning[:500])
            continue
        if stdout.strip():
            parts.append(stdout)
    return "\n".join(parts), warnings


def _git_top_level(repo_root: Path, timeout: int) -> Path:
    stdout, _, returncode = _run_git(repo_root, ["rev-parse", "--show-toplevel"], timeout)
    if returncode != 0 or not stdout.strip():
        return repo_root
    return Path(stdout.strip()).resolve()


def _normalize_status_path(repo_root: Path, git_top: Path, path: str) -> str:
    direct = repo_root / path
    if direct.exists():
        return path
    from_top = git_top / path
    try:
        return str(from_top.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except ValueError:
        return path


def _untracked_files(repo_root: Path, timeout: int) -> tuple[list[str], list[str]]:
    stdout, stderr, returncode = _run_git(repo_root, ["status", "--porcelain=v1", "-uall", "--"], timeout)
    if returncode != 0:
        warning = stderr.strip() or stdout.strip() or f"git status exited {returncode}"
        return [], [warning[:500]]
    files: list[str] = []
    git_top = _git_top_level(repo_root, timeout)
    for line in stdout.splitlines():
        if not line.startswith("?? "):
            continue
        path = line[3:].strip().strip('"').replace("\\", "/")
        if path:
            files.append(_normalize_status_path(repo_root, git_top, path))
    return sorted(dict.fromkeys(files)), []


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--scope", default="unstaged")
    parser.add_argument("--base-ref", default="")
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    normalized = args.scope if args.scope in VALID_SCOPES else "unstaged"
    diff_text, warnings = _diff(repo_root, normalized, args.base_ref, args.timeout)
    untracked_files: list[str] = []
    if normalized in {"unstaged", "all"}:
        untracked_files, status_warnings = _untracked_files(repo_root, args.timeout)
        warnings.extend(status_warnings)
        untracked_diff = _synthetic_untracked_diff(repo_root, untracked_files)
        if untracked_diff:
            diff_text = "\n".join(part for part in (diff_text, untracked_diff) if part.strip())
    payload = {
        "repo_root": str(repo_root),
        "scope": normalized,
        "base_ref": args.base_ref or "",
        "created_at": time.time(),
        "diff_text": diff_text,
        "untracked_files": untracked_files,
        "warnings": warnings,
    }
    temp = output.with_suffix(output.suffix + ".tmp")
    temp.write_text(json.dumps(payload), encoding="utf-8")
    temp.replace(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
