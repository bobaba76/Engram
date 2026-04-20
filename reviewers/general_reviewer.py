from pathlib import Path

from models.review_models import ReviewJob, ReviewResult
from reviewers.base import BaseReviewer
from reviewers.providers import _has_suspicious_token_usage


class GeneralReviewer(BaseReviewer):
    review_type = "general"

    def review(self, job: ReviewJob, file_path: Path) -> ReviewResult:
        text = file_path.read_text(encoding="utf-8")
        lowered = text.lower()
        findings = []
        if "todo" in lowered:
            findings.append(
                self.build_observation(
                    job,
                    title="TODO marker found in active code",
                    description="A TODO marker may indicate incomplete logic or an unfinished edge case.",
                    category="unhandled_edge_case",
                    severity="low",
                )
            )
        if len(text.splitlines()) > 300:
            findings.append(
                self.build_observation(
                    job,
                    title="Large file may be hard to maintain",
                    description="The file exceeds 300 lines and may benefit from decomposition.",
                    category="hard_to_modify_code",
                    severity="low",
                )
            )
        if _has_suspicious_token_usage(lowered):
            findings.append(
                self.build_observation(
                    job,
                    title="Token handling may rely on weak client-side or implicit validation",
                    description="The file appears to read or manipulate token or auth data, but obvious validation signals were not detected in the same file. This should be reviewed in context rather than treated as a confirmed vulnerability.",
                    category="authorization_gap",
                    severity="low",
                )
            )
        return ReviewResult(job=job, findings=findings)
