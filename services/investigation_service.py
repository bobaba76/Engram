"""Investigation service — facade re-exporting public API and orchestrating codebase investigation.

This module was decomposed from a 2255-line monolith into:
- investigation_constants.py: token sets, stopwords, behavior trace config
- investigation_question_analysis.py: intent, query rewrite, guardrails, search task
- investigation_discovery.py: cheap symbol discovery, alternate anchors, lexical terms
- investigation_ranking.py: hit classification, file relevance, evidence, graph signal
- investigation_guidance.py: guidance profile, answer synthesis, behavior trace summaries

This file re-exports the public API and contains the main ``investigate_codebase`` orchestrator.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from mcp_server.resolvers import resolve_tool_target
from services.app_context_service import app_context
from services.feature_context_service import feature_context
from services.source_retrieval_service import get_source_context
from services.unified_context_service import get_unified_context

# Re-export public API
from services.investigation_question_analysis import (
    _behavior_trace_features,
    _broad_question_guardrails,
    _query_rewrite,
    _question_intent,
    investigation_search_task,
)
from services.investigation_discovery import (
    alternate_discovery_anchors,
    broad_lexical_search_terms,
    cheap_symbol_discovery,
    cheap_symbol_discovery_terms,
    cheap_ui_symbol_discovery,
    cheap_ui_symbol_discovery_terms,
    should_allow_broad_vector_fallback,
)
from services.investigation_ranking import (
    _architecture_summary,
    _boost_call_chain_files,
    _call_chain_evidence,
    _classify_search_hits,
    _compact_hits,
    _data_flow_summary,
    _evidence_items,
    _exploratory_file_groups,
    _file_relevance,
    _graph_frontend_signal,
    _investigation_strength,
    _is_exploratory_intent,
    _is_frontend_file,
    _is_generic_target,
    _prioritize_search_hits,
    _retrieval_diagnostics,
    _should_retry_investigation,
    _unique_strings,
)
from services.investigation_guidance import (
    _behavior_trace_summary,
    _change_guidance,
    _guidance_next_steps,
    _guidance_next_tools,
    _guidance_profile,
    _guidance_summary,
    _merge_behavior_trace_summaries,
    _synthesize_answer,
)
from services.investigation_discovery import _alternate_seed_targets
from services.investigation_question_analysis import (
    _app_context_target,
    _best_seed_target,
    _should_enrich_behavior_trace,
)

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore

logger = logging.getLogger(__name__)


def investigate_codebase(
    repo_root: Path,
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    question: str,
    search_payload: dict[str, object] | None = None,
    limit: int = 5,
    verbose: bool = False,
) -> dict[str, object]:
    _t0 = time.monotonic()
    normalized_question = str(question or "").strip()
    payload_search_plan = search_payload.get("investigation_search_plan", {}) if isinstance(search_payload, dict) else {}
    search_task, search_plan = investigation_search_task(normalized_question, limit=limit)
    if isinstance(payload_search_plan, dict):
        merged_plan = dict(search_plan)
        merged_plan.update({key: value for key, value in payload_search_plan.items() if value is not None})
        search_plan = merged_plan
    intent = search_plan["intent"] if isinstance(search_plan.get("intent"), dict) else _question_intent(normalized_question)
    query_rewrite = search_plan["query_rewrite"] if isinstance(search_plan.get("query_rewrite"), dict) else _query_rewrite(normalized_question, intent)
    guardrails = search_plan["guardrails"] if isinstance(search_plan.get("guardrails"), dict) else _broad_question_guardrails(normalized_question, intent, query_rewrite, limit)
    search_payload = search_payload or {"compact_results": []}
    search_hits = _compact_hits(search_payload, limit=int(guardrails.get("search_limit", limit) or limit))
    diagnostics = _retrieval_diagnostics(search_payload)
    warnings = list(guardrails.get("warnings", [])) if isinstance(guardrails.get("warnings"), list) else []
    if _is_exploratory_intent(intent) and bool(diagnostics.get("exploratory_lightweight_path")):
        behavior_features = _behavior_trace_features(normalized_question, query_rewrite, limit=2)
        behavior_summaries: list[dict[str, object]] = []
        warnings.append("Exploratory feature tracing used a lightweight budget to avoid timeouts.")
        for feature_name in behavior_features:
            try:
                feature_payload = feature_context(
                    repo_root,
                    duckdb_store,
                    kuzu_store,
                    feature=feature_name,
                    limit=max(6, limit + 1),
                    lightweight=True,
                )
            except Exception:
                logger.debug("investigation: feature_context failed for feature %r", feature_name, exc_info=True)
                continue
            behavior_summaries.append(_behavior_trace_summary(feature_payload))
        behavior_trace = _merge_behavior_trace_summaries(behavior_summaries, limit=6) if behavior_summaries else {"feature": "", "attempted_features": [], "top_files": [], "top_routes": [], "top_processes": [], "file_kinds": {}, "role_groups": {}, "file_count": 0, "partial": True}
        if behavior_trace.get("top_files") or behavior_trace.get("top_routes") or behavior_trace.get("top_processes"):
            warnings.append("Behavior trace surfaced exploratory candidate files for follow-up.")
        if behavior_trace.get("attempted_features"):
            warnings.append(f"Behavior trace attempted exploratory anchors: {', '.join(behavior_trace.get('attempted_features', [])[:3])}.")
        ranked_files = [
            {
                "file": file_path,
                "score": max(3.0 - (index * 0.35), 1.0),
                "seed_hits": 0,
                "expanded_hits": 0,
                "snippet_hits": 0,
                "app_context": False,
                "reasons": ["behavior trace candidate", "exploratory feature trace surfaced a frontend candidate"] if _is_frontend_file(file_path) else ["behavior trace candidate"],
                "lines": [],
            }
            for index, file_path in enumerate(behavior_trace.get("top_files", [])[:8])
        ]
        architecture = {
            "caller_count": 0,
            "callee_count": 0,
            "top_neighbors": [],
            "top_routes": behavior_trace.get("top_routes", [])[:6] if isinstance(behavior_trace.get("top_routes", []), list) else [],
            "top_processes": behavior_trace.get("top_processes", [])[:6] if isinstance(behavior_trace.get("top_processes", []), list) else [],
            "file_kinds": behavior_trace.get("file_kinds", {}) if isinstance(behavior_trace.get("file_kinds", {}), dict) else {},
            "dependency_counts": {},
            "graph_edge_count": 0,
        }
        exploratory_groups = _exploratory_file_groups(ranked_files, behavior_trace, architecture)
        trace_roles = behavior_trace.get("role_groups", {}) if isinstance(behavior_trace.get("role_groups", {}), dict) else {}
        ordered_paths: list[str] = []
        for source_groups in (trace_roles, exploratory_groups):
            for group_name in ("page_files", "shared_ui_files", "backend_files"):
                group_values = source_groups.get(group_name, []) if isinstance(source_groups, dict) else []
                if isinstance(group_values, list):
                    for file_path in group_values:
                        normalized = str(file_path or "").strip()
                        if normalized and normalized not in ordered_paths:
                            ordered_paths.append(normalized)
        if ordered_paths:
            weighted_ranked_files: list[dict[str, object]] = []
            for index, file_path in enumerate(ordered_paths[:8]):
                reasons = ["behavior trace candidate"]
                if file_path in exploratory_groups.get("page_files", []):
                    reasons.extend(["exploratory role: page owner", "page-owner bias: prompt asks for the owning page first"])
                elif file_path in exploratory_groups.get("shared_ui_files", []):
                    reasons.extend(["exploratory role: shared period state", "secondary-role ordering: shared UI follows the page owner"])
                elif file_path in exploratory_groups.get("backend_files", []):
                    reasons.extend(["exploratory role: backend flow", "secondary-role ordering: backend flow follows page and shared UI"])
                if _is_frontend_file(file_path):
                    reasons.append("exploratory feature trace surfaced a frontend candidate")
                weighted_ranked_files.append(
                    {
                        "file": file_path,
                        "score": max(4.5 - (index * 0.4), 1.0),
                        "seed_hits": 0,
                        "expanded_hits": 0,
                        "snippet_hits": 0,
                        "app_context": False,
                        "reasons": reasons,
                        "lines": [],
                    }
                )
            ranked_files = weighted_ranked_files
        evidence = _evidence_items(
            [],
            [],
            [],
            {"compact_summary": {"top_neighbors": []}},
            {"compact_summary": {"top_files": behavior_trace.get("top_files", [])[:6] if isinstance(behavior_trace.get("top_files", []), list) else []}},
            ranked_files=ranked_files,
            intent=intent,
        )
        top_target = str(exploratory_groups.get("page_files", [behavior_trace.get("feature", "")])[:1][0] if exploratory_groups.get("page_files") else behavior_trace.get("feature", "") or normalized_question)
        graph_signal = {"frontend_graph_hit_count": 0, "frontend_graph_files": [], "top_frontend_ranked_files": [item.get("file", "") for item in ranked_files[:3]], "frontend_file_count": 0, "graph_edge_count": 0, "has_indirect_frontend_path": False}
        answer, confidence, open_questions = _synthesize_answer(
            normalized_question,
            top_target,
            ranked_files,
            evidence,
            diagnostics,
            architecture,
            [],
            [],
            intent,
            graph_signal,
            exploratory_groups=exploratory_groups,
        )
        next_tools = [{"tool": "feature_context", "target": behavior_trace.get("feature") or normalized_question, "why": "Trace exploratory feature or behavior context across files, routes, and processes."}]
        if ranked_files:
            next_tools.append({"tool": "get_source_context", "why": "Read exact source snippets for the strongest candidate file or symbol."})
        return {
            "question": normalized_question,
            "target": top_target,
            "intent": intent,
            "query_rewrite": query_rewrite,
            "seed_target": search_task,
            "search_task": {"task": search_task, "source": search_plan.get("task_source", "question")},
            "guardrails": guardrails,
            "app_context_target": {"target": behavior_trace.get("feature", "") or search_task, "source": "behavior_trace_feature"},
            "investigation_passes": {"attempted_seeds": [search_task], "retry_used": False, "retry_reason": "", "alternate_discovery_anchors": []},
            "warnings": warnings,
            "answer": answer,
            "confidence": confidence,
            "evidence": evidence,
            "evidence_breakdown": {"seed_hits": [], "expanded_hits": [], "source_snippets": []},
            "retrieval_diagnostics": diagnostics,
            "ranked_files": ranked_files,
            "architecture_summary": architecture,
            "graph_signal": graph_signal,
            "data_flow_summary": [],
            "guidance_summary": {"ambiguous": True, "weak_primary": False, "evidence_count": len(evidence), "has_graph_context": False, "has_routes": bool(architecture["top_routes"]), "has_processes": bool(architecture["top_processes"]), "intent": intent, "top_file": ranked_files[0]["file"] if ranked_files else "", "top_file_reasons": ranked_files[0]["reasons"][:3] if ranked_files else [], "retrieval_signal_strength": {}},
            "exploratory_groups": exploratory_groups,
            "behavior_trace": behavior_trace,
            "change_guidance": {"related_files": [item.get("file", "") for item in ranked_files[:6]], "recommended_tests": [], "likely_impact_targets": [], "test_count": 0},
            "discovered_symbols": [],
            "open_questions": open_questions,
            "next_tools": next_tools,
            "answer_outline": [
                f"Exploratory page files: {', '.join(exploratory_groups.get('page_files', [])[:3])}" if exploratory_groups.get("page_files") else "Exploratory page files: none",
                f"Exploratory shared UI files: {', '.join(exploratory_groups.get('shared_ui_files', [])[:3])}" if exploratory_groups.get("shared_ui_files") else "Exploratory shared UI files: none",
                f"Exploratory backend files: {', '.join(exploratory_groups.get('backend_files', [])[:3])}" if exploratory_groups.get("backend_files") else "Exploratory backend files: none",
            ],
            "next_steps": ["Open the top exploratory files first to confirm the owning page, shared period state, and backend flow."],
            "compact_summary": {
                "target": top_target,
                "question": normalized_question,
                "confidence": confidence,
                "intent": intent,
                "query_rewrite": query_rewrite,
                "seed_target": search_task,
                "search_task": {"task": search_task, "source": search_plan.get("task_source", "question")},
                "guardrails": guardrails,
                "warnings": warnings,
                "top_files": [item.get("file", "") for item in ranked_files[:8]],
                "top_symbols": [],
                "snippet_count": 0,
                "evidence_count": len(evidence),
                "seed_hit_count": 0,
                "expanded_hit_count": 0,
                "behavior_trace": behavior_trace,
                "exploratory_groups": exploratory_groups,
                "status": "partial",
                "next_tools": next_tools,
                "partial": True,
            },
        }
    logger.debug("investigate_codebase: exploratory path completed in %.1fs", time.monotonic() - _t0)
    seed_hits, expanded_hits = _classify_search_hits(search_hits)
    discovered_symbols: list[dict[str, object]] = []
    alternate_anchors: list[str] = []
    if bool(guardrails.get("broad_question")) and not search_hits:
        discovered_symbols = cheap_symbol_discovery(duckdb_store, search_task, query_rewrite, limit=5)
        if not discovered_symbols:
            alternate_anchors = alternate_discovery_anchors(search_task, query_rewrite, app_target=str(search_task or ""), limit=2)
            if alternate_anchors:
                seen_keys = {
                    (
                        str(symbol.get("qualified_name", "") or ""),
                        str(symbol.get("file_path", "") or ""),
                        symbol.get("start_line"),
                        symbol.get("end_line"),
                    )
                    for symbol in discovered_symbols
                }
                for anchor in alternate_anchors:
                    remaining = max(1, 5 - len(discovered_symbols))
                    for symbol in cheap_symbol_discovery(duckdb_store, anchor, query_rewrite, limit=remaining):
                        key = (
                            str(symbol.get("qualified_name", "") or ""),
                            str(symbol.get("file_path", "") or ""),
                            symbol.get("start_line"),
                            symbol.get("end_line"),
                        )
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        discovered_symbols.append(symbol)
                        if len(discovered_symbols) >= 5:
                            break
                    if len(discovered_symbols) >= 5:
                        break
        if not discovered_symbols:
            discovered_symbols = cheap_ui_symbol_discovery(duckdb_store, search_task, query_rewrite, limit=5)
        if discovered_symbols:
            warnings.append("Broad search found nearby symbols via cheap lexical discovery.")
        if alternate_anchors:
            warnings.append(f"Broad search also tried alternate anchors: {', '.join(alternate_anchors)}.")
        if discovered_symbols and any(str(item.get("discovery_source", "")) == "chunk_content" for item in discovered_symbols):
            warnings.append("Weak UI-like target was expanded through nearby chunk text to surface candidate symbols.")
    expanded_hit_limit = int(guardrails.get("expanded_hit_limit", max(limit + 1, 6)) or max(limit + 1, 6))
    if len(expanded_hits) > expanded_hit_limit:
        expanded_hits = expanded_hits[:expanded_hit_limit]
        warnings.append("Expanded retrieval was capped to keep the investigation responsive.")
    seed_target = _best_seed_target(normalized_question, query_rewrite, seed_hits, expanded_hits)
    if bool(guardrails.get("broad_question")) and str(search_plan.get("task_source", "question")) != "question":
        narrowed_task = str(search_task or "").strip()
        if narrowed_task:
            seed_target = narrowed_task
            warnings.append(f"Investigation was anchored to narrowed search term '{narrowed_task}'.")

    resolution = resolve_tool_target(duckdb_store, repo_root, target=seed_target, limit=limit)
    resolved_target = str(resolution.get("resolved_target") or seed_target)
    # Fallback: if the resolved target didn't match a real symbol but seed hits
    # contain actual symbols, use the best seed hit as the resolved target.
    # This is critical for flow-intent ("how") questions where we need a real
    # symbol to traverse the call chain.
    resolution_matches = resolution.get("matches", []) if isinstance(resolution, dict) else []
    has_real_symbol = bool(resolution_matches) and any(
        str(item.get("uid") or "").strip() for item in resolution_matches if isinstance(item, dict)
    )
    if not has_real_symbol:
        # Build a list of candidate targets to try resolving, ordered by
        # token overlap with the question so semantically closer symbols win.
        primary_intent = str(intent.get("primary", "general") or "general")
        question_tokens = {token for token in re.split(r"[^a-zA-Z0-9]+", normalized_question.lower()) if token and len(token) >= 3}
        test_intent = primary_intent == "tests" or "tests" in (intent.get("secondary", []) if isinstance(intent.get("secondary", []), list) else [])
        def _hit_relevance(hit: dict[str, object]) -> tuple[int, int]:
            hit_target = str(hit.get("target") or "").lower()
            if not hit_target:
                return (0, 0)
            split_target = re.sub(r"([a-z])([A-Z])", r"\1 \2", hit_target).replace("_", " ").lower()
            target_tokens = {token for token in re.split(r"[^a-zA-Z0-9]+", split_target) if token}
            token_overlap = len(question_tokens & target_tokens)
            # Production-code bias: penalize test files for non-test-intent questions
            hit_file = str(hit.get("file") or hit.get("file_path") or "").replace("\\", "/").lower()
            is_test = any(marker in hit_file for marker in ("/tests/", "/test/", "/__tests__/")) or hit_file.startswith(("tests/", "test/", "__tests__/"))
            stem = hit_file.rsplit("/", 1)[-1].rsplit(".", 1)[0] if hit_file else ""
            is_test = is_test or stem.startswith("test_") or stem.endswith("_test") or stem.endswith("_tests") or stem.endswith("test") or stem.endswith("tests") or stem.endswith("spec") or stem.endswith("specs")
            test_penalty = 0 if test_intent else (-1 if is_test else 0)
            return (token_overlap, test_penalty)

        # Collect candidates from seed hits and, for flow-intent questions,
        # also from cheap symbol discovery (which may find symbols that the
        # search missed due to the search_limit cap).
        fallback_candidates: list[dict[str, object]] = list(seed_hits)
        if primary_intent == "flow":
            flow_discovered = cheap_symbol_discovery(duckdb_store, search_task, query_rewrite, limit=5)
            for sym in flow_discovered:
                if isinstance(sym, dict) and sym not in fallback_candidates:
                    fallback_candidates.append(sym)
            # Also try discovery with multi-word combinations from the question's
            # core terms, since the search_task may have narrowed away the
            # terms that actually match real symbols (e.g. "dead code" → detect_dead_code).
            core_terms = query_rewrite.get("core_terms", [])
            if isinstance(core_terms, list) and len(core_terms) >= 2:
                # Try pairs of core terms that look like they could form a symbol name
                for i in range(len(core_terms)):
                    for j in range(i + 1, min(i + 3, len(core_terms))):
                        pair = f"{core_terms[i]} {core_terms[j]}"
                        pair_rewrite = {"core_terms": core_terms, "symbol_terms": [core_terms[i], core_terms[j]], "route_terms": [], "file_terms": [], "search_seeds": [pair], "rewritten_queries": [pair], "normalized_question": normalized_question}
                        pair_discovered = cheap_symbol_discovery(duckdb_store, pair, pair_rewrite, limit=3)
                        for sym in pair_discovered:
                            if isinstance(sym, dict) and sym not in fallback_candidates:
                                fallback_candidates.append(sym)

        sorted_candidates = sorted(fallback_candidates, key=_hit_relevance, reverse=True)
        for hit in sorted_candidates:
            hit_target = str(hit.get("target") or hit.get("qualified_name") or "").strip()
            if hit_target and hit_target != resolved_target and not _is_generic_target(hit_target):
                retry_resolution = resolve_tool_target(duckdb_store, repo_root, target=hit_target, limit=limit)
                retry_matches = retry_resolution.get("matches", []) if isinstance(retry_resolution, dict) else []
                if retry_matches and any(str(item.get("uid") or "").strip() for item in retry_matches if isinstance(item, dict)):
                    resolution = retry_resolution
                    resolved_target = str(retry_resolution.get("resolved_target") or hit_target)
                    warnings.append(f"Resolved target was replaced with search hit '{resolved_target}' for deeper analysis.")
                    break
    app_target, app_target_source = _app_context_target(normalized_question, resolved_target, query_rewrite)
    if bool(guardrails.get("broad_question")) and _is_generic_target(resolved_target) and app_target_source in {"file_term", "route_term", "symbol_term"}:
        narrowed_target = str(app_target or "").strip()
        if narrowed_target and narrowed_target != resolved_target:
            if narrowed_target == seed_target:
                resolved_target = narrowed_target
            else:
                resolution = resolve_tool_target(duckdb_store, repo_root, target=narrowed_target, limit=limit)
                resolved_target = str(resolution.get("resolved_target") or narrowed_target)
                if _is_generic_target(resolved_target):
                    resolved_target = narrowed_target
            warnings.append(f"Generic target resolution was replaced with narrowed term '{narrowed_target}'.")
    search_hits = _prioritize_search_hits(search_hits, seed_target, resolved_target, intent=intent)
    seed_hits, expanded_hits = _classify_search_hits(search_hits)
    app = app_context(repo_root, duckdb_store, kuzu_store, target=app_target, limit=6)
    source_context = get_source_context(duckdb_store, resolved_target, limit=3, repo_root=repo_root)
    unified = get_unified_context(duckdb_store, kuzu_store, resolved_target, max_matches=3, neighborhood_depth=1)
    behavior_trace = {"feature": "", "attempted_features": [], "top_files": [], "top_routes": [], "top_processes": [], "file_kinds": {}, "role_groups": {}, "file_count": 0, "partial": False}
    if _should_enrich_behavior_trace(normalized_question, intent, guardrails):
        try:
            exploratory_intent = _is_exploratory_intent(intent)
            lightweight_behavior = bool(exploratory_intent and (guardrails.get("broad_question") or len(_question_intent(normalized_question).get("tokens", [])) >= 8))
            broad_behavior_budget = 2 if lightweight_behavior else 3
            behavior_features = _behavior_trace_features(normalized_question, query_rewrite, limit=broad_behavior_budget)
            behavior_summaries = [
                _behavior_trace_summary(
                    feature_context(
                        repo_root,
                        duckdb_store,
                        kuzu_store,
                        feature=feature,
                        limit=4 if lightweight_behavior else 6,
                        lightweight=lightweight_behavior,
                    )
                )
                for feature in behavior_features
            ]
            behavior_trace = _merge_behavior_trace_summaries(behavior_summaries, limit=6)
            if lightweight_behavior:
                behavior_trace["partial"] = True
                warnings.append("Exploratory feature tracing used a lightweight budget to avoid timeouts.")
        except Exception:
            logger.warning("investigation: behavior trace failed", exc_info=True)
            behavior_trace = {"feature": "", "attempted_features": [], "top_files": [], "top_routes": [], "top_processes": [], "file_kinds": {}, "role_groups": {}, "file_count": 0, "partial": False}
    snippets = source_context.get("compact_results", [])
    snippets_list = [item for item in snippets if isinstance(item, dict)] if isinstance(snippets, list) else []
    attempted_passes = [seed_target]
    retry_used = False
    retry_reason = ""
    if bool(guardrails.get("allow_retry")) and _should_retry_investigation(seed_hits, expanded_hits, snippets_list):
        retry_reason = "weak_primary" if expanded_hits else "no_direct_evidence"
        current_strength = _investigation_strength(seed_hits, expanded_hits, snippets_list, resolved_target)
        retry_limit = int(guardrails.get("retry_limit", 4) or 4)
        for alternate_seed in _alternate_seed_targets(seed_target, query_rewrite, limit=retry_limit):
            attempted_passes.append(alternate_seed)
            retry_resolution = resolve_tool_target(duckdb_store, repo_root, target=alternate_seed, limit=limit)
            retry_target = str(retry_resolution.get("resolved_target") or alternate_seed)
            retry_source_context = get_source_context(duckdb_store, retry_target, limit=3, repo_root=repo_root)
            retry_snippets = retry_source_context.get("compact_results", [])
            retry_snippets_list = [item for item in retry_snippets if isinstance(item, dict)] if isinstance(retry_snippets, list) else []
            retry_strength = _investigation_strength(seed_hits, expanded_hits, retry_snippets_list, retry_target)
            if retry_strength > current_strength:
                resolution = retry_resolution
                resolved_target = retry_target
                source_context = retry_source_context
                snippets_list = retry_snippets_list
                snippets = retry_snippets
                unified = get_unified_context(duckdb_store, kuzu_store, resolved_target, max_matches=3, neighborhood_depth=1)
                retry_used = True
                break
    elif _should_retry_investigation(seed_hits, expanded_hits, snippets_list):
        retry_reason = "guardrail_skipped"
        warnings.append("Alternate-seed retries were skipped because the question is broad.")

    app_summary = app.get("compact_summary", {}) if isinstance(app, dict) else {}
    unified_summary = unified.get("compact_summary", {}) if isinstance(unified, dict) else {}
    evidence_limit = int(guardrails.get("evidence_limit", max(limit + 3, 8)) or max(limit + 3, 8))
    ranked_files = _file_relevance(
        search_hits,
        snippets_list,
        app,
        behavior_trace=behavior_trace,
        question=normalized_question,
        intent=intent,
        limit=evidence_limit,
    )
    key_files = [str(item.get("file", "")) for item in ranked_files if str(item.get("file", "")).strip()]
    architecture = _architecture_summary(unified, app)
    exploratory_groups = _exploratory_file_groups(ranked_files, behavior_trace, architecture)
    graph_signal = _graph_frontend_signal(search_hits, ranked_files, architecture)
    data_flow_points = _data_flow_summary(architecture)
    evidence = _evidence_items(
        seed_hits,
        expanded_hits,
        snippets_list,
        unified,
        app,
        ranked_files=ranked_files,
        intent=intent,
    )

    # Call-chain traversal for flow-intent questions ("how does X work?")
    call_chain_evidence: list[dict[str, object]] = []
    primary_intent = str(intent.get("primary", "general") or "general")
    if primary_intent == "flow" and isinstance(unified, dict):
        # In compact mode, callees are in categorized_references.CALLS.outgoing.
        # In full mode, they're also available as unified["callees"].
        callees = unified.get("callees", [])
        if not callees:
            cat_refs = unified.get("categorized_references", {})
            if isinstance(cat_refs, dict):
                calls_ref = cat_refs.get("CALLS", {})
                if isinstance(calls_ref, dict):
                    callees = calls_ref.get("outgoing", [])
        if isinstance(callees, list) and callees:
            snippets_by_callee: dict[str, list[dict[str, object]]] = {}
            seen_callees: set[str] = set()
            for edge in callees:
                if not isinstance(edge, dict):
                    continue
                callee_name = str(edge.get("target") or "").strip()
                if not callee_name or callee_name in seen_callees:
                    continue
                relation = str(edge.get("relation") or "").upper()
                if relation not in {"CALLS", "REFERENCES"}:
                    continue
                if callee_name.startswith("property:"):
                    continue
                seen_callees.add(callee_name)
                try:
                    callee_source = get_source_context(duckdb_store, callee_name, limit=1, repo_root=repo_root)
                    callee_snippets = callee_source.get("compact_results", [])
                    if isinstance(callee_snippets, list):
                        snippets_by_callee[callee_name] = [item for item in callee_snippets if isinstance(item, dict)]
                except Exception:
                    logger.debug("investigation: source context failed for callee %r", callee_name, exc_info=True)
            call_chain_evidence = _call_chain_evidence(unified, snippets_by_callee, max_items=5)
            if call_chain_evidence:
                evidence.extend(call_chain_evidence)
                ranked_files = _boost_call_chain_files(ranked_files, call_chain_evidence)
                # Re-sort by score after boosting
                ranked_files.sort(key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
                callee_names = [str(item.get("target") or "") for item in call_chain_evidence[:3]]
                warnings.append(f"Call-chain traversal surfaced implementation functions: {', '.join(callee_names)}.")

    if len(evidence) > evidence_limit:
        evidence = evidence[:evidence_limit]
        warnings.append("Evidence was truncated to keep the result compact.")
    answer, confidence, open_questions = _synthesize_answer(
        normalized_question,
        resolved_target,
        ranked_files,
        evidence,
        diagnostics,
        architecture,
        seed_hits,
        expanded_hits,
        intent,
        graph_signal,
        exploratory_groups=exploratory_groups,
        call_chain_evidence=call_chain_evidence,
    )
    if not evidence and discovered_symbols:
        discovered_names = [
            str(item.get("qualified_name") or item.get("name") or "").strip()
            for item in discovered_symbols
            if str(item.get("qualified_name") or item.get("name") or "").strip()
        ][:3]
        if discovered_names:
            answer += f" Cheap symbol discovery found nearby candidates: {', '.join(discovered_names)}."
        open_questions = ["No direct evidence was found, but nearby symbols may help narrow the follow-up."]
    if behavior_trace.get("top_files"):
        trace_files = ", ".join(str(path) for path in behavior_trace.get("top_files", [])[:3])
        answer += f" Feature trace candidates include {trace_files}."
        if "Behavior trace surfaced exploratory candidate files for follow-up." not in warnings:
            warnings.append("Behavior trace surfaced exploratory candidate files for follow-up.")
    if behavior_trace.get("attempted_features"):
        attempted = ", ".join(str(item) for item in behavior_trace.get("attempted_features", [])[:3])
        warnings.append(f"Behavior trace attempted exploratory anchors: {attempted}.")
    profile = _guidance_profile(resolution, diagnostics, seed_hits, expanded_hits, snippets_list, ranked_files, architecture, intent, graph_signal)
    next_steps = _guidance_next_steps(profile, resolved_target, normalized_question)
    if unified_summary.get("caller_count") or unified_summary.get("callee_count"):
        if "Review callers/callees from unified_context." not in next_steps:
            next_steps.append("Review callers/callees from unified_context.")
    next_tools = _guidance_next_tools(profile, resolved_target, normalized_question)
    if behavior_trace.get("top_files") or behavior_trace.get("top_routes") or behavior_trace.get("top_processes"):
        feature_hint_target = str(behavior_trace.get("feature") or normalized_question)
        feature_hint = {"tool": "feature_context", "target": feature_hint_target, "why": "Trace exploratory feature or behavior context across files, routes, and processes."}
        if feature_hint not in next_tools:
            next_tools.insert(0, feature_hint)
    guidance_summary = _guidance_summary(profile)
    change_guidance = _change_guidance(duckdb_store, resolved_target, ranked_files, unified_summary, app_summary)

    result = {
        "question": normalized_question,
        "target": resolved_target,
        "intent": intent,
        "query_rewrite": query_rewrite,
        "seed_target": seed_target,
        "search_task": {"task": search_task, "source": search_plan.get("task_source", "question")},
        "guardrails": guardrails,
        "app_context_target": {"target": app_target, "source": app_target_source},
        "investigation_passes": {
            "attempted_seeds": attempted_passes,
            "retry_used": retry_used,
            "retry_reason": retry_reason,
            "alternate_discovery_anchors": alternate_anchors,
        },
        "warnings": warnings,
        "answer": answer,
        "confidence": confidence,
        "evidence": evidence,
        "evidence_breakdown": {
            "seed_hits": seed_hits,
            "expanded_hits": expanded_hits,
            "source_snippets": snippets_list[:6],
            "call_chain": call_chain_evidence,
        },
        "retrieval_diagnostics": diagnostics,
        "ranked_files": ranked_files,
        "architecture_summary": architecture,
        "graph_signal": graph_signal,
        "data_flow_summary": data_flow_points,
        "guidance_summary": guidance_summary,
        "exploratory_groups": exploratory_groups,
        "behavior_trace": behavior_trace,
        "change_guidance": change_guidance,
        "discovered_symbols": discovered_symbols,
        "open_questions": open_questions,
        "next_tools": next_tools,
        "resolution": resolution,
        "answer_outline": [
            f"Primary target: {resolved_target}",
            f"Key files: {', '.join(key_files[:6])}" if key_files else "Key files: no strong file candidates",
            f"Search hits: {len(search_hits)} ({len(seed_hits)} seed, {len(expanded_hits)} expanded)",
            f"Snippet hits: {len(snippets_list)}",
            f"Cheap symbol candidates: {len(discovered_symbols)}",
            f"Alternate anchors tried: {', '.join(alternate_anchors)}" if alternate_anchors else "Alternate anchors tried: none",
            f"Suggested tests: {change_guidance.get('test_count', 0)}",
            f"Behavior trace files: {len(behavior_trace.get('top_files', []))}",
            f"Behavior anchors tried: {', '.join(behavior_trace.get('attempted_features', [])[:3])}" if behavior_trace.get("attempted_features") else "Behavior anchors tried: none",
            f"Exploratory page files: {', '.join(exploratory_groups.get('page_files', [])[:2])}" if exploratory_groups.get("page_files") else "Exploratory page files: none",
        ] + data_flow_points[:3],
        "next_steps": next_steps,
        "compact_summary": {
            "target": resolved_target,
            "question": normalized_question,
            "confidence": confidence,
            "intent": intent,
            "query_rewrite": query_rewrite,
            "seed_target": seed_target,
            "search_task": {"task": search_task, "source": search_plan.get("task_source", "question")},
            "guardrails": guardrails,
            "app_context_target": {"target": app_target, "source": app_target_source},
            "investigation_passes": {
                "attempted_seeds": attempted_passes,
                "retry_used": retry_used,
                "retry_reason": retry_reason,
                "alternate_discovery_anchors": alternate_anchors,
            },
            "warnings": warnings,
            "top_files": key_files[:8],
            "top_file_reasons": {str(item.get("file", "")): item.get("reasons", [])[:3] for item in ranked_files[:5]},
            "top_symbols": _unique_strings([item.get("target") for item in search_hits[:5] if item.get("target")]),
            "discovered_symbols": discovered_symbols[:5],
            "snippet_count": len(snippets_list),
            "evidence_count": len(evidence),
            "seed_hit_count": len(seed_hits),
            "expanded_hit_count": len(expanded_hits),
            "guidance": guidance_summary,
            "behavior_trace": behavior_trace,
            "exploratory_groups": exploratory_groups,
            "change_guidance": change_guidance,
            "app_files": app_summary.get("top_files", []),
            "top_neighbors": unified_summary.get("top_neighbors", []),
            "graph_signal": graph_signal,
        },
    }
    # Include raw sub-payloads only in verbose mode — these are large
    # (search, source_context, unified_context, app_context are each full
    # tool payloads) and bury the synthesized answer in noise.
    if verbose:
        result["search"] = search_payload
        result["source_context"] = source_context
        result["unified_context"] = unified
        result["app_context"] = app
    else:
        result["verbose_note"] = (
            "Raw sub-payloads (search, source_context, unified_context, app_context) "
            "were omitted to keep the result compact. Pass verbose=true to include them."
        )
    return result
    logger.debug("investigate_codebase: full path completed in %.1fs", time.monotonic() - _t0)
