from models.stage_models import StageResult


def finish_stage(stage_result: StageResult, status: str, output_summary: dict[str, object] | None = None, diagnostics: list[str] | None = None) -> StageResult:
    stage_result.status = status
    stage_result.output_summary = output_summary or {}
    stage_result.diagnostics = diagnostics or []
    stage_result.completed_at = stage_result.started_at
    return stage_result
