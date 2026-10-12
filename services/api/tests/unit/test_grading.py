import pytest

from app.models import Question
from app.services.assessment.grading import grade_mcq, grade_numerical, numeric_match, parse_number


@pytest.mark.parametrize(
    ("raw", "value", "pct"),
    [("25", 25.0, False), ("25%", 25.0, True), ("₹1,25,000", 125000.0, False), ("-₹200", -200.0, False),
     ("1.5 lakh", 150000.0, False), ("2.5 crore", 25000000.0, False), ("about 12.5 percent", 12.5, True),
     ("3k", 3000.0, False), (".5", 0.5, False), (7, 7.0, False), ("", None, False), ("no idea", None, False)],
)
def test_parse_number(raw, value, pct):
    v, had_pct = parse_number(raw)
    assert (v == pytest.approx(value)) if value is not None else v is None
    assert had_pct is pct


def test_numeric_match_modes():
    assert numeric_match(100.4, 100, 0.6, "abs")
    assert not numeric_match(101, 100, 0.6, "abs")
    assert numeric_match(1010, 1000, 0.02, "rel")
    assert not numeric_match(1030, 1000, 0.02, "rel")


def _numq(answer=100.0, tol=0.6, unit="%"):
    return Question(question_type="numerical", numeric_answer=answer, numeric_tolerance=tol, tolerance_mode="abs",
                    answer_unit=unit, options=[])


def test_grade_numerical_accepts_within_tolerance_and_formats():
    assert grade_numerical(_numq(), {"value": "100%"}).is_correct
    assert grade_numerical(_numq(), {"value": "99.5"}).is_correct
    assert not grade_numerical(_numq(), {"value": "25"}).is_correct


def test_fraction_for_percent_is_accepted_and_reported():
    g = grade_numerical(_numq(answer=25.0), {"value": "0.25"})
    assert g.is_correct and g.detail["interpreted_as_fraction"]


def test_unreadable_numeric_answer_is_not_graded():
    g = grade_numerical(_numq(), {"value": "lots"})
    assert g.is_correct is None and "error" in g.detail


def test_grade_mcq():
    q = Question(question_type="mcq", options=[{"id": "a", "text": "x"}, {"id": "b", "text": "y"}], correct_option_id="b")
    assert grade_mcq(q, {"option_id": "B"}).is_correct
    assert grade_mcq(q, {"option_id": "a"}).is_correct is False
    assert grade_mcq(q, {"option_id": "z"}).is_correct is None
