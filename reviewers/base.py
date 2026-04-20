from abc import ABC, abstractmethod
from pathlib import Path
from uuid import uuid4

from models.review_models import ReviewJob, ReviewObservation, ReviewResult


class BaseReviewer(ABC):
    review_type: str = "base"
    is_llm_backed: bool = False

    @abstractmethod
    def review(self, job: ReviewJob, file_path: Path) -> ReviewResult:
        raise NotImplementedError

    def build_observation(self, job: ReviewJob, title: str, description: str, category: str, severity: str) -> ReviewObservation:
        return ReviewObservation(
            observation_id=uuid4().hex,
            job_id=job.job_id,
            run_id=job.run_id,
            review_type=self.review_type,
            category=category,
            severity=severity,
            title=title,
            description=description,
            file_path=job.file_path,
            review_model="heuristic-v1",
        )
