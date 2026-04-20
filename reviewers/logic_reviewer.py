from pathlib import Path

from models.review_models import ReviewJob, ReviewResult
from reviewers.base import BaseReviewer


class LogicReviewer(BaseReviewer):
    review_type = "logic"

    def review(self, job: ReviewJob, file_path: Path) -> ReviewResult:
        text = file_path.read_text(encoding="utf-8")
        findings = []
        if "TODO" in text:
            findings.append(
                self.build_observation(
                    job,
                    title="TODO marker found in active code",
                    description="A TODO marker may indicate incomplete logic or an unfinished edge case.",
                    category="unhandled_edge_case",
                    severity="low",
                )
            )
        return ReviewResult(job=job, findings=findings)
