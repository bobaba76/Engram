from __future__ import annotations

from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import BoundedSemaphore
from time import sleep
from typing import Callable

from models.review_models import ReviewJob, ReviewResult
from reviewers.base import BaseReviewer


@dataclass(slots=True)
class ReviewExecutionPolicy:
    max_workers: int = 3
    max_concurrent_llm_requests: int = 1
    max_attempts: int = 3
    initial_backoff_seconds: float = 1.0
    backoff_multiplier: float = 2.0


class RetryableReviewError(RuntimeError):
    pass


LLM_ERROR_MARKERS = ("429", "rate limit", "too many requests", "timeout", "temporarily unavailable")


def _is_retryable_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in LLM_ERROR_MARKERS)


def _run_single_review(
    reviewer: BaseReviewer,
    job: ReviewJob,
    file_path: Path,
    policy: ReviewExecutionPolicy,
    llm_semaphore: BoundedSemaphore,
) -> ReviewResult:
    attempts = 0
    backoff = policy.initial_backoff_seconds
    while True:
        attempts += 1
        acquired = False
        try:
            if getattr(reviewer, "is_llm_backed", False):
                llm_semaphore.acquire()
                acquired = True
            result = reviewer.review(job, file_path)
            job.status = "completed"
            return result
        except Exception as error:
            if attempts >= policy.max_attempts or not _is_retryable_error(error):
                job.status = "failed"
                raise
            sleep(backoff)
            backoff *= policy.backoff_multiplier
        finally:
            if acquired:
                llm_semaphore.release()


def run_review_jobs(
    review_jobs: list[ReviewJob],
    reviewers: dict[str, BaseReviewer],
    repo_root: Path,
    policy: ReviewExecutionPolicy,
    progress_callback: Callable[[int, int, ReviewJob], None] | None = None,
) -> list[ReviewResult]:
    if not review_jobs:
        return []
    results: list[ReviewResult] = []
    llm_semaphore = BoundedSemaphore(value=max(policy.max_concurrent_llm_requests, 1))
    with ThreadPoolExecutor(max_workers=max(policy.max_workers, 1)) as executor:
        future_to_job = {}
        for job in review_jobs:
            reviewer = reviewers[job.review_type]
            file_path = repo_root / Path(job.file_path)
            future = executor.submit(_run_single_review, reviewer, job, file_path, policy, llm_semaphore)
            future_to_job[future] = job
        completed = 0
        for future in as_completed(future_to_job):
            results.append(future.result())
            completed += 1
            if progress_callback is not None:
                progress_callback(completed, len(review_jobs), future_to_job[future])
    return results
