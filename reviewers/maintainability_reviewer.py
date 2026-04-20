from pathlib import Path

from models.review_models import ReviewJob, ReviewResult
from reviewers.base import BaseReviewer


class MaintainabilityReviewer(BaseReviewer):
    review_type = "maintainability"

    def review(self, job: ReviewJob, file_path: Path) -> ReviewResult:
        line_count = len(file_path.read_text(encoding="utf-8").splitlines())
        findings = []
        if line_count > 300:
            findings.append(
                self.build_observation(
                    job,
                    title="Large file may be hard to maintain",
                    description="The file exceeds 300 lines and may benefit from decomposition.",
                    category="hard_to_modify_code",
                    severity="low",
                )
            )
        return ReviewResult(job=job, findings=findings)
