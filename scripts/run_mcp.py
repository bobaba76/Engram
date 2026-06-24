"""MCP server entry point — wires together session state, tool handlers, and server."""
from __future__ import annotations

import inspect
import io
import logging
import os
import sys
from functools import wraps
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# NOTE: On hybrid GPU laptops (AMD iGPU + NVIDIA dGPU), CUDA_VISIBLE_DEVICES=0
# must be set in the environment BEFORE the process starts (e.g. in MCP config
# env section). Setting it here via os.environ is too late — nvcuda.dll is
# already loaded by the time Python runs this line.

if sys.platform == "win32":
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import load_settings
from mcp_server.git_change_cache import fast_repo_root_for_tool
from mcp_server.mcp_session import MCPSession
from mcp_server.project_resolution import resolve_project_root
from mcp_server.server import MCPServer
from mcp_server.tool_handlers import TOOL_DEFINITIONS
from storage.manifest_store import ManifestStore


def _append_warning(payload: dict[str, Any], warning: str) -> None:
    warnings = payload.setdefault("warnings", [])
    if isinstance(warnings, list) and warning not in warnings:
        warnings.append(warning)
    compact_summary = payload.setdefault("compact_summary", {})
    if isinstance(compact_summary, dict):
        summary_warnings = compact_summary.setdefault("warnings", [])
        if isinstance(summary_warnings, list) and warning not in summary_warnings:
            summary_warnings.append(warning)


def _make_repo_safe_handler(session: MCPSession, handler: Any) -> Any:
    """Wrap a tool handler to inject repo metadata into the response payload."""
    signature = inspect.signature(handler)

    @wraps(handler)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        payload = handler(session, *args, **kwargs)
        if not isinstance(payload, dict):
            return payload
        if "repo" not in signature.parameters:
            return payload
        try:
            bound = signature.bind_partial(session, *args, **kwargs)
        except TypeError:
            bound = None
        repo_arg = ""
        if bound is not None:
            repo_arg = str(bound.arguments.get("repo") or "").strip()
        resolved_repo_root = fast_repo_root_for_tool(session.default_repo_root, repo_arg)
        payload.setdefault("repo_root", str(resolved_repo_root))
        payload.setdefault("repo_name", resolved_repo_root.name)
        selection_mode = "explicit_repo" if repo_arg else "default_repo_fallback"
        payload.setdefault(
            "repo_selection",
            {
                "mode": selection_mode,
                "requested_repo": repo_arg or None,
                "resolved_repo_root": str(resolved_repo_root),
                "resolved_repo_name": resolved_repo_root.name,
            },
        )
        compact_summary = payload.setdefault("compact_summary", {})
        if isinstance(compact_summary, dict):
            compact_summary.setdefault("repo_root", str(resolved_repo_root))
            compact_summary.setdefault("repo_name", resolved_repo_root.name)
            compact_summary.setdefault("repo_selection_mode", selection_mode)
        if not repo_arg:
            _append_warning(payload, f"No repo argument provided; used default repo '{resolved_repo_root.name}'. Pass the 'repo' argument explicitly to target a different repo.")
        return payload

    # Build a signature without the session parameter for MCP schema generation
    params = list(signature.parameters.values())[1:]  # drop session
    wrapped.__signature__ = signature.replace(parameters=params)
    return wrapped


def _check_stale_pid(settings: Any) -> None:
    pid_file = settings.data_dir / "mcp_server.pid"
    try:
        if pid_file.exists():
            old_pid_str = pid_file.read_text().strip()
            if old_pid_str.isdigit():
                old_pid = int(old_pid_str)
                try:
                    import os as _os
                    _os.kill(old_pid, 0)
                    logger.warning(
                        "Another MCP server (PID %d) appears to be running. "
                        "This may cause database lock conflicts. "
                        "Kill it if tools hang: Stop-Process -Id %d -Force",
                        old_pid, old_pid,
                    )
                except (ProcessLookupError, PermissionError, OSError):
                    pass
    except Exception:
        logger.debug("PID guard check failed", exc_info=True)
    try:
        import os as _os
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(_os.getpid()))
    except Exception:
        logger.debug("Failed to write PID file", exc_info=True)


def main() -> int:
    # Set up file logging so crashes are captured even when stdio transport dies
    log_dir = Path(__file__).resolve().parent.parent / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(str(log_dir / "mcp_server.log"), encoding="utf-8"),
        ],
    )

    project_root, resolved_by = resolve_project_root()
    settings = load_settings(project_root)
    _check_stale_pid(settings)
    manifest_store = ManifestStore(settings.manifest_path)
    manifest = manifest_store.read_current()
    manifest.setdefault("mcp_resolved_repo_root", str(settings.repo_root))
    manifest.setdefault("mcp_resolution_source", resolved_by)

    session = MCPSession(settings, manifest, resolved_by)
    server = MCPServer()

    # Eagerly load torch/transformers on the main thread BEFORE starting the
    # prewarm daemon thread.  The `import torch` call inside the daemon thread
    # holds the GIL for several seconds and freezes the MCP event loop.  By
    # importing here (before server.run()), the import completes synchronously
    # at startup with no event loop to block.  The daemon thread then finds
    # torch already imported and proceeds to load the model without GIL contention.
    try:
        from indexing.embeddings import _load_embedding_dependencies, prewarm_jina_model
        _load_embedding_dependencies()
        prewarm_jina_model(settings.embedding_model, device=settings.embedding_device)
    except Exception:
        logger.debug("Startup prewarm failed", exc_info=True)

    for tool_name, handler, description in TOOL_DEFINITIONS:
        server.register_tool(tool_name, _make_repo_safe_handler(session, handler), description=description)

    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
