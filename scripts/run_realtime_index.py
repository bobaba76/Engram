from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.realtime_index_service import WatchdogRealtimeIndexer


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch a repository and run safe incremental Coder indexing after changes settle.")
    parser.add_argument("repo_root", nargs="?", default=str(ROOT), help="Repository root to watch.")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Polling/status loop interval in seconds.")
    parser.add_argument("--debounce", type=float, default=2.0, help="Seconds to wait after the last change before indexing.")
    parser.add_argument("--status-interval", type=float, default=30.0, help="Seconds between watcher status messages.")
    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve()
    indexer = WatchdogRealtimeIndexer(
        repo_root=repo_root,
        coder_root=ROOT,
        poll_interval_seconds=args.poll_interval,
        debounce_seconds=args.debounce,
        status_interval_seconds=args.status_interval,
    )
    print(f"[realtime-index] watching {repo_root}; debounce={args.debounce:g}s", flush=True)
    indexer.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
