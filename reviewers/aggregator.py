from __future__ import annotations

import json
import re
from time import time
from uuid import uuid4

from models.review_models import ReviewAgentAnalysis, ReviewFinding, ReviewJob, ReviewObservation, ReviewResult


SEVERITY_ALIASES = {"minor": "low", "moderate": "medium", "major": "high", "info": "low"}
SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _path_area(file_path: str) -> str:
    parts = [part for part in file_path.replace("\\", "/").split("/") if part]
    if len(parts) == 2:
        return parts[0]
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return file_path.replace("\\", "/")


def _normalize_text(value: str) -> str:
    lowered = (value or "").strip().lower()
    lowered = re.sub(r"`[^`]+`", "", lowered)
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _title_signature(title: str, category: str) -> str:
    normalized = _normalize_text(title)
    if not normalized:
        normalized = _normalize_text(category)
    for hint in (
        "sql injection",
        "hardcoded secret",
        "hardcoded credential",
        "token usage without obvious verification",
        "missing authentication",
        "unsafe subprocess",
        "path traversal",
    ):
        if hint in normalized:
            return hint
    words = [word for word in normalized.split(" ") if len(word) > 2]
    return " ".join(words[:6])


def _fingerprint(observation: ReviewObservation) -> str:
    title_signature = _title_signature(observation.title, observation.category)
    normalized_category = _normalize_text(observation.category)
    return f"{_path_area(observation.file_path)}|{normalized_category}|{title_signature}"


def _normalize_severity(value: str) -> str:
    normalized = (value or "low").lower()
    normalized = SEVERITY_ALIASES.get(normalized, normalized)
    if normalized in SEVERITY_ORDER:
        return normalized
    return "low"


def _normalize_confidence(value: object) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(float(value), 1.0))
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"low", "minor"}:
            return 0.35
        if normalized in {"medium", "moderate"}:
            return 0.65
        if normalized in {"high", "major"}:
            return 0.9
        if normalized == "critical":
            return 0.98
        try:
            return max(0.0, min(float(normalized), 1.0))
        except ValueError:
            return 0.5
    return 0.5


def synthesize_findings_from_agent_analyses(
    analyses: list[ReviewAgentAnalysis],
    review_jobs: list[ReviewJob],
) -> list[ReviewResult]:
    jobs_by_id = {job.job_id: job for job in review_jobs}
    synthesized_results: list[ReviewResult] = []
    for analysis in analyses:
        if analysis.agent_type not in {"synthesizer_agent", "general_review_agent", "grouped_general_review_agent"}:
            continue
        job = jobs_by_id.get(analysis.job_id)
        if job is None:
            continue
        observations_raw = analysis.output_json.get("observations", [])
        if isinstance(observations_raw, str):
            try:
                observations_raw = json.loads(observations_raw)
            except json.JSONDecodeError:
                observations_raw = []
        observations: list[ReviewObservation] = []
        for item in observations_raw:
            if not isinstance(item, dict):
                continue
            observations.append(
                ReviewObservation(
                    observation_id=uuid4().hex,
                    job_id=job.job_id,
                    run_id=job.run_id,
                    review_type=f"{job.review_type}_llm",
                    file_path=str(item.get("file_path", job.file_path) or job.file_path).replace("\\", "/"),
                    category=str(item.get("category", "llm_review")),
                    severity=_normalize_severity(str(item.get("severity", "low"))),
                    title=str(item.get("title", analysis.summary or "LLM synthesized finding")),
                    description=str(item.get("description", analysis.summary or "")),
                    confidence=_normalize_confidence(item.get("confidence", 0.5)),
                    suggested_fix=str(item.get("suggested_fix", "")),
                    start_line=item.get("start_line"),
                    end_line=item.get("end_line"),
                    review_model=analysis.model_name,
                    prompt_version=analysis.prompt_version,
                )
            )
        synthesized_results.append(ReviewResult(job=job, findings=observations))
    return synthesized_results


def merge_findings(results: list[ReviewResult]) -> tuple[list[ReviewObservation], list[ReviewFinding]]:
    observations: list[ReviewObservation] = []
    merged: dict[str, ReviewFinding] = {}
    now = time()
    for result in results:
        for observation in result.findings:
            observations.append(observation)
            fingerprint = _fingerprint(observation)
            existing = merged.get(fingerprint)
            if existing is None:
                merged[fingerprint] = ReviewFinding(
                    finding_id=uuid4().hex,
                    review_type=observation.review_type,
                    category=observation.category,
                    severity=_normalize_severity(observation.severity),
                    title=observation.title,
                    description=observation.description,
                    file_path=observation.file_path,
                    confidence=observation.confidence,
                    suggested_fix=observation.suggested_fix,
                    start_line=observation.start_line,
                    end_line=observation.end_line,
                    fingerprint=fingerprint,
                    first_seen_at=now,
                    last_seen_at=now,
                    source_review_types=[observation.review_type],
                )
                continue
            existing.last_seen_at = now
            existing.occurrence_count += 1
            if observation.review_type not in existing.source_review_types:
                existing.source_review_types.append(observation.review_type)
            existing.severity = _normalize_severity(existing.severity)
            normalized_observation_severity = _normalize_severity(observation.severity)
            if SEVERITY_ORDER[normalized_observation_severity] > SEVERITY_ORDER[existing.severity]:
                existing.severity = normalized_observation_severity
            if len(observation.description or "") > len(existing.description or ""):
                existing.description = observation.description
            if len(observation.suggested_fix or "") > len(existing.suggested_fix or ""):
                existing.suggested_fix = observation.suggested_fix
            if observation.start_line is not None and existing.start_line is None:
                existing.start_line = observation.start_line
            if observation.end_line is not None and existing.end_line is None:
                existing.end_line = observation.end_line
            existing.confidence = max(existing.confidence, observation.confidence)
    return observations, list(merged.values())
