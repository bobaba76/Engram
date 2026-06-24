"""Quick timing test for detect_communities to find the hang point."""
import sys
import time
sys.path.insert(0, r"C:\Users\michael\Documents\Github\Coder")

from config.settings import load_settings
from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore
from services.community_detection_service import (
    _build_adjacency,
    _label_propagation,
    _batch_symbol_info,
    _name_community,
    _compute_cohesion,
    _store_communities,
    _split_community,
)
from collections import defaultdict

from pathlib import Path
repo_root = Path(r"C:\Users\michael\Documents\Github\Stock")
settings = load_settings(repo_root)

print("Opening stores...")
duckdb = DuckDBStore(settings.duckdb_path, read_only=False)
kuzu = KuzuStore(settings.kuzu_path)

t0 = time.time()
print("Phase 1: Building adjacency...")
adjacency = _build_adjacency(kuzu)
nodes = sorted(adjacency.keys())
print(f"  Done: {len(nodes)} nodes in {time.time()-t0:.2f}s")

t1 = time.time()
print("Phase 2: Label propagation...")
labels = _label_propagation(adjacency, nodes)
print(f"  Done in {time.time()-t1:.2f}s")

communities_raw = defaultdict(list)
for node, label in labels.items():
    communities_raw[label].append(node)

communities = []
for members in communities_raw.values():
    if len(members) >= 3:
        if len(members) > 200:
            communities.extend(_split_community(members, adjacency, 200, 3))
        else:
            communities.append(sorted(members))
# Also accept communities between 200-500 that LP couldn't split further
print(f"  {len(communities)} communities after filtering")

t2 = time.time()
print("Phase 3: Batch symbol info...")
all_members = [sym for members in communities for sym in members]
print(f"  Fetching info for {len(all_members)} symbols...")
symbol_info = _batch_symbol_info(duckdb, all_members)
print(f"  Done in {time.time()-t2:.2f}s, got {len(symbol_info)} entries")

t3 = time.time()
print("Phase 4: Naming communities...")
for idx, members in enumerate(sorted(communities, key=len, reverse=True)):
    name, top_kinds = _name_community(members, symbol_info)
    cohesion = _compute_cohesion(members, adjacency)
    if idx < 10:
        print(f"  community_{idx:03d}: {name} ({len(members)} symbols, cohesion={cohesion})")
print(f"  Done in {time.time()-t3:.2f}s")

t4 = time.time()
print("Phase 5: Building records...")
community_records = []
for idx, members in enumerate(sorted(communities, key=len, reverse=True)):
    community_id = f"community_{idx:03d}"
    name, top_kinds = _name_community(members, symbol_info)
    cohesion = _compute_cohesion(members, adjacency)
    file_paths_set = set()
    for qn in members:
        info = symbol_info.get(qn)
        if info and info[0]:
            file_paths_set.add(info[0])
    community_records.append({
        "community_id": community_id,
        "name": name,
        "symbol_count": len(members),
        "file_count": len(sorted(file_paths_set)),
        "cohesion": cohesion,
        "top_kinds": top_kinds,
        "members": members,
        "file_paths": sorted(file_paths_set)[:30],
    })
print(f"  Done in {time.time()-t4:.2f}s")

t5 = time.time()
print("Phase 6: Storing to DuckDB...")
stored = _store_communities(duckdb, community_records)
print(f"  stored={stored} in {time.time()-t5:.2f}s")

print(f"\nTotal: {time.time()-t0:.2f}s")
