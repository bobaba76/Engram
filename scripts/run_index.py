import sys
from pathlib import Path

# NOTE: On hybrid GPU laptops, set CUDA_VISIBLE_DEVICES=0 in the shell
# environment before running this script.

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.coordinator import Coordinator
from app.run_modes import FULL, INCREMENTAL
from config.settings import load_settings


def _format_duration(stage) -> str:
    if stage.completed_at is None:
        return "n/a"
    return f"{(stage.completed_at - stage.started_at):.2f}s"


def _compact(value):
    if isinstance(value, list):
        if len(value) <= 5:
            return value
        return {"count": len(value), "sample": value[:5]}
    if isinstance(value, dict):
        return {key: _compact(item) for key, item in value.items()}
    return value


def _print_llm_summary(summary) -> None:
    llm_summary = summary.llm_summary
    if not llm_summary:
        return
    print("Run summary:")
    overall = llm_summary.get("overall_summary", "")
    if overall:
        print(f"- overview: {overall}")
    current_state = llm_summary.get("current_state", [])
    if current_state:
        print("- current_state:")
        for item in current_state:
            print(f"  - {item}")
    issues = llm_summary.get("issues", [])
    if issues:
        print("- issues:")
        for item in issues:
            title = item.get("title", "Untitled issue")
            severity = item.get("severity", "unknown")
            file_path = item.get("file_path", "unknown")
            explanation = item.get("explanation", "")
            print(f"  - [{severity}] {title} ({file_path})")
            if explanation:
                print(f"    {explanation}")
    next_actions = llm_summary.get("next_actions", [])
    if next_actions:
        print("- next_actions:")
        for item in next_actions:
            print(f"  - {item}")


def _print_report_paths(summary) -> None:
    if not summary.report_paths:
        return
    print("Report files:")
    technical = summary.report_paths.get("technical")
    layperson = summary.report_paths.get("layperson")
    if technical:
        print(f"- technical: {technical}")
    if layperson:
        print(f"- layperson: {layperson}")


def _resolve_run_mode() -> str:
    if len(sys.argv) <= 2:
        return INCREMENTAL
    requested = str(sys.argv[2] or '').strip().lower()
    if requested == FULL:
        return FULL
    return INCREMENTAL


def main() -> int:
    project_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
    run_mode = _resolve_run_mode()
    settings = load_settings(project_root)
    print(f"Starting index run for: {settings.repo_root}", flush=True)
    coordinator = Coordinator(settings)
    summary = coordinator.run(run_mode=run_mode)
    print(f"Index run completed: {summary.run_id}")
    for stage in summary.stage_results:
        print(
            f"- {stage.stage_name}: {_format_duration(stage)} | "
            f"in={_compact(stage.input_summary)} | out={_compact(stage.output_summary)}"
        )
    _print_llm_summary(summary)
    _print_report_paths(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
