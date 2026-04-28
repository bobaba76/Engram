import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\michael\Documents\Github\Coder")

from config.settings import load_settings
from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore
from services.rename_service import preview_rename

settings = load_settings(Path(r"C:\Users\michael\Documents\Github\Stock"))
duck = DuckDBStore(settings.duckdb_path, read_only=True)
kuzu = KuzuStore(settings.kuzu_path)
out = preview_rename(
    settings.repo_root,
    duck,
    kuzu,
    symbol_name="Customers",
    new_name="CustomersPage",
    file_path="frontend/src/pages/Customers.tsx",
)

bad_examples = []
for edit in out.get("edits", []):
    text = edit.get("new_text", "")
    if (
        "CustomersPage with Gaps" in text
        or "Total CustomersPage" in text
        or '<Link to="/customers">CustomersPage</Link>' in text
        or '<Statistic title="CustomersPage"' in text
    ):
        bad_examples.append(text)

print(
    json.dumps(
        {
            "status": out.get("status"),
            "resolved_target": out.get("resolved_target"),
            "edit_count": len(out.get("edits", [])),
            "files": out.get("compact_summary", {}).get("files", []),
            "edits": out.get("edits", []),
            "bad_examples": bad_examples,
        },
        indent=2,
    )
)
