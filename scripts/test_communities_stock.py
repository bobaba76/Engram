"""Quick test of detect_communities on the Stock repo."""
import time
from pathlib import Path
from config.settings import load_settings
from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore

s = load_settings(Path(r"C:\Users\michael\Documents\Github\Stock"))
print(f"kuzu: {s.kuzu_path}")
print(f"duckdb: {s.duckdb_path}")

db = DuckDBStore(s.duckdb_path, read_only=True)
k = KuzuStore(s.kuzu_path, read_only=True)
print("Stores opened OK")

# Test individual phases
from services.community_detection_service import _build_adjacency, _label_propagation, _batch_symbol_info, _name_community, _compute_cohesion
from collections import defaultdict

t0 = time.time()
adj = _build_adjacency(k)
t1 = time.time()
print(f"Phase 1 - Adjacency: {len(adj)} nodes, {t1-t0:.2f}s")

nodes = sorted(adj.keys())
labels = _label_propagation(adj, nodes)
t2 = time.time()
print(f"Phase 2 - Label propagation: {t2-t1:.2f}s")

# Group by label
communities_raw = defaultdict(list)
for node, label in labels.items():
    communities_raw[label].append(node)

communities = [sorted(members) for members in communities_raw.values() if len(members) >= 3]
print(f"Raw communities (size>=3): {len(communities)}")

# Batch fetch symbol info
all_members = [sym for members in communities for sym in members]
t3 = time.time()
symbol_info = _batch_symbol_info(db, all_members)
t4 = time.time()
print(f"Phase 3 - Batch symbol info: {len(symbol_info)} lookups, {t4-t3:.2f}s")

# Name communities
for idx, members in enumerate(sorted(communities, key=len, reverse=True)[:5]):
    name, kinds = _name_community(members, symbol_info)
    cohesion = _compute_cohesion(members, adj)
    print(f"  community_{idx:03d}: {name} ({len(members)} symbols, cohesion={cohesion})")

print(f"\nTotal: {time.time()-t0:.2f}s")
k.close()
db.close()
