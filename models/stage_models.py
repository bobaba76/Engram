from dataclasses import dataclass, field
from time import time
from typing import Any


@dataclass(slots=True)
class StageResult:
    stage_name: str
    status: str
    input_summary: dict[str, Any] = field(default_factory=dict)
    output_summary: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time)
    completed_at: float | None = None


@dataclass(slots=True)
class RunSummary:
    run_id: str
    run_mode: str
    stage_results: list[StageResult] = field(default_factory=list)
    llm_summary: dict[str, Any] = field(default_factory=dict)
    technical_summary: dict[str, Any] = field(default_factory=dict)
    layperson_summary: dict[str, Any] = field(default_factory=dict)
    report_paths: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    promoted: bool = False
