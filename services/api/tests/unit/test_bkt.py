import pytest

from app.services.learner import bkt


def test_correct_answer_raises_and_wrong_answer_lowers_mastery():
    p = bkt.params_for("numerical", 2)
    assert bkt.update(0.4, True, p) > 0.4
    assert bkt.posterior(0.4, False, p) < 0.4


def test_posterior_matches_closed_form():
    p = bkt.Params(guess=0.2, slip=0.1)
    expected = 0.5 * 0.9 / (0.5 * 0.9 + 0.5 * 0.2)
    assert bkt.posterior(0.5, True, p) == pytest.approx(expected)


def test_zero_weight_observation_changes_nothing():
    p = bkt.params_for("mcq", 1, n_options=4)
    assert bkt.posterior(0.3, True, p, weight=0.0) == 0.3
    # learning transition is also scaled by the weight
    assert bkt.update(0.3, True, p, weight=0.0) == pytest.approx(0.3)


def test_weighting_tempers_evidence():
    p = bkt.params_for("numerical", 2)
    full = bkt.update(0.25, True, p, weight=1.0)
    half = bkt.update(0.25, True, p, weight=0.5)
    assert 0.25 < half < full


def test_update_stays_inside_open_interval():
    p = bkt.params_for("numerical", 1)
    x = 0.5
    for _ in range(200):
        x = bkt.update(x, True, p)
    assert 0 < x < 1
    for _ in range(200):
        x = bkt.update(x, False, p)
    assert 0 < x < 1


def test_mcq_guess_is_capped_by_number_of_options():
    assert bkt.params_for("mcq", 2, n_options=3).guess == pytest.approx(0.2)
    assert bkt.params_for("mcq", 2, n_options=6).guess == pytest.approx(1 / 6)


def test_harder_items_have_higher_slip():
    assert bkt.params_for("numerical", 1).slip < bkt.params_for("numerical", 2).slip < bkt.params_for("numerical", 3).slip


@pytest.mark.parametrize(
    ("p", "n", "distinct", "expected"),
    [(None, 0, 0, "unassessed"), (0.95, 5, 2, "proficient"), (0.95, 5, 3, "mastered"), (0.5, 2, 2, "developing"),
     (0.1, 1, 1, "emerging")],
)
def test_labels(p, n, distinct, expected):
    assert bkt.label(p, n, distinct) == expected


def test_predicted_correctness():
    p = bkt.Params(guess=0.2, slip=0.1)
    assert bkt.p_correct(1.0, p) == pytest.approx(0.9)
    assert bkt.p_correct(0.0, p) == pytest.approx(0.2)
