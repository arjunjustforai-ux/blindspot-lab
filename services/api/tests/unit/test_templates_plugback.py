import pytest

from app.services.assessment import templates as T
from app.services.assessment.plugback import CHECKS, plug_back


@pytest.mark.parametrize("key", sorted(T.TEMPLATES))
@pytest.mark.parametrize("seed", [1, 7, 42])
def test_every_template_answer_passes_its_independent_plug_back(key, seed):
    g = T.generate(key, seed)
    answer = g.numeric_answer if g.question_type == "numerical" else g.correct_option_id
    assert answer is not None
    result = plug_back(key, g.params, answer)
    if key in CHECKS:
        assert result is True, f"{key} seed={seed} answer={answer} params={g.params}"


@pytest.mark.parametrize("key", sorted(k for k in T.TEMPLATES if T.TEMPLATES[k].question_type == "numerical"))
def test_plug_back_rejects_a_perturbed_answer(key):
    g = T.generate(key, 3)
    if key not in CHECKS:
        pytest.skip("no plug-back check")
    wrong = g.numeric_answer * 1.25 + 7
    assert plug_back(key, g.params, wrong) is False


def test_signature_scenario_numbers():
    g = T.generate("price_cut_volume", 0, {"price": 100, "var_cost": 60, "new_price": 80,
                                            "context": ["a company", "product", "units"]})
    assert g.numeric_answer == pytest.approx(100.0)
    rev = next(s for s in g.signatures if s.get("misconception_key") == "contribution_vs_revenue")
    assert rev["value"] == pytest.approx(25.0)


def test_templates_carry_complete_metadata():
    for key, t in T.TEMPLATES.items():
        g = T.generate(key, 11)
        assert g.stem and g.explanation and g.worked_steps, key
        assert g.difficulty in (1, 2, 3), key
        assert g.concept_key == t.concept_key and g.family, key
        if g.question_type == "mcq":
            ids = [o["id"] for o in g.options]
            assert len(ids) == len(set(ids)) >= 3 and g.correct_option_id in ids, key
        else:
            assert g.tolerance is not None and g.tolerance_mode in ("abs", "rel"), key


def test_unknown_template_has_no_check():
    assert plug_back("not-a-template", {}, 1) is None


def test_generation_is_deterministic_per_seed():
    a, b = T.generate("breakeven_roas", 5), T.generate("breakeven_roas", 5)
    assert a.stem == b.stem and a.numeric_answer == b.numeric_answer
