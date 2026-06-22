from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import os
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)


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


def _is_in_executor() -> bool:
    """Check if the current thread belongs to _GRAPH_TIMEOUT_EXECUTOR."""
    return threading.current_thread().name.startswith("coder-graph-timeout")


def run_with_timeout(
    operation: Callable[[], T],
    timeout_seconds: float,
    default: T,
    warnings: list[str] | None = None,
    label: str = "Operation",
    catch_exceptions: bool = True,
) -> T:
    # If we're already running inside the executor, run directly.
    # This prevents thread-pool exhaustion deadlocks when nested
    # run_with_timeout calls compete for the same limited worker pool.
    # The outer timeout still protects the overall operation.
    if _is_in_executor():
        try:
            return operation()
        except Exception:
            if catch_exceptions:
                logger.warning("run_with_timeout (inline): %s raised an exception", label, exc_info=True)
                return default
            raise

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
            logger.warning("run_with_timeout: %s raised an exception", label, exc_info=True)
            return default
        raise
