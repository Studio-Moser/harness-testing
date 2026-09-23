"""Automated work-quality grades are descriptive evidence beside the engineering verdict."""

from statistics import mean

POLICY_ID = "benchmark-readiness-v2"
RUBRIC_VERSION = "tim-work-quality-v2"
DIMENSIONS = (
    "plain_language",
    "appropriate_autonomy",
    "self_verification",
    "regression_coverage",
    "requirements_fit",
    "research_depth",
)


def quality_score(grade):
    if (
        not grade
        or grade.get("status") != "completed"
        or grade.get("rubric_version") != RUBRIC_VERSION
    ):
        return None
    rows = grade.get("dimensions", [])
    if len(rows) != len(DIMENSIONS) or {r["name"] for r in rows} != set(DIMENSIONS):
        return None
    values = [r.get("score") for r in rows]
    if any(type(v) is not int or not 1 <= v <= 5 for v in values):
        return None
    return mean(values) / 5
