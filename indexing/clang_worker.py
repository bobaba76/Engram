from __future__ import annotations

import json
import sys
from pathlib import Path

from indexing.clang_extractor import _extract_clang_symbols_in_process, _symbol_to_dict


def main() -> int:
    if len(sys.argv) < 2:
        sys.stdout.write(json.dumps({"symbols": [], "error": "missing file path"}))
        return 2
    file_path = Path(sys.argv[1]).resolve()
    try:
        symbols = _extract_clang_symbols_in_process(file_path)
    except Exception as exc:
        sys.stdout.write(json.dumps({"symbols": [], "error": str(exc)}))
        return 1
    sys.stdout.write(json.dumps({"symbols": [_symbol_to_dict(symbol) for symbol in symbols]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
