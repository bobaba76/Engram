"""Debug the split logic for the mega-cluster."""
import sys
import time
sys.path.insert(0, r"C:\Users\michael\Documents\Github\Coder")

from pathlib import Path
from config.settings import load_settings
from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore
from services.community_detection_service import (
    _build_adjacency,
    _label_propagation,
    _compute_cohesion,
    _bisect_community,
    _bfs_distances,
    _split_community,
)
from collections import defaultdict

repo_root = Path(r"C:\Users\michael\Documents\Github\Stock")
settings = load_settings(repo_root)

print("Opening stores...")
duckdb = DuckDBStore(settings.duckdb_path, read_only=False)
kuzu = KuzuStore(settings.kuzu_path)

print("Building adjacency...")
adjacency = _build_adjacency(kuzu)
nodes = sorted(adjacency.keys())
print(f"  {len(nodes)} nodes")

print("Running LP...")
labels = _label_propagation(adjacency, nodes)
communities_raw = defaultdict(list)
for node, label in labels.items():
    communities_raw[label].append(node)

# Find the mega-cluster
mega = max(communities_raw.values(), key=len)
print(f"\nMega-cluster: {len(mega)} symbols")

# Run _split_community on it
print("\nRunning _split_community...")
result = _split_community(mega, adjacency, 200, 3)
print(f"  Produced {len(result)} sub-communities")
for i, r in enumerate(sorted(result, key=len, reverse=True)[:10]):
    coh = _compute_cohesion(r, adjacency)
    print(f"  sub_{i}: {len(r)} symbols, cohesion={coh:.3f}")
