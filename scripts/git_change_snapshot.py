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
    payload = {
        "repo_root": str(repo_root),
        "scope": normalized,
        "base_ref": args.base_ref or "",
        "created_at": time.time(),
        "diff_text": diff_text,
        "warnings": warnings,
    }
    temp = output.with_suffix(output.suffix + ".tmp")
    temp.write_text(json.dumps(payload), encoding="utf-8")
    temp.replace(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
