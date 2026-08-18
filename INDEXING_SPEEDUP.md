# Coder Indexing Speedup — Handoff for Devin

Task: make Coder's `run_index.py` full-index significantly faster. Baseline (SalesDash, 2026-08-16, run `c4ffb0fe`): **17.8 min total** — graph 392.7s (37%), embed 228.8s, review 301.6s, process 99.3s, parse 44s. hermes-agent first build is projected at 2.5–4h today; target ≈45–75 min.

## Already implemented in the working tree (WIP branch, uncommitted) — review + finish

### 1. Kuzu bulk inserts (BIGGEST lever, done, verified)
- `indexing/graph_builder.py` — hot loop now collects nodes/edges in-memory instead of per-edge kuzu calls; flushed at the end.
- `storage/kuzu_store.py` — new `bulk_ensure_nodes()` + `bulk_add_edges()` using `UNWIND $rows ... CREATE`, ~10k-row chunks.
- Verification: `python "C:/Users/michael/Documents/Hermes/Hermes projects/coder-index/smoke_graph_bulk.py"` — **24/24 PASS** (counts, dedupe, synthetic property/field/route nodes, confidence values, auto-created OWNS rel table, coordinator-style DETACH DELETE rebuild).
- Measured on a spike: 2.15ms → 0.196ms per edge = **11x**. Expected: graph stage 392.7s → 20–60s.
- Side benefit: auto-creates missing `OWNS`/`HAS_COMPONENT` rel tables (latent schema bug — `_initialize_schema` never created them; those edges were silently dropped).

**CRITICAL GOTCHA (spike-proven):** kuzu does NOT enforce the rel-table PK under `UNWIND CREATE` — 50,001 rows produced 52,002 edges. Python-side dedupe is mandatory and is implemented (mirrors the old "duplicate edge skipped" semantics). Full runs reset the DB; incremental runs DETACH DELETE changed+impacted nodes first (`app/coordinator.py:257`), so CREATE cannot conflict — but never call `bulk_add_edges` twice on the same data without deleting first.

### What remains before it ships
- Run the smoke test yourself (command above); if it's still green, do a **full SalesDash re-index** and compare per-stage timings vs the baseline log at `C:/Users/michael/Documents/Hermes/Hermes projects/coder-index/logs/salesdash_baseline_*.log` (graph 392.7s / 116,747 edges / 1,277 processes).
- Re-run `git diff -w` — check nothing else in the file changed (there is unrelated WIP in the tree; don't commit those together).
- Note: the repo is **CRLF** — do NOT run blanket LF normalization (it blank-line-doubled `kuzu_store.py` once; file was repaired via SequenceMatcher vs HEAD).

## Remaining levers (priority order)

### 2. Drop double tokenization (`indexing/embeddings.py`)
`_token_aware_batches` (line ~155) calls `estimate_tokens(text, tokenizer=...)` on every chunk — that's a full tokenizer encode per chunk, and the same text is encoded AGAIN in the main loop (line ~362). Replace the per-chunk estimate with a cheap heuristic (`len(text) // 4` is fine) and keep the real encode. ~5–15% of embed time. Tiny, safe.

### 3. Preserve the embedding cache across full rebuilds (`storage/vector_store.py`)
`reset()` wipes the hash→vector cache (`_clear_embedding_cache`) along with the chunks table. Full rebuilds re-embed everything even when content is unchanged. Keep the cache, wipe only chunks. 2–4x cheaper rebuilds; 0 cache hits were seen in the baseline (7,357 new embeddings for 8,338 chunks).

### 4. Embed pipelining (`indexing/embeddings.py` line ~338+)
The loop is strictly serial: tokenize → `.to(device)` → forward → `.cpu().tolist()` → next. Double-buffer (tokenize next batch while GPU is busy) and raise batch 24 → 40–48 fp16 (4 GB card, `CODER_EMBED_DEVICE=cuda`). In-pipeline rate was ~32 chunks/s vs raw 49–158 — 1.5–2x embed stage.

### 5. Overlap stages (`app/coordinator.py`)
Run embed (GPU) in parallel with process+review (CPU-only stages). ~30–45% wall-time cut. Most invasive; do last.

## Environment facts
- Standalone Python (no PYTHONPATH poison): `env -u PYTHONPATH C:/Users/michael/AppData/Local/Programs/Python/Python311/python.exe`
- Offline/GPU-hardened index env: `CUDA_VISIBLE_DEVICES=0 CODER_EMBED_DEVICE=cuda HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`
- Script bypass: `C:/Users/michael/Documents/Github/Coder/scripts/run_index.py <root> full|incremental`
- Do NOT run index jobs while LongMemEval eval/embedding jobs are in flight (user's rule).

## Review stage (user question)
`CODER_REVIEW_ENABLED=false` disables the review stage entirely (read at `config/settings.py:115`, honored at `app/coordinator.py:604`). `CODER_PROCESS_EXTRACTION_ENABLED=false` likewise disables process extraction. Note: review already runs heuristic-only today (`CODER_LLM_FEATURES_ENABLED=false` default, no OPENROUTER key in the MCP env) — it costs 301.6s (28% of the run) purely for heuristic agent analyses.
