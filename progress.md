# Engram (Coder) — Improvement Progress Tracker

## High Priority

- [x] **Fix 1: Replace silent `except: pass` with logged warnings** — across `embeddings.py`, `semantic_search.py`, `feature_context_service.py`, `index_health_service.py`, `test_intelligence_service.py`, `route_map_service.py`, `rename_service.py`, `route_parsing.py`, `parsers/common.py`, `clang_extractor.py`, `native_build_context.py`, `kuzu_store.py`, `vector_store.py`, `investigation_service.py`, `timeout_utils.py`
- [x] **Fix 2: Add embedding dimension guard in VectorStore** — warn when fallback (≤64-dim) embeddings are inserted
- [x] **Fix 3: Default `embedding_device` to `"auto"`** — in `config_models.py` and `settings.py`
- [x] **Fix 4: Add config validation in `RuntimeConfig.__post_init__`** — validates batch sizes, device, provider, etc.
- [x] **Fix 5: Add logging to `_load_jina_model` failure path** — in `embeddings.py`

## Medium Priority

- [x] **Fix 6: Surface GPU fallback warning at index time** — in `coordinator.py`
- [x] **Fix 7: Remove dead in-memory `items` list in `VectorStore`** — clean up dual-mode code
- [x] **Fix 8: Make `process_builder` `next_nodes` truncation configurable** — via `max_branches` param
- [x] **Fix 9: Fix `module_tags == community_tags` in `process_builder`** — community_tags now derived from normalized symbol names
- [x] **Fix 10: Add `LazyKuzuStore.__getattr__`** — forwards all methods dynamically
- [x] **Fix 11: Add structured error response in `enrich_payload`** — wraps handler in try/except, returns error payload
- [x] **Fix 12: Add incremental embedding skip for unchanged chunks** — skips chunks with matching content_hash in incremental mode

## Low Priority

- [x] **Fix 13: Add `.env.example` template** — updated device default to `auto`
- [x] **Fix 14: Add `pyproject.toml`** — with ruff, mypy, pytest configs
- [x] **Fix 15: Add CI workflow** — `.github/workflows/ci.yml` with lint and test jobs
- [x] **Fix 16: Add `__pycache__` to `.gitignore`** — already present
- [x] **Fix 17: Improve schema handling for `Optional` types** — added nullable support in `schema.py`
- [x] **Fix 18: Add Kuzu edge deduplication** — distinguish duplicate edges (debug) from real errors (warning)
- [x] **Fix 19: Add parallel parsing with `ProcessPoolExecutor`** — in `coordinator.py`, up to 8 workers, falls back to sequential for single file
- [x] **Fix 20: Mask API keys in config serialization** — added `safe_dict()` to `RuntimeConfig`
- [x] **Fix 21: Add input sanitization for graph queries** — blocked dangerous Cypher operations
- [x] **Fix 22: Add pipeline integration test** — `tests/test_pipeline_integration.py` (scan→parse→chunk→embed→graph)
- [x] **Fix 23: Add tests for `embeddings.py`** — `tests/test_embeddings.py` (19 tests, all passing)
- [x] **Fix 24: Add tests for `connection_manager.py`** — `tests/test_connection_manager.py` (thread safety, read-only, concurrent)
- [x] **Fix 25: Decompose `run_mcp.py`** — split 1261-line monolith into `git_change_cache.py` (224), `project_resolution.py` (101), `mcp_session.py` (321), `tool_handlers.py` (669), slim `run_mcp.py` (106)
- [x] **Fix 26: Decompose `investigation_service.py`** — split 2255-line monolith into `investigation_constants.py` (126), `investigation_question_analysis.py` (491), `investigation_discovery.py` (275), `investigation_ranking.py` (575), `investigation_guidance.py` (354), slim `investigation_service.py` facade (559)

## Improvement: Embedding Model Loading & No Silent Fallback

- [x] **Fix prewarm double-load bug** — `prewarm_jina_model` was calling `_load_jina_model` twice (once to load, once to get reference for `.to(device)`); now loads once and moves to device in the same call
- [x] **Add `wait_for_model(timeout)`** — blocks until the model is ready or timeout, so callers don't need to poll `is_model_ready` or tell users to "retry in a few seconds"
- [x] **Remove silent fallback in `embed_texts`** — now raises `EmbeddingNotReadyError` by default instead of silently returning hash-based embeddings; `allow_fallback=True` opts back into fallback for tests
- [x] **Add half-precision loading** — `_load_jina_model` now uses `torch.float16` on CUDA/MPS devices to reduce memory and speed up loading
- [x] **Update `semantic_code_search_tool`** — waits up to 15s for model, adds `degraded: true` and `missing_capabilities: ["vector_search"]` to response for LLM consumption
- [x] **Update `coordinator.py` indexing** — prewarms and waits up to 60s for model before embedding; raises `RuntimeError` if model fails to load (no silent fallback during indexing)
- [x] **Update `semantic_search.py`** — wraps `provider.embed` in try/except to gracefully skip vector search on error
- [x] **Add 3 new tests** — `test_embed_texts_raises_when_model_not_ready`, `test_embed_texts_fallback_when_allowed`, `test_embed_texts_raises_for_non_jina_without_fallback` (22 total, all passing)
