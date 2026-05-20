from pathlib import Path

from app.coordinator import Coordinator
from models.review_models import ReviewAgentAnalysis, ReviewJob


def test_coordinator_bulk_writes_agent_analyses(monkeypatch, tmp_path: Path) -> None:
    coordinator = object.__new__(Coordinator)
    coordinator.settings = type(
        "_Settings",
        (),
        {
            "repo_root": tmp_path,
            "review_group_size": 10,
            "max_concurrent_llm_reviews": 2,
        },
    )()
    coordinator.kuzu = object()
    logs: list[str] = []
    coordinator._log_progress = logs.append
    coordinator._should_log_index = lambda index, total: True
    coordinator.duckdb = type(
        "_Duck",
        (),
        {
            "reviews": type(
                "_Reviews",
                (),
                {
                    "bulk_records": [],
                    "single_calls": 0,
                    "insert_agent_analyses": lambda self, records: setattr(self, "bulk_records", records),
                    "insert_agent_analysis": lambda self, record: setattr(self, "single_calls", self.single_calls + 1),
                },
            )()
        },
    )()
    monkeypatch.setattr(
        "app.coordinator.build_review_context",
        lambda duckdb, kuzu, file_path, relative_path: {"file_path": relative_path},
    )

    class _Provider:
        def analyze_group(self, jobs, contexts):
            return [
                ReviewAgentAnalysis(
                    analysis_id=f"analysis-{job.job_id}",
                    job_id=job.job_id,
                    run_id=job.run_id,
                    file_path=job.file_path,
                    agent_type="test",
                    provider_name="fake",
                    model_name="fake-model",
                    prompt_version="1",
                    summary="ok",
                    output_json={"ok": True},
                    input_context_json={"file_path": job.file_path},
                )
                for job in jobs
            ]

    jobs = [
        ReviewJob(job_id="job-1", review_type="general", file_path="src/a.py", run_id="run-1"),
        ReviewJob(job_id="job-2", review_type="general", file_path="src/b.py", run_id="run-1"),
    ]

    analyses = coordinator._run_agent_analyses(jobs, _Provider())

    assert len(analyses) == 2
    assert len(coordinator.duckdb.reviews.bulk_records) == 2
    assert coordinator.duckdb.reviews.single_calls == 0
    assert coordinator.duckdb.reviews.bulk_records[0]["output_json"] == '{"ok": true}'
    assert any("bulk write started" in message for message in logs)
