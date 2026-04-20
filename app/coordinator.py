from __future__ import annotations
 
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from time import time
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor, as_completed
 
from app.run_modes import FULL, INCREMENTAL
from indexing.chunker import build_chunks
from indexing.embedder import embed_chunks
from indexing.embeddings import get_embedding_runtime_info
from indexing.graph_builder import build_graph
from indexing.planner import plan_incremental_work
from indexing.scanner import scan_repo
from indexing.symbol_extractor import extract_symbols
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
from services.run_summary_service import generate_run_summary, write_run_reports
from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore
from storage.manifest_store import ManifestStore
from storage.vector_store import VectorStore
 
 
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
                    self.duckdb.insert_review_agent_analysis(record)
                completed += 1
                group = future_to_group[future]
                if self._should_log_index(completed, len(grouped_prepared_jobs)):
                    self._log_progress(
                        f"agent analysis progress: {completed}/{len(grouped_prepared_jobs)} groups, {len(analyses)} analyses persisted ({', '.join(job.file_path for job, _, _ in group[:2])})"
                    )
        return analyses

    def _should_run_legacy_review_jobs(self, analysis_provider_used: str) -> bool:
        if analysis_provider_used != "openrouter-multi-agent":
            return True
        return self.settings.review_run_legacy_heuristics_with_llm
 
    def _load_persisted_symbols(self) -> dict[str, list[SymbolRecord]]:
        loaded: dict[str, list[SymbolRecord]] = {}
        for file_path, rows in self.duckdb.fetch_symbols_by_file().items():
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
 
    def run(self, run_mode: str = INCREMENTAL) -> RunSummary:
        summary = RunSummary(run_id=uuid4().hex[:8], run_mode=run_mode)
        self._log_progress(f"run {summary.run_id} started for {self.settings.repo_root} ({run_mode})")
        full_rebuild = run_mode == FULL
        existing_files = self.duckdb.fetch_files_index() if not full_rebuild else {}
        if full_rebuild:
            self.duckdb.clear_index_tables()
            self.kuzu.reset()
            self.vector_store.reset()
            self.symbols_by_file = {}
        else:
            self.symbols_by_file = self._load_persisted_symbols()
 
        scan_stage = StageResult(stage_name="scan", status="running")
        self._log_progress("scan started")
        files = scan_repo(self.settings.repo_root, excluded_dirs=self.settings.scan_excluded_dirs)
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

        file_map = {file_record.path: file_record for file_record in files}
        changed_files = plan["files_to_parse"]
        deleted_files = plan.get("deleted_files", [])
        unchanged_files = plan.get("unchanged_files", [])
        touched_files = sorted(set(changed_files) | set(deleted_files))
        if touched_files and not full_rebuild:
            self.duckdb.resolve_findings_for_files(touched_files)
            self.duckdb.delete_index_data_for_files(touched_files)
            self.vector_store.delete_items_for_files(touched_files)
            impacted_files = self.kuzu.get_impacted_files(touched_files)
            impacted_files = {file_path for file_path in impacted_files if file_path in file_map or file_path in self.symbols_by_file}
            self.kuzu.delete_index_data_for_files(sorted(impacted_files))
            for file_path in touched_files:
                self.symbols_by_file.pop(file_path, None)
        else:
            impacted_files = set(file_map) if full_rebuild else set()

        parse_stage = StageResult(stage_name="parse", status="running")
        self._log_progress(f"parse started for {len(changed_files)} changed files")
        parse_stage.input_summary = {
            "changed_files": len(changed_files),
            "unchanged_files": len(unchanged_files),
            "deleted_files": len(deleted_files),
        }
        for index, file_path in enumerate(changed_files, start=1):
            file_record = file_map[file_path]
            file_path = self.settings.repo_root / file_record.path
            symbols = extract_symbols(file_path)
            self.symbols_by_file[file_record.path] = symbols
            self.duckdb.upsert_file(asdict(file_record))
            for symbol in symbols:
                self.duckdb.insert_symbol(
                    {
                        "file_path": file_record.path,
                        "qualified_name": symbol.qualified_name,
                        "name": symbol.name,
                        "kind": symbol.kind,
                        "start_line": symbol.start_line,
                        "end_line": symbol.end_line,
                        "signature": symbol.signature,
                        "metadata_json": json.dumps(symbol.metadata),
                    }
                )
            if self._should_log_index(index, len(changed_files)):
                self._log_progress(f"parse progress: {index}/{len(changed_files)} files ({file_record.path})")
        symbol_count = sum(len(symbols) for symbols in self.symbols_by_file.values())
        parse_stage.output_summary = {
            "parsed_files": len(changed_files),
            "retained_files": len(unchanged_files),
            "symbol_count": symbol_count,
        }
        parse_stage.status = "completed"
        parse_stage.completed_at = time()
        summary.stage_results.append(parse_stage)
        self._log_progress(f"parse completed: {len(changed_files)} files, {symbol_count} symbols")

        graph_stage = StageResult(stage_name="graph", status="running")
        graph_files = [file_map[file_path] for file_path in sorted(impacted_files) if file_path in file_map]
        self._log_progress(f"graph started for {len(graph_files)} impacted files")
        graph_stage.input_summary = {
            "impacted_files": len(graph_files),
            "touched_files": len(touched_files),
        }
        if graph_files:
            build_graph(self.kuzu, graph_files, self.symbols_by_file)
        graph_stage.output_summary = {
            "edge_count": self.kuzu.count_edges(),
            "rebuilt_files": len(graph_files),
        }
        graph_stage.status = "completed"
        graph_stage.completed_at = time()
        summary.stage_results.append(graph_stage)
        self._log_progress(f"graph completed: {graph_stage.output_summary['edge_count']} edges")

        embed_stage = StageResult(stage_name="embed", status="running")
        self._log_progress(f"embed started for {len(changed_files)} files")
        existing_chunk_count = len(self.duckdb.fetch_all("chunks"))
        new_chunk_count = 0
        embedding_runtime = get_embedding_runtime_info(self.settings.embedding_model, self.settings.embedding_device)
        self._log_progress(
            f"embedding runtime: backend={embedding_runtime['backend']} requested={embedding_runtime['requested_device']} resolved={embedding_runtime['resolved_device']}"
        )
        embed_stage.input_summary = {"files_to_embed": len(changed_files)}
        for index, file_path in enumerate(changed_files, start=1):
            file_record = file_map[file_path]
            chunks = build_chunks(self.settings.repo_root, file_record.path, self.symbols_by_file.get(file_record.path, []))
            new_chunk_count += len(chunks)
            for chunk in chunks:
                self.duckdb.insert_chunk(asdict(chunk))
            embed_chunks(
                self.vector_store,
                chunks,
                model_name=self.settings.embedding_model,
                batch_size=self.settings.embedding_batch_size,
                max_length=self.settings.embedding_max_length,
                device=self.settings.embedding_device,
            )
            if self._should_log_index(index, len(changed_files)):
                self._log_progress(
                    f"embed progress: {index}/{len(changed_files)} files, {new_chunk_count} new chunks so far ({file_record.path})"
                )
        total_chunks = existing_chunk_count + new_chunk_count
        embed_stage.output_summary = {
            "chunk_count": total_chunks,
            "updated_files": len(changed_files),
            "new_chunks": new_chunk_count,
            "embedding_runtime": embedding_runtime,
        }
        embed_stage.status = "completed"
        embed_stage.completed_at = time()
        summary.stage_results.append(embed_stage)
        self._log_progress(f"embed completed: {new_chunk_count} new chunks, {total_chunks} total chunks")

        review_stage = StageResult(stage_name="review", status="running")
        review_jobs = build_review_jobs(plan["files_to_review"], run_id=summary.run_id)
        self._log_progress(f"review started for {len(review_jobs)} jobs")
        review_stage.input_summary = {
            "files_to_review": len(plan["files_to_review"]),
            "review_types": len(self.reviewers),
        }
        for job in review_jobs:
            self.duckdb.insert_review_job(asdict(job))
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
        self.latest_observations, self.latest_findings = merge_findings(review_results)
        for observation in self.latest_observations:
            self.duckdb.insert_review_observation(asdict(observation))
        for finding in self.latest_findings:
            record = asdict(finding)
            existing = self.duckdb.fetch_finding_by_fingerprint(record["fingerprint"])
            if existing is not None:
                record["finding_id"] = existing["finding_id"]
                record["first_seen_at"] = existing["first_seen_at"]
                record["occurrence_count"] = existing["occurrence_count"] + record["occurrence_count"]
            record["source_review_types"] = json.dumps(record["source_review_types"])
            self.duckdb.upsert_finding(record)
        review_stage.output_summary = {
            "job_count": len(review_jobs),
            "reviewed_files": len(plan["files_to_review"]),
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
        self.duckdb.upsert_run(
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
        summary.technical_summary = generate_run_summary(
            self.settings,
            summary,
            self.latest_findings,
            self.latest_agent_analyses,
            audience="technical",
        )
        summary.llm_summary = summary.technical_summary
        summary.layperson_summary = generate_run_summary(
            self.settings,
            summary,
            self.latest_findings,
            self.latest_agent_analyses,
            audience="layperson",
        )
        summary.report_paths = write_run_reports(
            self.settings.data_dir,
            summary.run_id,
            summary.technical_summary,
            summary.layperson_summary,
        )
        self._log_progress(f"reports written: {summary.report_paths}")
        summary.promoted = True
        self._log_progress(f"run {summary.run_id} completed")
        return summary
 
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
