import pytest

from harness_testing.Quality import DIMENSIONS, RUBRIC_VERSION, quality_score


def grade(score=4, **overrides):
    return {
        "status": "completed",
        "rubric_version": RUBRIC_VERSION,
        "protocol_id": "one",
        "dimensions": [{"name": name, "score": score} for name in DIMENSIONS],
        **overrides,
    }


def test_quality_score_is_the_mean_of_six_complete_dimensions():
    assert quality_score(grade()) == 0.8
    assert quality_score(grade(5)) == 1.0


@pytest.mark.parametrize("score", [None, 0, 6, True])
def test_quality_never_averages_away_missing_or_invalid_dimensions(score):
    value = grade()
    value["dimensions"][0]["score"] = score
    assert quality_score(value) is None


def test_quality_requires_a_completed_grade_under_the_current_rubric():
    assert quality_score(None) is None
    assert quality_score(grade(status="blocked")) is None
    assert quality_score(grade(rubric_version="other")) is None
    assert quality_score(grade(dimensions=grade()["dimensions"][:5])) is None
