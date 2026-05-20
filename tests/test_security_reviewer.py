from pathlib import Path

from models.review_models import ReviewJob
from reviewers.security_reviewer import SecurityReviewer


def _job(path: Path) -> ReviewJob:
    return ReviewJob(job_id="job-1", review_type="security", file_path=str(path), run_id="run-1")


def test_security_reviewer_ignores_benign_design_tokens(tmp_path: Path) -> None:
    source = tmp_path / "theme.py"
    source.write_text(
        "def palette():\n"
        "    design_token = 'blue'\n"
        "    return design_token\n",
        encoding="utf-8",
    )

    result = SecurityReviewer().review(_job(source), source)

    assert result.findings == []


def test_security_reviewer_flags_token_without_verification_flow(tmp_path: Path) -> None:
    source = tmp_path / "auth.py"
    source.write_text(
        "def load_user(access_token):\n"
        "    user_id = parse_user(access_token)\n"
        "    return user_id\n",
        encoding="utf-8",
    )

    result = SecurityReviewer().review(_job(source), source)

    assert [finding.category for finding in result.findings] == ["authorization_gap"]
    assert result.findings[0].start_line == 1
    assert result.findings[0].review_model == "ast-graph-heuristic-v2"


def test_security_reviewer_allows_token_with_verification_call(tmp_path: Path) -> None:
    source = tmp_path / "auth.py"
    source.write_text(
        "def load_user(access_token):\n"
        "    claims = verify_token(access_token)\n"
        "    return claims['sub']\n",
        encoding="utf-8",
    )

    result = SecurityReviewer().review(_job(source), source)

    assert result.findings == []


def test_security_reviewer_flags_dynamic_python_sql(tmp_path: Path) -> None:
    source = tmp_path / "repo.py"
    source.write_text(
        "def get_user(conn, user_id):\n"
        "    return conn.execute(f\"select * from users where id = {user_id}\")\n",
        encoding="utf-8",
    )

    result = SecurityReviewer().review(_job(source), source)

    assert any(finding.category == "injection_risk" for finding in result.findings)
    sql_finding = next(finding for finding in result.findings if finding.category == "injection_risk")
    assert sql_finding.start_line == 2
