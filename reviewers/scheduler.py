from models.review_models import ReviewJob


# REVIEW_TYPES = ("security", "logic", "maintainability")
REVIEW_TYPES = ("general",)


def build_review_jobs(file_paths: list[str], run_id: str) -> list[ReviewJob]:
    jobs: list[ReviewJob] = []
    counter = 1
    for file_path in file_paths:
        for review_type in REVIEW_TYPES:
            jobs.append(ReviewJob(job_id=f"job-{counter}", review_type=review_type, file_path=file_path, run_id=run_id))
            counter += 1
    return jobs
