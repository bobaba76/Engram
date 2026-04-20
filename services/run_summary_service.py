from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib import error, request

from models.config_models import RuntimeConfig
from models.review_models import ReviewAgentAnalysis, ReviewFinding
from models.stage_models import RunSummary

SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}
SUPPRESSED_CATEGORY_HINTS = ("maintainability", "abstraction", "separation of concerns", "single responsibility", "complex")
SPECULATIVE_HINTS = (
    "potential",
    "could",
    "might",
    "may",
    "consider",
    "gracefully",
    "would benefit",
    "if logged or exposed",
    "not provided in the grouped syntheses",
)
CONCRETE_SECURITY_HINTS = (
    "sql injection",
    "hardcoded secret",
    "hardcoded jwt secret",
    "missing input validation",
    "lack of input validation",
    "authentication",
    "authorization",
    "command injection",
    "path traversal",
)


def _path_area(file_path: str) -> str:
    parts = [part for part in str(file_path).replace("\\", "/").split("/") if part]
    if not parts:
        return "unknown"
    if parts[0] in {"backend", "frontend", "electron"}:
        return parts[0]
    return parts[0]


def _finding_specificity_score(finding: ReviewFinding) -> float:
    haystack = " ".join(
        [
            str(finding.title or "").lower(),
            str(finding.description or "").lower(),
            str(finding.suggested_fix or "").lower(),
        ]
    )
    score = 0.0
    if finding.start_line is not None:
        score += 0.2
    if finding.end_line is not None:
        score += 0.1
    if any(hint in haystack for hint in CONCRETE_SECURITY_HINTS):
        score += 0.6
    if "hardcoded" in haystack or "uses string formatting" in haystack or "raises an error" in haystack:
        score += 0.2
    if any(hint in haystack for hint in SPECULATIVE_HINTS):
        score -= 0.45
    if len(str(finding.description or "")) < 80:
        score -= 0.1
    return score


def _finding_rank(finding: ReviewFinding) -> tuple[int, float, int]:
    return (
        SEVERITY_ORDER.get((finding.severity or "low").lower(), 1),
        float(finding.confidence or 0.0) + _finding_specificity_score(finding),
        int(finding.occurrence_count or 1),
    )


def _should_suppress_finding(finding: ReviewFinding) -> bool:
    severity = (finding.severity or "low").lower()
    category = (finding.category or "").lower()
    title = (finding.title or "").lower()
    description = (finding.description or "").lower()
    haystack = " ".join((category, title, description))
    if severity in {"high", "critical"}:
        return False
    return any(hint in haystack for hint in SUPPRESSED_CATEGORY_HINTS)


def _select_summary_findings(findings: list[ReviewFinding], limit: int = 5) -> list[ReviewFinding]:
    deduped: dict[tuple[str, str], ReviewFinding] = {}
    for finding in sorted(findings, key=_finding_rank, reverse=True):
        if _should_suppress_finding(finding):
            continue
        key = (_path_area(finding.file_path), finding.title)
        existing = deduped.get(key)
        if existing is None or _finding_rank(finding) > _finding_rank(existing):
            deduped[key] = finding
    return list(sorted(deduped.values(), key=_finding_rank, reverse=True)[:limit])


def _compact_findings(findings: list[ReviewFinding]) -> list[dict[str, Any]]:
    return [
        {
            "title": finding.title,
            "severity": finding.severity,
            "category": finding.category,
            "file_path": finding.file_path,
            "description": finding.description,
            "suggested_fix": finding.suggested_fix,
            "start_line": finding.start_line,
            "end_line": finding.end_line,
            "confidence": finding.confidence,
            "occurrence_count": finding.occurrence_count,
            "source_review_types": finding.source_review_types,
        }
        for finding in findings
    ]


def _compact_value(value: Any) -> Any:
    if isinstance(value, list):
        if len(value) <= 5:
            return [_compact_value(item) for item in value]
        return {
            "count": len(value),
            "sample": [_compact_value(item) for item in value[:5]],
        }
    if isinstance(value, dict):
        return {key: _compact_value(item) for key, item in value.items()}
    return value


def _select_analysis_summaries(analyses: list[ReviewAgentAnalysis], limit: int = 6) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for analysis in analyses:
        summary = (analysis.summary or "").strip()
        if not summary:
            continue
        selected.append(
            {
                "agent_type": analysis.agent_type,
                "file_path": analysis.file_path,
                "summary": summary[:600],
            }
        )
    return selected[:limit]


def _select_grouped_syntheses(analyses: list[ReviewAgentAnalysis], limit: int = 6) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], dict[str, Any]] = {}
    for analysis in analyses:
        if analysis.agent_type != "grouped_general_review_agent":
            continue
        summary = (analysis.summary or "").strip()
        if not summary:
            continue
        output_json = analysis.output_json or {}
        group_paths = output_json.get("group_file_paths", [])
        if not isinstance(group_paths, list) or not group_paths:
            group_paths = [analysis.file_path]
        normalized_paths = tuple(sorted(str(path) for path in group_paths if str(path).strip()))
        if not normalized_paths:
            normalized_paths = (analysis.file_path,)
        candidate = {
            "agent_type": analysis.agent_type,
            "group_file_paths": list(normalized_paths),
            "anchor_file_path": analysis.file_path,
            "summary": summary[:1200],
        }
        existing = grouped.get(normalized_paths)
        if existing is None or len(candidate["summary"]) > len(existing["summary"]):
            grouped[normalized_paths] = candidate
    grouped_values = list(grouped.values())
    area_buckets: dict[str, list[dict[str, Any]]] = {}
    for item in grouped_values:
        paths = item.get("group_file_paths", [])
        area = _path_area(paths[0] if paths else item.get("anchor_file_path", "unknown"))
        area_buckets.setdefault(area, []).append(item)
    for items in area_buckets.values():
        items.sort(key=lambda candidate: (len(candidate.get("group_file_paths", [])), len(candidate.get("summary", ""))), reverse=True)
    selected: list[dict[str, Any]] = []
    preferred_areas = ["backend", "frontend", "electron"]
    for area in preferred_areas:
        candidates = area_buckets.get(area, [])
        if candidates:
            selected.append(candidates.pop(0))
    remaining = []
    for items in area_buckets.values():
        remaining.extend(items)
    remaining.sort(key=lambda candidate: (len(candidate.get("group_file_paths", [])), len(candidate.get("summary", ""))), reverse=True)
    for item in remaining:
        if len(selected) >= limit:
            break
        if item not in selected:
            selected.append(item)
    return selected[:limit]


def _repo_profile_from_summary(summary: RunSummary) -> dict[str, Any]:
    for stage in summary.stage_results:
        if stage.stage_name != "scan":
            continue
        output_summary = stage.output_summary or {}
        repo_profile = output_summary.get("repo_profile", {})
        if isinstance(repo_profile, dict):
            return repo_profile
    return {}


def build_run_summary_payload(
    summary: RunSummary,
    findings: list[ReviewFinding],
    analyses: list[ReviewAgentAnalysis],
) -> dict[str, Any]:
    selected_findings = _select_summary_findings(findings)
    grouped_syntheses = _select_grouped_syntheses(analyses)
    return {
        "run_id": summary.run_id,
        "run_mode": summary.run_mode,
        "repo_profile": _repo_profile_from_summary(summary),
        "stages": [
            {
                "stage_name": stage.stage_name,
                "status": stage.status,
                "input_summary": _compact_value(stage.input_summary),
                "output_summary": _compact_value(stage.output_summary),
            }
            for stage in summary.stage_results
        ],
        "grouped_syntheses": grouped_syntheses,
        "findings": _compact_findings(selected_findings),
        "analysis_summaries": _select_analysis_summaries(analyses),
        "counts": {
            "finding_count": len(findings),
            "selected_finding_count": len(selected_findings),
            "analysis_count": len(analyses),
            "grouped_synthesis_count": len(grouped_syntheses),
        },
    }


def _build_summary_messages(prompt_payload: dict[str, Any], audience: str) -> list[dict[str, str]]:
    if audience == "layperson":
        return [
            {
                "role": "system",
                "content": (
                    "You generate warm, clear, conversational markdown-friendly summaries for a regular person or vibecoder reviewing a completed code indexing run. "
                    "Return JSON only with keys status, overall_summary, current_state, codebase_areas, issues, next_actions. "
                    "Explain what the application appears to do, how the main parts fit together, what happened in this run, and why the issues matter in practical terms. "
                    "Use repo_profile as primary evidence for the app shape: if it shows frontend, backend, electron, or desktop scripts, reflect that instead of reducing the app to a single layer. "
                    "Do not claim the app is only backend-only, frontend-only, or single-service if the repo_profile contradicts that. "
                    "Use the tone of a strong technical explainer talking to a smart builder, not a corporate status bot. It should feel like a thoughtful human read the repo and is telling the user what stood out. "
                    "Avoid jargon where possible, and when you use it, make it understandable. "
                    "Treat grouped_syntheses as the primary review artifact for understanding what is going on in each area of the codebase. Use findings as secondary evidence that supports the narrative. "
                    "Do not just restate counters. Synthesize the architecture and intent from the repo_profile, stage summaries, grouped_syntheses, findings, and agent summaries. "
                    "overall_summary should read like a compact, insightful narrative of 2 to 5 sentences, not bullet fragments. "
                    "current_state must be an array of short plain-English strings describing the app's role, current state, and notable system behavior after this run, ideally organized around major code areas surfaced by grouped_syntheses. "
                    "codebase_areas must be an array of objects with title, summary, and file_paths, describing the major areas surfaced by grouped_syntheses. Keep it to 2 to 6 areas. "
                    "issues must be an array of objects with title, severity, file_path, and explanation. "
                    "For each issue explanation, include why a vibecoder should care about it, in normal conversational language. "
                    "next_actions should be plain-English, high-leverage follow-up steps. "
                    "Keep it useful, confident, and human-readable. List at most 5 issues."
                ),
            },
            {
                "role": "user",
                "content": (
                    "A vibecoder wants to understand this app and this completed run. First explain what is going on in the major areas of the codebase using grouped_syntheses and repo_profile, then call out the concrete issues worth keeping from the selected findings. Anchor the architecture description to repo_profile and grouped_syntheses before using findings for detail. "
                    "Write it like a thoughtful person explaining what they saw after reading the repo and the run output, not like a compliance report. Keep it easy to read, but do not dumb it down.\n"
                    + json.dumps(prompt_payload)
                ),
            },
        ]
    return [
        {
            "role": "system",
            "content": (
                "You generate concise but natural engineering run summaries for completed runs. Return JSON only with keys status, overall_summary, current_state, codebase_areas, issues, next_actions. "
                "Treat the run as completed, never in progress, unless the payload explicitly says otherwise. "
                "Treat grouped_syntheses as the primary review artifact for explaining what is happening in major areas of the codebase. Use selected persisted merged findings as secondary evidence. "
                "Base the summary on the provided repo_profile, grouped_syntheses, stage output, and selected persisted merged findings. Do not use speculative architecture criticism unless it appears in the selected findings or grouped_syntheses. "
                "If repo_profile shows multiple app surfaces such as backend, frontend, electron, or desktop scripts, reflect that in the summary instead of collapsing the app to one layer. "
                "Write like a senior engineer briefing another engineer, not like an auto-generated audit robot. "
                "current_state must be an array of short strings describing the app state after the completed run, organized around the major areas surfaced by grouped_syntheses when possible. "
                "codebase_areas must be an array of objects with title, summary, and file_paths, describing the major areas surfaced by grouped_syntheses. Keep it to 2 to 6 areas. "
                "issues must be an array of objects with title, severity, file_path, and explanation derived from actual findings when possible. "
                "Use only the top selected findings provided. Keep the response compact and practical, and list at most 5 issues."
            ),
        },
        {
            "role": "user",
            "content": (
                "Summarize this completed indexing and review run. First describe what is going on in the major areas of the codebase using repo_profile and grouped_syntheses, then list the most important concrete issues from the selected merged findings. Do not say the run is still in progress. Write it as a useful engineering readout, not a stiff template.\n"
                + json.dumps(prompt_payload)
            ),
        },
    ]


def _fallback_summary(audience: str, reason: str) -> dict[str, Any]:
    if audience == "layperson":
        return {
            "status": "unavailable",
            "overall_summary": f"Layperson run summary unavailable: {reason}",
            "current_state": [],
            "codebase_areas": [],
            "issues": [],
            "next_actions": [],
        }
    return {
        "status": "unavailable",
        "overall_summary": f"LLM run summary unavailable: {reason}",
        "current_state": [],
        "codebase_areas": [],
        "issues": [],
        "next_actions": [],
    }


def _render_markdown_report(title: str, run_id: str, summary: dict[str, Any]) -> str:
    lines = [f"# {title}", "", f"Run ID: `{run_id}`", ""]
    overall = summary.get("overall_summary", "")
    if overall:
        lines.extend(["## Overview", "", overall, ""])
    current_state = summary.get("current_state", [])
    if current_state:
        lines.extend(["## Current State", ""])
        lines.extend([f"- {item}" for item in current_state])
        lines.append("")
    codebase_areas = summary.get("codebase_areas", [])
    if codebase_areas:
        lines.extend(["## Codebase Areas", ""])
        for item in codebase_areas:
            area_title = item.get("title", "Untitled area")
            area_summary = item.get("summary", "")
            file_paths = item.get("file_paths", [])
            lines.append(f"- **{area_title}**")
            if area_summary:
                lines.append(f"  - {area_summary}")
            if file_paths:
                lines.append(f"  - Files: {', '.join(f'`{path}`' for path in file_paths[:6])}")
        lines.append("")
    issues = summary.get("issues", [])
    if issues:
        lines.extend(["## Issues", ""])
        for item in issues:
            title_text = item.get("title", "Untitled issue")
            severity = item.get("severity", "unknown")
            file_path = item.get("file_path", "unknown")
            explanation = item.get("explanation", "")
            lines.append(f"- **[{severity}] {title_text}** (`{file_path}`)")
            if explanation:
                lines.append(f"  - {explanation}")
        lines.append("")
    next_actions = summary.get("next_actions", [])
    if next_actions:
        lines.extend(["## Next Actions", ""])
        lines.extend([f"- {item}" for item in next_actions])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def write_run_reports(data_dir: Path, run_id: str, technical_summary: dict[str, Any], layperson_summary: dict[str, Any]) -> dict[str, str]:
    reports_dir = data_dir / "reports" / run_id
    reports_dir.mkdir(parents=True, exist_ok=True)
    technical_path = reports_dir / "technical_summary.md"
    layperson_path = reports_dir / "layperson_summary.md"
    technical_path.write_text(
        _render_markdown_report("Technical Run Report", run_id, technical_summary),
        encoding="utf-8",
    )
    layperson_path.write_text(
        _render_markdown_report("Layperson Run Report", run_id, layperson_summary),
        encoding="utf-8",
    )
    return {
        "technical": str(technical_path),
        "layperson": str(layperson_path),
    }


def generate_run_summary(
    settings: RuntimeConfig,
    summary: RunSummary,
    findings: list[ReviewFinding],
    analyses: list[ReviewAgentAnalysis],
    audience: str = "technical",
) -> dict[str, Any]:
    if not settings.openrouter_api_key:
        return _fallback_summary(audience, "OPENROUTER_API_KEY is not configured.")
    prompt_payload = build_run_summary_payload(summary, findings, analyses)
    body = {
        "model": settings.review_analysis_model,
        "response_format": {"type": "json_object"},
        "messages": _build_summary_messages(prompt_payload, audience),
    }
    req = request.Request(
        url=f"{settings.openrouter_base_url.rstrip('/')}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": settings.openrouter_site_url or "https://local.coder",
            "X-Title": settings.openrouter_app_name,
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="ignore")
        return _fallback_summary(audience, message)
    except error.URLError as exc:
        return _fallback_summary(audience, str(exc))
    content = payload.get("choices", [{}])[0].get("message", {}).get("content", "{}")
    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        return _fallback_summary(audience, f"invalid JSON returned: {content[:500]}")
    if not isinstance(result, dict):
        return _fallback_summary(audience, "response was not a JSON object.")
    result.setdefault("status", "completed")
    result.setdefault("overall_summary", "")
    result.setdefault("current_state", [])
    result.setdefault("codebase_areas", [])
    result.setdefault("issues", [])
    result.setdefault("next_actions", [])
    return result
