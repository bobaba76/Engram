from dataclasses import dataclass, field
from time import time
from typing import Any


@dataclass(slots=True)
class ReviewJob:
    job_id: str
    review_type: str
    file_path: str
    run_id: str = ""
    priority: str = "medium"
    status: str = "pending"
    created_at: float = field(default_factory=time)


@dataclass(slots=True)
class ReviewObservation:
    observation_id: str
    job_id: str
    run_id: str
    review_type: str
    file_path: str
    category: str
    severity: str
    title: str
    description: str
    confidence: float = 0.5
    suggested_fix: str = ""
    start_line: int | None = None
    end_line: int | None = None
    review_model: str = ""
    prompt_version: str = "1"


@dataclass(slots=True)
class ReviewFinding:
    finding_id: str
    review_type: str
    category: str
    severity: str
    title: str
    description: str
    file_path: str
    confidence: float = 0.5
    suggested_fix: str = ""
    start_line: int | None = None
    end_line: int | None = None
    fingerprint: str = ""
    status: str = "open"
    first_seen_at: float = field(default_factory=time)
    last_seen_at: float = field(default_factory=time)
    occurrence_count: int = 1
    source_review_types: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ReviewResult:
    job: ReviewJob
    findings: list[ReviewObservation] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ReviewAgentAnalysis:
    analysis_id: str
    job_id: str
    run_id: str
    file_path: str
    agent_type: str
    provider_name: str
    model_name: str
    prompt_version: str
    summary: str
    output_json: dict[str, Any] = field(default_factory=dict)
    input_context_json: dict[str, Any] = field(default_factory=dict)
    status: str = "completed"
    created_at: float = field(default_factory=time)
