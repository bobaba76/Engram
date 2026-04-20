from pathlib import Path

from models.review_models import ReviewJob, ReviewResult
from reviewers.base import BaseReviewer


class SecurityReviewer(BaseReviewer):
    review_type = "security"

    def review(self, job: ReviewJob, file_path: Path) -> ReviewResult:
        text = file_path.read_text(encoding="utf-8")
        findings = []
        lowered = text.lower()
        if "token" in lowered and "verify" not in lowered:
            findings.append(
                self.build_observation(
                    job,
                    title="Token usage without obvious verification",
                    description="The file references tokens but no obvious verification keyword was found.",
                    category="authorization_gap",
                    severity="medium",
                )
            )
        return ReviewResult(job=job, findings=findings)
