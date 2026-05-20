from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import os
from typing import Callable, TypeVar


T = TypeVar("T")


def _env_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return max(1, value)


_GRAPH_TIMEOUT_EXECUTOR = ThreadPoolExecutor(
    max_workers=_env_int("CODER_GRAPH_TIMEOUT_WORKERS", 4),
    thread_name_prefix="coder-graph-timeout",
)


def run_with_timeout(
    operation: Callable[[], T],
    timeout_seconds: float,
    default: T,
    warnings: list[str] | None = None,
    label: str = "Operation",
    catch_exceptions: bool = True,
) -> T:
    future = _GRAPH_TIMEOUT_EXECUTOR.submit(operation)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError:
        future.cancel()
        if warnings is not None:
            warnings.append(f"{label} timed out after {timeout_seconds:.1f}s and was skipped.")
        return default
    except Exception:
        if catch_exceptions:
            return default
        raise
