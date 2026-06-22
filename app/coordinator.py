from __future__ import annotations
 
import json
import logging
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from time import time
from uuid import uuid4
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from typing import Any

logger = logging.getLogger(__name__)
 
from app.run_modes import FULL, INCREMENTAL
from indexing.chunker import build_chunks, diff_chunk_ids, summarize_chunks
from indexing.embedder import embed_chunks
from indexing.embedding_providers import EmbeddingRequest, embedding_runtime_info
from indexing.embeddings import prewarm_jina_model, wait_for_model
from indexing.graph_builder import build_graph
from indexing.process_builder import build_process_graph_records
from indexing.planner import plan_incremental_work
from indexing.scanner import scan_repo
from indexing.symbol_extractor import extract_symbols_with_status
from models.entity_models import SymbolRecord
from models.config_models import RuntimeConfig
from models.review_models import ReviewAgentAnalysis, ReviewFinding, ReviewObservation, ReviewResult
from models.stage_models import RunSummary, StageResult
from reviewers.aggregator import merge_findings, synthesize_findings_from_agent_analyses
from reviewers.context import build_review_context
from reviewers.execution import ReviewExecutionPolicy, run_review_jobs
from reviewers.general_reviewer import GeneralReviewer
from reviewers.logic_reviewer import LogicReviewer
from reviewers.maintainability_reviewer import MaintainabilityReviewer
from reviewers.providers import build_review_analysis_provider
from reviewers.scheduler import build_review_jobs
from reviewers.security_reviewer import SecurityReviewer
from services.agents_file_service import update_agents_file
from services.run_summary_service import generate_run_summary, write_run_reports
from services.index_pipeline_stages import persist_chunk_records, persist_parse_records
from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore
from storage.manifest_store import ManifestStore
from storage.vector_store import VectorStore
 
 
def _parse_file_worker(file_path: Path) -> tuple[str, list[dict[str, object]], dict[str, object]]:
    """Module-level worker for ProcessPoolExecutor — must be picklable."""
    from indexing.symbol_extractor import extract_symbols_with_status
    from dataclasses import asdict
    symbols, parse_status = extract_symbols_with_status(file_path)
    symbol_dicts = [asdict(s) for s in symbols]
    return str(file_path), symbol_dicts, parse_status


def _build_repo_profile(files) -> dict[str, object]:
    top_level_dirs = sorted({Path(file_record.path).parts[0] for file_record in files if Path(file_record.path).parts})
    top_level_file_counts: dict[str, int] = {}
    for file_record in files:
        parts = Path(file_record.path).parts
        if not parts:
            continue
        root = parts[0]
        top_level_file_counts[root] = top_level_file_counts.get(root, 0) + 1
    sample_paths = [file_record.path for file_record in files[:12]]
    return {
        "top_level_dirs": top_level_dirs,
        "top_level_file_counts": top_level_file_counts,
        "sample_paths": sample_paths,
        "has_frontend": "frontend" in top_level_dirs,
        "has_backend": "backend" in top_level_dirs,
        "has_electron": "electron" in top_level_dirs,
        "has_desktop_scripts": any(path.endswith(".bat") for path in sample_paths) or any(
            file_record.path.endswith(".bat") for file_record in files
        ),
    }
 
 
def _review_group_key(file_path: str) -> str:
    parts = Path(file_path).parts
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return file_path


class Coordinator:
    def __init__(self, settings: RuntimeConfig) -> None:
        self.settings = settings
        self.duckdb = DuckDBStore(settings.duckdb_path)
        self.kuzu = KuzuStore(settings.kuzu_path)
        self.vector_store = VectorStore(settings.lancedb_path)
        self.manifest_store = ManifestStore(settings.manifest_path)
        # self.reviewers = {
        #     "security": SecurityReviewer(),
        #     "logic": LogicReviewer(),
        #     "maintainability": MaintainabilityReviewer(),
        # }
        self.reviewers = {
            "general": GeneralReviewer(),
        }
        self.latest_findings: list[ReviewFinding] = []
        self.latest_observations: list[ReviewObservation] = []
        self.latest_agent_analyses: list[ReviewAgentAnalysis] = []
        self.symbols_by_file: dict[str, list] = {}
 
    def _log_progress(self, message: str) -> None:
        print(f"[progress] {message}", flush=True)
 
    def _should_log_index(self, index: int, total: int) -> bool:
        if total <= 10:
            return True
        interval = max(total // 10, 1)
        return index == 1 or index == total or index % interval == 0
 
    def _run_agent_analyses(self, review_jobs: list, analysis_provider) -> list[ReviewAgentAnalysis]:
        if not review_jobs:
            return []
        prepared_jobs: list[tuple] = []
        for job in review_jobs:
            file_path = self.settings.repo_root / Path(job.file_path)
            context = build_review_context(self.duckdb, self.kuzu, file_path, job.file_path)
            prepared_jobs.append((job, file_path, context))
        grouped_prepared_jobs: list[list[tuple]] = []
        grouped_by_key: dict[str, list[tuple]] = defaultdict(list)
        for prepared in prepared_jobs:
            job = prepared[0]
            grouped_by_key[_review_group_key(job.file_path)].append(prepared)
        for items in grouped_by_key.values():
            group_size = max(self.settings.review_group_size, 1)
            for index in range(0, len(items), group_size):
                grouped_prepared_jobs.append(items[index:index + group_size])
        completed = 0
        analyses: list[ReviewAgentAnalysis] = []
        analysis_records: list[dict[str, object]] = []
        max_workers = max(min(self.settings.max_concurrent_llm_reviews, len(grouped_prepared_jobs)), 1)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_group = {
                executor.submit(
                    analysis_provider.analyze_group,
                    [job for job, _, _ in group],
                    [context for _, _, context in group],
                ): group
                for group in grouped_prepared_jobs
            }
            for future in as_completed(future_to_group):
                job_analyses = future.result()
                analyses.extend(job_analyses)
                for analysis in job_analyses:
                    record = asdict(analysis)
                    record["output_json"] = json.dumps(record["output_json"])
                    record["input_context_json"] = json.dumps(record["input_context_json"])
                    analysis_records.append(record)
                completed += 1
                group = future_to_group[future]
                if self._should_log_index(completed, len(grouped_prepared_jobs)):
                    self._log_progress(
                        f"agent analysis progress: {completed}/{len(grouped_prepared_jobs)} groups, {len(analyses)} analyses prepared ({', '.join(job.file_path for job, _, _ in group[:2])})"
                    )
        if analysis_records:
            self._log_progress(f"agent analysis bulk write started: {len(analysis_records)} analyses")
            self.duckdb.reviews.insert_agent_analyses(analysis_records)
            self._log_progress("agent analysis bulk write completed")
        return analyses

    def _should_run_legacy_review_jobs(self, analysis_provider_used: str) -> bool:
        if analysis_provider_used != "openrouter-multi-agent":
            return True
        return self.settings.review_run_legacy_heuristics_with_llm
 
    def _load_persisted_symbols(self) -> dict[str, list[SymbolRecord]]:
        loaded: dict[str, list[SymbolRecord]] = {}
        for file_path, rows in self.duckdb.symbols.fetch_by_file().items():
            loaded[file_path] = [
                SymbolRecord(
                    name=row["name"],
                    qualified_name=row["qualified_name"],
                    kind=row["kind"],
                    start_line=row["start_line"],
                    end_line=row["end_line"],
                    signature=row["signature"],
                    metadata=json.loads(row["metadata_json"] or "{}"),
                )
                for row in rows
            ]
        return loaded

    def _initialize_run_state(self, run_mode: str) -> tuple[RunSummary, bool, dict[str, dict[str, object]]]:
        summary = RunSummary(run_id=uuid4().hex[:8], run_mode=run_mode)
        self._log_progress(f"run {summary.run_id} started for {self.settings.repo_root} ({run_mode})")
        full_rebuild = run_mode == FULL
        existing_files = self.duckdb.files.fetch_index() if not full_rebuild else {}
        if full_rebuild:
            self.duckdb.clear_index_tables()
            self.kuzu.reset()
            self.vector_store.reset()
            self.symbols_by_file = {}
        else:
            self.symbols_by_file = self._load_persisted_symbols()
        return summary, full_rebuild, existing_files

    def _run_scan_stage(self, summary: RunSummary, run_mode: str) -> list:
        scan_stage = StageResult(stage_name="scan", status="running")
        self._log_progress("scan started")
        files = scan_repo(self.settings.repo_root, excluded_dirs=self.settings.scan_excluded_dirs, progress_callback=self._log_progress)
        repo_profile = _build_repo_profile(files)
        scan_stage.output_summary = {
            "file_count": len(files),
            "run_mode": run_mode,
            "excluded_dirs": list(self.settings.scan_excluded_dirs),
            "repo_profile": repo_profile,
        }
        scan_stage.status = "completed"
        scan_stage.completed_at = time()
        summary.stage_results.append(scan_stage)
        self._log_progress(
            f"scan completed: discovered {len(files)} files after excluding {len(self.settings.scan_excluded_dirs)} directory patterns"
        )
        return files

    def _run_plan_stage(self, summary: RunSummary, files: list, existing_files: dict[str, dict[str, object]], full_rebuild: bool) -> dict[str, list[str]]:
        plan_stage = StageResult(stage_name="plan", status="running")
        self._log_progress("plan started")
        plan = plan_incremental_work(files, existing_files=existing_files)
        if full_rebuild:
            plan["files_to_parse"] = [file_record.path for file_record in files]
            plan["files_to_review"] = [file_record.path for file_record in files]
            plan["deleted_files"] = []
            plan["unchanged_files"] = []
        plan_stage.output_summary = dict(plan)
        plan_stage.status = "completed"
        plan_stage.completed_at = time()
        summary.stage_results.append(plan_stage)
        self._log_progress(
            f"plan completed: parse={len(plan['files_to_parse'])}, review={len(plan['files_to_review'])}, deleted={len(plan.get('deleted_files', []))}"
        )
        return plan

    def _prepare_incremental_scope(self, files: list, plan: dict[str, list[str]], full_rebuild: bool) -> dict[str, object]:
        file_map = {file_record.path: file_record for file_record in files}
        changed_files = plan["files_to_parse"]
        deleted_files = plan.get("deleted_files", [])
        unchanged_files = plan.get("unchanged_files", [])
        previous_chunks_by_file: dict[str, list[dict[str, object]]] = {}
        if not full_rebuild and changed_files:
            for chunk in self.duckdb.fetch_chunks_for_files(changed_files):
                previous_chunks_by_file.setdefault(str(chunk.get("file_path", "")), []).append(chunk)
        impacted_file_details: dict[str, object] = {"impacted_files": [], "by_touched_file": {}, "relation_totals": {}}
        touched_files = sorted(set(changed_files) | set(deleted_files))
        if touched_files and not full_rebuild:
            self.duckdb.reviews.resolve_findings_for_files(touched_files)
            self.duckdb.files.delete_index_data_for_files(touched_files)
            if deleted_files:
                self.vector_store.delete_items_for_files(deleted_files)
            impacted_file_details = self.kuzu.get_impacted_file_details(touched_files)
            impacted_files = set(str(path) for path in impacted_file_details.get("impacted_files", []))
            impacted_files = {file_path for file_path in impacted_files if file_path in file_map or file_path in self.symbols_by_file}
            self.kuzu.delete_index_data_for_files(sorted(impacted_files))
            for file_path in touched_files:
                self.symbols_by_file.pop(file_path, None)
        else:
            impacted_files = set(file_map) if full_rebuild else set()
        return {
            "file_map": file_map,
            "changed_files": changed_files,
            "deleted_files": deleted_files,
            "unchanged_files": unchanged_files,
            "previous_chunks_by_file": previous_chunks_by_file,
            "touched_files": touched_files,
            "impacted_files": impacted_files,
            "impacted_file_details": impacted_file_details,
        }

    def _run_parse_stage(self, summary: RunSummary, file_map: dict[str, Any], changed_files: list[str], unchanged_files: list[str], deleted_files: list[str]) -> int:
        parse_stage = StageResult(stage_name="parse", status="running")
        self._log_progress(f"parse started for {len(changed_files)} changed files")
        parse_stage.input_summary = {
            "changed_files": len(changed_files),
            "unchanged_files": len(unchanged_files),
            "deleted_files": len(deleted_files),
        }
        parser_usage: dict[str, int] = defaultdict(int)
        clang_runtime_summary: dict[str, object] = {}
        file_records_to_upsert = []
        absolute_paths = [self.settings.repo_root / file_map[fp].path for fp in changed_files]
        max_workers = min(len(changed_files), 8) if len(changed_files) > 1 else 1
        if max_workers > 1:
            self._log_progress(f"parse using ProcessPoolExecutor with {max_workers} workers")
            with ProcessPoolExecutor(max_workers=max_workers) as pool:
                results = list(pool.map(_parse_file_worker, absolute_paths, chunksize=max(1, len(changed_files) // (max_workers * 4))))
            for index, ((abs_path_str, symbol_dicts, parse_status), file_path) in enumerate(zip(results, changed_files), start=1):
                file_record = file_map[file_path]
                symbols = [SymbolRecord(**d) for d in symbol_dicts]
                self.symbols_by_file[file_record.path] = symbols
                parser_name = str(parse_status.get("parser", "unknown"))
                parser_usage[parser_name] += 1
                if not clang_runtime_summary and isinstance(parse_status.get("clang"), dict):
                    clang_runtime_summary = dict(parse_status.get("clang") or {})
                file_records_to_upsert.append(file_record)
                if self._should_log_index(index, len(changed_files)):
                    self._log_progress(
                        f"parse progress: {index}/{len(changed_files)} files ({file_record.path}) parser={parser_name} symbols={len(symbols)}"
                    )
        else:
            for index, file_path in enumerate(changed_files, start=1):
                file_record = file_map[file_path]
                absolute_file_path = self.settings.repo_root / file_record.path
                symbols, parse_status = extract_symbols_with_status(absolute_file_path)
                self.symbols_by_file[file_record.path] = symbols
                parser_name = str(parse_status.get("parser", "unknown"))
                parser_usage[parser_name] += 1
                if not clang_runtime_summary and isinstance(parse_status.get("clang"), dict):
                    clang_runtime_summary = dict(parse_status.get("clang") or {})
                file_records_to_upsert.append(file_record)
                if self._should_log_index(index, len(changed_files)):
                    self._log_progress(
                        f"parse progress: {index}/{len(changed_files)} files ({file_record.path}) parser={parser_name} symbols={len(symbols)}"
                    )
        if file_records_to_upsert:
            persisted = persist_parse_records(self.duckdb, file_records_to_upsert, self.symbols_by_file)
            self._log_progress(f"parse DB write completed: {persisted['files']} files, {persisted['symbols']} symbols")
        symbol_count = sum(len(symbols) for symbols in self.symbols_by_file.values())
        parse_stage.output_summary = {
            "parsed_files": len(changed_files),
            "retained_files": len(unchanged_files),
            "symbol_count": symbol_count,
            "parser_usage": dict(parser_usage),
            "clang_runtime": clang_runtime_summary,
        }
        parse_stage.status = "completed"
        parse_stage.completed_at = time()
        summary.stage_results.append(parse_stage)
        self._log_progress(
            f"parse completed: {len(changed_files)} files, {symbol_count} symbols, parsers={dict(parser_usage)}"
        )
        return symbol_count

    def _run_graph_stage(self, summary: RunSummary, file_map: dict[str, Any], impacted_files: set[str], touched_files: list[str], impacted_file_details: dict[str, object], full_rebuild: bool) -> None:
        graph_stage = StageResult(stage_name="graph", status="running")
        graph_files = [file_map[file_path] for file_path in sorted(impacted_files) if file_path in file_map]
        self._log_progress(f"graph started for {len(graph_files)} impacted files")
        graph_stage.input_summary = {
            "impacted_files": len(graph_files),
            "touched_files": len(touched_files),
        }
        if not full_rebuild and touched_files:
            graph_stage.diagnostics.append({
                "impacted_file_details": {
                    "impacted_files": sorted(impacted_files),
                    "by_touched_file": impacted_file_details.get("by_touched_file", {}),
                    "relation_totals": impacted_file_details.get("relation_totals", {}),
                }
            })
        if graph_files:
            build_graph(self.kuzu, graph_files, self.symbols_by_file, progress_callback=self._log_progress)
        graph_stage.output_summary = {
            "edge_count": self.kuzu.count_edges(),
            "rebuilt_files": len(graph_files),
        }
        graph_stage.status = "completed"
        graph_stage.completed_at = time()
        summary.stage_results.append(graph_stage)
        self._log_progress(f"graph completed: {graph_stage.output_summary['edge_count']} edges")

    def _run_process_stage(self, summary: RunSummary, file_map: dict[str, Any], impacted_files: set[str], full_rebuild: bool, symbol_count: int) -> tuple[list, list, list, list]:
        process_stage = StageResult(stage_name="process", status="running")
        process_scope_files = sorted(set(file_map) if full_rebuild else impacted_files)
        process_symbols_by_file = {
            file_path: self.symbols_by_file[file_path]
            for file_path in process_scope_files
            if file_path in self.symbols_by_file
        }
        process_stage.input_summary = {
            "symbol_count": symbol_count,
            "scoped_symbol_count": sum(len(symbols) for symbols in process_symbols_by_file.values()),
            "scoped_file_count": len(process_symbols_by_file),
            "max_depth": self.settings.process_max_depth,
            "max_entrypoints": self.settings.process_max_entrypoints,
            "max_flows_per_entrypoint": self.settings.process_max_flows_per_entrypoint,
            "max_records": self.settings.process_max_records,
            "max_relationships": self.settings.process_max_relationships,
        }
        if self.settings.process_extraction_enabled:
            process_started_at = time()
            self._log_progress(
                f"process extraction started for {sum(len(symbols) for symbols in process_symbols_by_file.values())} scoped symbols across {len(process_symbols_by_file)} files"
            )
            if not full_rebuild and process_scope_files:
                self.duckdb.processes.delete_for_files(process_scope_files)
            process_records, process_clusters, process_memberships, process_relationships = build_process_graph_records(
                self.duckdb,
                self.kuzu,
                process_symbols_by_file,
                max_depth=self.settings.process_max_depth,
                max_flows_per_target=self.settings.process_max_flows_per_entrypoint,
                max_entrypoints=self.settings.process_max_entrypoints,
                max_processes=self.settings.process_max_records,
                max_relationships=self.settings.process_max_relationships,
                progress_callback=self._log_progress,
            )
            self._log_progress(f"process write started: {len(process_records)} processes")
            self.duckdb.processes.insert_processes([asdict(process_record) for process_record in process_records])
            self._log_progress(f"process cluster write started: {len(process_clusters)} clusters")
            self.duckdb.processes.insert_clusters([asdict(process_cluster) for process_cluster in process_clusters])
            self._log_progress(f"process membership write started: {len(process_memberships)} memberships")
            self.duckdb.processes.insert_symbol_memberships([asdict(membership) for membership in process_memberships])
            self._log_progress(f"process relationship write started: {len(process_relationships)} relationships")
            self.duckdb.processes.insert_relationships([asdict(relationship) for relationship in process_relationships])
            self._log_progress(
                f"process extraction completed in {round(time() - process_started_at, 2)}s: {len(process_records)} processes, {len(process_clusters)} clusters, {len(process_relationships)} relationships persisted"
            )
        else:
            process_records = []
            process_clusters = []
            process_memberships = []
            process_relationships = []
            self._log_progress("process extraction skipped because CODER_PROCESS_EXTRACTION_ENABLED=false")
        process_stage.output_summary = {
            "enabled": self.settings.process_extraction_enabled,
            "processes": len(process_records),
            "clusters": len(process_clusters),
            "memberships": len(process_memberships),
            "relationships": len(process_relationships),
        }
        process_stage.status = "completed"
        process_stage.completed_at = time()
        summary.stage_results.append(process_stage)
        return process_records, process_clusters, process_memberships, process_relationships

    def _run_embed_stage(self, summary: RunSummary, file_map: dict[str, Any], changed_files: list[str], previous_chunks_by_file: dict[str, list[dict[str, object]]], full_rebuild: bool) -> dict[str, object]:
        embed_stage = StageResult(stage_name="embed", status="running")
        self._log_progress(f"embed started for {len(changed_files)} files")
        existing_chunk_count = self.duckdb.chunks.count()
        new_chunk_count = 0
        chunks_to_embed = []
        chunk_records_to_insert: list[dict[str, object]] = []
        stale_chunk_ids: list[str] = []
        embedding_request = EmbeddingRequest(
            model_name=self.settings.embedding_model,
            provider_name=self.settings.embedding_provider,
            batch_size=self.settings.embedding_batch_size,
            max_length=self.settings.embedding_max_length,
            device=self.settings.embedding_device,
            max_batch_tokens=self.settings.embedding_max_batch_tokens,
            api_key=self.settings.embedding_api_key,
            base_url=self.settings.embedding_base_url,
            retry_attempts=self.settings.embedding_retry_attempts,
            retry_backoff_seconds=self.settings.embedding_retry_backoff_seconds,
            max_concurrent_batches=self.settings.embedding_max_concurrent_batches,
        )
        embedding_runtime = embedding_runtime_info(embedding_request)
        requested_device = str(embedding_runtime.get('requested_device', ''))
        resolved_device = str(embedding_runtime.get('resolved_device', ''))
        if requested_device and requested_device != resolved_device and resolved_device == 'cpu':
            logger.warning(
                'GPU fallback: requested device %s but resolved to %s — embeddings will be slower',
                requested_device, resolved_device,
            )
        self._log_progress(
            f"embedding runtime: backend={embedding_runtime['backend']} requested={embedding_runtime['requested_device']} resolved={embedding_runtime['resolved_device']}"
        )
        embed_stage.input_summary = {"files_to_embed": len(changed_files)}
        reused_embedding_count = 0
        new_embedding_count = 0
        chunk_module_count = 0
        skipped_unchanged_chunks = 0
        chunk_omitted_content_count = 0
        chunk_duplicate_content_count = 0
        aggregate_chunk_kind_counts: dict[str, int] = defaultdict(int)
        embed_result: dict[str, object] = {}
        for index, file_path in enumerate(changed_files, start=1):
            file_record = file_map[file_path]
            chunks = build_chunks(self.settings.repo_root, file_record.path, self.symbols_by_file.get(file_record.path, []))
            chunk_summary = summarize_chunks(chunks)
            new_chunk_count += len(chunks)
            if not full_rebuild:
                previous_chunks = previous_chunks_by_file.get(file_record.path, [])
                chunk_diff = diff_chunk_ids(previous_chunks, chunks)
                stale_chunk_ids.extend(sorted(chunk_diff["stale"]))
                previous_content_hashes = {
                    str(prev.get("chunk_id", "")): str(prev.get("content_hash", ""))
                    for prev in previous_chunks
                    if str(prev.get("chunk_id", ""))
                }
                changed_chunks = [
                    chunk for chunk in chunks
                    if chunk.chunk_id not in previous_content_hashes
                    or chunk.content_hash != previous_content_hashes.get(chunk.chunk_id, "")
                ]
                skipped_unchanged_chunks += len(chunks) - len(changed_chunks)
                chunks = changed_chunks
            chunk_module_count += int(chunk_summary.get("module_chunk_count", 0))
            chunk_omitted_content_count += int(chunk_summary.get("omitted_content_chunk_count", 0))
            chunk_duplicate_content_count += int(chunk_summary.get("duplicate_content_chunk_count", 0))
            for kind, count in dict(chunk_summary.get("chunk_kind_counts", {})).items():
                aggregate_chunk_kind_counts[str(kind)] += int(count)
            if chunks and self._should_log_index(index, len(changed_files)):
                self._log_progress(
                    f"chunk write progress: writing {len(chunks)} chunks for {file_record.path} module={chunk_summary.get('module_chunk_count', 0)} omitted={chunk_summary.get('omitted_content_chunk_count', 0)} dup_content={chunk_summary.get('duplicate_content_chunk_count', 0)}"
                )
            chunk_records_to_insert.extend(asdict(chunk) for chunk in chunks)
            chunks_to_embed.extend(chunks)
            if self._should_log_index(index, len(changed_files)):
                self._log_progress(
                    f"chunk progress: {index}/{len(changed_files)} files, {new_chunk_count} new chunks prepared ({file_record.path})"
                )
        if stale_chunk_ids:
            self._log_progress(f"chunk diff cleanup started: deleting {len(stale_chunk_ids)} stale vector chunks")
            self.vector_store.delete_items_for_chunk_ids(stale_chunk_ids)
        if chunk_records_to_insert:
            self._log_progress(f"chunk DB write started: {len(chunk_records_to_insert)} chunks")
            persist_chunk_records(self.duckdb, chunks_to_embed)
        if chunks_to_embed:
            vector_started_at = time()
            model_name = self.settings.embedding_model
            if model_name.startswith("jinaai/"):
                prewarm_jina_model(model_name, device=self.settings.embedding_device)
                if not wait_for_model(model_name, timeout=60.0):
                    load_error = ""
                    try:
                        from indexing.embeddings import get_model_load_error
                        load_error = get_model_load_error(model_name)
                    except Exception:
                        pass
                    raise RuntimeError(
                        f"Embedding model {model_name!r} failed to load"
                        + (f": {load_error}" if load_error else " within 60s timeout")
                        + ". Vector embeddings cannot be generated without the model."
                    )
            self._log_progress(f"embedding vectors started for {len(chunks_to_embed)} chunks")
            embed_result = embed_chunks(
                self.vector_store,
                chunks_to_embed,
                model_name=self.settings.embedding_model,
                batch_size=self.settings.embedding_batch_size,
                max_length=self.settings.embedding_max_length,
                device=self.settings.embedding_device,
                max_batch_tokens=self.settings.embedding_max_batch_tokens,
                provider_name=self.settings.embedding_provider,
                api_key=self.settings.embedding_api_key,
                base_url=self.settings.embedding_base_url,
                retry_attempts=self.settings.embedding_retry_attempts,
                retry_backoff_seconds=self.settings.embedding_retry_backoff_seconds,
                max_concurrent_batches=self.settings.embedding_max_concurrent_batches,
            )
            reused_embedding_count += int(embed_result.get("reused_embedding_count", 0))
            new_embedding_count += int(embed_result.get("new_embedding_count", 0))
            self._log_progress(
                f"embedding vectors completed in {round(time() - vector_started_at, 2)}s: reused={reused_embedding_count}, new={new_embedding_count}, cache_hits={embed_result.get('cache_hit_count', 0)}, cache_misses={embed_result.get('cache_miss_count', 0)}, dup_reuse={embed_result.get('duplicate_content_reuse_count', 0)}, batches~={embed_result.get('planned_batch_count', 0)}/{embed_result.get('token_budget_batch_estimate', 0)}, missing_tokens~={embed_result.get('approx_missing_token_count', 0)}"
            )
        total_chunks = existing_chunk_count + new_chunk_count
        embed_stage.output_summary = {
            "chunk_count": total_chunks,
            "updated_files": len(changed_files),
            "new_chunks": new_chunk_count,
            "module_chunks": chunk_module_count,
            "omitted_content_chunks": chunk_omitted_content_count,
            "duplicate_content_chunks": chunk_duplicate_content_count,
            "chunk_kind_counts": dict(aggregate_chunk_kind_counts),
            "reused_embeddings": reused_embedding_count,
            "new_embeddings": new_embedding_count,
            "skipped_unchanged_chunks": skipped_unchanged_chunks,
            "embedding_cache_hits": int(embed_result.get("cache_hit_count", 0)),
            "embedding_cache_misses": int(embed_result.get("cache_miss_count", 0)),
            "embedding_duplicate_content_reuse": int(embed_result.get("duplicate_content_reuse_count", 0)),
            "embedding_unique_content_hashes": int(embed_result.get("unique_content_hash_count", 0)),
            "embedding_requested_batch_size": int(embed_result.get("requested_batch_size", 0)),
            "embedding_max_batch_tokens": int(embed_result.get("max_batch_tokens", 0)),
            "embedding_planned_batch_count": int(embed_result.get("planned_batch_count", 0)),
            "embedding_token_budget_batch_estimate": int(embed_result.get("token_budget_batch_estimate", 0)),
            "embedding_approx_missing_token_count": int(embed_result.get("approx_missing_token_count", 0)),
            "embedding_provider": str(embed_result.get("provider", "")),
            "embedding_runtime": embedding_runtime,
        }
        embed_stage.status = "completed"
        embed_stage.completed_at = time()
        summary.stage_results.append(embed_stage)
        self._log_progress(f"embed completed: {new_chunk_count} new chunks, {total_chunks} total chunks")
        return {"embedding_runtime": embedding_runtime, "total_chunks": total_chunks}

    def _run_review_stage(self, summary: RunSummary, plan: dict[str, list[str]]) -> None:
        review_stage = StageResult(stage_name="review", status="running")
        self._log_progress(f"review planning started for {len(plan['files_to_review'])} files")
        review_jobs = build_review_jobs(plan["files_to_review"], run_id=summary.run_id)
        review_stage.input_summary = {
            "files_to_review": len(plan["files_to_review"]),
            "review_types": len(self.reviewers),
            "enabled": self.settings.review_enabled,
        }
        if not self.settings.review_enabled:
            self.latest_agent_analyses = []
            self.latest_observations = []
            self.latest_findings = []
            review_stage.output_summary = {
                "job_count": len(review_jobs),
                "reviewed_files": 0,
                "enabled": False,
                "agent_analysis_count": 0,
                "observation_count": 0,
                "finding_count": 0,
            }
            review_stage.status = "completed"
            review_stage.completed_at = time()
            summary.stage_results.append(review_stage)
            self._log_progress(f"review skipped for {len(review_jobs)} jobs because CODER_REVIEW_ENABLED=false")
            return

        self._log_progress(f"review started for {len(review_jobs)} jobs")
        self._log_progress(f"review job write started for {len(review_jobs)} jobs")
        for job in review_jobs:
            self.duckdb.reviews.insert_job(asdict(job))
        self._log_progress("review job write completed")
        analysis_provider = build_review_analysis_provider(self.settings.review_analysis_provider, self.settings)
        analysis_provider_requested = self.settings.review_analysis_provider
        analysis_provider_used = analysis_provider.provider_name
        analysis_model_used = analysis_provider.model_name
        analysis_provider_fallback = analysis_provider_requested != analysis_provider_used
        self.latest_agent_analyses = []
        if review_jobs:
            self._log_progress(f"agent analysis provider: {analysis_provider_used} ({analysis_model_used})")
        self.latest_agent_analyses = self._run_agent_analyses(review_jobs, analysis_provider)
        run_legacy_review_jobs = self._should_run_legacy_review_jobs(analysis_provider_used)
        if run_legacy_review_jobs:
            review_results = self._run_review_jobs(review_jobs)
        else:
            review_results = []
            self._log_progress("legacy heuristic review skipped because grouped LLM review is active")
        review_results.extend(synthesize_findings_from_agent_analyses(self.latest_agent_analyses, review_jobs))
        self._log_progress(f"review result merge started for {len(review_results)} results")
        self.latest_observations, self.latest_findings = merge_findings(review_results)
        self._log_progress(f"review persistence started: {len(self.latest_observations)} observations, {len(self.latest_findings)} findings")
        for observation in self.latest_observations:
            self.duckdb.reviews.insert_observation(asdict(observation))
        for finding in self.latest_findings:
            record = asdict(finding)
            existing = self.duckdb.reviews.fetch_finding_by_fingerprint(record["fingerprint"])
            if existing is not None:
                record["finding_id"] = existing["finding_id"]
                record["first_seen_at"] = existing["first_seen_at"]
                record["occurrence_count"] = existing["occurrence_count"] + record["occurrence_count"]
            record["source_review_types"] = json.dumps(record["source_review_types"])
            self.duckdb.reviews.upsert_finding(record)
        review_stage.output_summary = {
            "job_count": len(review_jobs),
            "reviewed_files": len(plan["files_to_review"]),
            "enabled": True,
            "analysis_provider_requested": analysis_provider_requested,
            "analysis_provider_used": analysis_provider_used,
            "analysis_model": analysis_model_used,
            "analysis_provider_fallback": analysis_provider_fallback,
            "legacy_heuristic_review_enabled": run_legacy_review_jobs,
            "agent_analysis_count": len(self.latest_agent_analyses),
            "observation_count": len(self.latest_observations),
            "finding_count": len(self.latest_findings),
        }
        review_stage.status = "completed"
        review_stage.completed_at = time()
        summary.stage_results.append(review_stage)
        self._log_progress(
            f"review completed: jobs={len(review_jobs)}, analyses={len(self.latest_agent_analyses)}, findings={len(self.latest_findings)}"
        )

    def _finalize_run(self, summary: RunSummary, files: list, symbol_count: int, total_chunks: int, process_records: list, process_clusters: list, embedding_runtime: dict[str, object]) -> RunSummary:
        self._log_progress("manifest write started")
        manifest = {
            "status": "ready",
            "run_id": summary.run_id,
            "repo_root": str(self.settings.repo_root),
            "project_root": str(self.settings.project_root),
            "data_dir": str(self.settings.data_dir),
            "embedding_runtime": embedding_runtime,
            "counts": {
                "files": len(files),
                "symbols": symbol_count,
                "chunks": total_chunks,
                "processes": len(process_records),
                "process_clusters": len(process_clusters),
                "findings": len(self.latest_findings),
            },
            "versions": {
                "parser_version": self.settings.versions.parser_version,
                "graph_version": self.settings.versions.graph_version,
                "chunking_version": self.settings.versions.chunking_version,
                "embedding_model": self.settings.embedding_model,
                "reviewer_bundle_version": self.settings.versions.reviewer_bundle_version,
            },
        }
        self.manifest_store.write_current(manifest)
        self._log_progress("AGENTS.md update started")
        agents_file_result = update_agents_file(self.settings.repo_root, enabled=self.settings.agents_file_enabled)
        if agents_file_result.get("updated"):
            self._log_progress(f"AGENTS.md updated: {agents_file_result.get('path')}")
        else:
            self._log_progress("AGENTS.md already current or disabled")
        self._log_progress("run metadata write started")
        self.duckdb.runs.upsert(
            {
                "run_id": summary.run_id,
                "run_mode": summary.run_mode,
                "status": "completed",
                "file_count": len(files),
                "symbol_count": symbol_count,
                "chunk_count": total_chunks,
                "finding_count": len(self.latest_findings),
            }
        )
        self._log_progress("technical summary generation started")
        summary.technical_summary = generate_run_summary(
            self.settings,
            summary,
            self.latest_findings,
            self.latest_agent_analyses,
            audience="technical",
        )
        summary.llm_summary = summary.technical_summary
        self._log_progress("layperson summary generation started")
        summary.layperson_summary = generate_run_summary(
            self.settings,
            summary,
            self.latest_findings,
            self.latest_agent_analyses,
            audience="layperson",
        )
        self._log_progress("report write started")
        summary.report_paths = write_run_reports(
            self.settings.data_dir,
            summary.run_id,
            summary.technical_summary,
            summary.layperson_summary,
        )
        self._log_progress(f"reports written: {summary.report_paths}")
        self._log_progress("run metadata refresh started")
        self.duckdb.runs.upsert(
            {
                "run_id": summary.run_id,
                "run_mode": summary.run_mode,
                "status": "completed",
                "file_count": len(files),
                "symbol_count": symbol_count,
                "chunk_count": total_chunks,
                "finding_count": len(self.latest_findings),
                "stage_results_json": json.dumps(
                    [
                        {
                            "stage_name": stage.stage_name,
                            "status": stage.status,
                            "input_summary": stage.input_summary,
                            "output_summary": stage.output_summary,
                            "diagnostics": stage.diagnostics,
                            "started_at": stage.started_at,
                            "completed_at": stage.completed_at,
                        }
                        for stage in summary.stage_results
                    ]
                ),
                "warnings_json": json.dumps(summary.warnings),
                "errors_json": json.dumps(summary.errors),
                "report_paths_json": json.dumps(summary.report_paths),
            }
        )
        summary.promoted = True
        self._log_progress(f"run {summary.run_id} completed")
        return summary
 
    def run(self, run_mode: str = INCREMENTAL) -> RunSummary:
        summary, full_rebuild, existing_files = self._initialize_run_state(run_mode)
        files = self._run_scan_stage(summary, run_mode)
        plan = self._run_plan_stage(summary, files, existing_files, full_rebuild)
        scope = self._prepare_incremental_scope(files, plan, full_rebuild)
        symbol_count = self._run_parse_stage(
            summary,
            scope["file_map"],
            scope["changed_files"],
            scope["unchanged_files"],
            scope["deleted_files"],
        )
        self._run_graph_stage(
            summary,
            scope["file_map"],
            scope["impacted_files"],
            scope["touched_files"],
            scope["impacted_file_details"],
            full_rebuild,
        )
        process_records, process_clusters, _process_memberships, _process_relationships = self._run_process_stage(
            summary,
            scope["file_map"],
            scope["impacted_files"],
            full_rebuild,
            symbol_count,
        )
        embed_result = self._run_embed_stage(
            summary,
            scope["file_map"],
            scope["changed_files"],
            scope["previous_chunks_by_file"],
            full_rebuild,
        )
        self._run_review_stage(summary, plan)
        return self._finalize_run(
            summary,
            files,
            symbol_count,
            int(embed_result["total_chunks"]),
            process_records,
            process_clusters,
            dict(embed_result["embedding_runtime"]),
        )
 
    def _run_review_jobs(self, review_jobs: list) -> list[ReviewResult]:
        policy = ReviewExecutionPolicy(
            max_workers=self.settings.max_review_workers,
            max_concurrent_llm_requests=self.settings.max_concurrent_llm_reviews,
            max_attempts=self.settings.review_retry_attempts,
            initial_backoff_seconds=self.settings.review_retry_backoff_seconds,
        )
        return run_review_jobs(
            review_jobs,
            self.reviewers,
            self.settings.repo_root,
            policy,
            progress_callback=lambda completed, total, job: self._log_progress(
                f"heuristic review progress: {completed}/{total} jobs completed ({job.review_type} {job.file_path})"
            ),
        )
