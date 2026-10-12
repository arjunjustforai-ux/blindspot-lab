import json

import pytest

from app.config import REPO_ROOT
from app.services.diagnosis import hypotheses as H
from app.services.knowledge.catalog import misconception_catalog

CATALOG = misconception_catalog()
HYPS = list(CATALOG["hypothesis_keys"])


def test_catalogue_has_ten_entries_with_unique_keys():
    keys = [e["key"] for e in CATALOG["entries"]]
    assert len(keys) == 10 and len(set(keys)) == 10


@pytest.mark.parametrize("entry", CATALOG["entries"], ids=lambda e: e["key"])
def test_probe_likelihood_tables_are_distributions(entry):
    """Each probe covers exactly the entry's hypotheses (the misconception plus its competing
    interpretations), and for every hypothesis h, P(response | h) over the responses sums to 1."""
    assert entry["diagnostic_probes"], entry["key"]
    declared = {"misconception"} | {c["key"] for c in entry["competing_interpretations"]}
    assert declared <= set(HYPS)
    for probe in entry["diagnostic_probes"]:
        lk = probe["likelihoods"]
        assert set().union(*map(set, lk.values())) == declared, probe["key"]
        for h in declared:
            total = sum(table.get(h, 0.0) for table in lk.values())
            assert total == pytest.approx(1.0, abs=0.011), f"{entry['key']}/{probe['key']}/{h}: {total}"
        if probe["type"] == "mcq":
            assert set(lk) == {o["id"] for o in probe["options"]}


@pytest.mark.parametrize("entry", CATALOG["entries"], ids=lambda e: e["key"])
def test_entries_are_complete(entry):
    for field in ("title", "description", "concept_keys", "detection_cues", "competing_interpretations", "repair"):
        assert entry.get(field), (entry["key"], field)
    assert entry["repair"].get("contrast")


def test_bayes_update_and_entropy():
    prior = {"misconception": 0.5, "calculation_error": 0.5}
    post = H.bayes(prior, {"misconception": 0.75, "calculation_error": 0.1})
    assert post["misconception"] == pytest.approx(0.75 / 0.85)
    assert H.entropy({"a": 0.5, "b": 0.5}) == pytest.approx(1.0)


def test_probe_selection_prefers_informative_probe():
    dist = {h: 1 / len(HYPS) for h in HYPS}
    useless = {"key": "useless", "likelihoods": {"x": {h: 0.5 for h in HYPS}, "y": {h: 0.5 for h in HYPS}}}
    useful = CATALOG["entries"][0]["diagnostic_probes"][0]
    best, gain = H.choose_probe(dist, [useless, useful], asked=set())
    assert best["key"] == useful["key"] and gain > H.MIN_EIG_BITS
    assert H.expected_information_gain(dist, useless) == pytest.approx(0.0, abs=1e-9)
    best2, _ = H.choose_probe(dist, [useless, useful], asked={useful["key"]})
    assert best2 is None


def test_status_never_supported_from_single_evidence():
    assert H.status_for(0.95, 1) == "suspected"
    assert H.status_for(0.95, 2) == "supported"
    assert H.status_for(0.2, 3) == "unresolved"
    assert H.status_for(0.05, 3) == "rejected"


def test_prior_from_history_is_bounded():
    dist = {"misconception": 0.4, "guess": 0.6}
    up = H.prior_from_history(dist, 0.99)
    down = H.prior_from_history(dist, 0.01)
    assert down["misconception"] < 0.4 < up["misconception"] < 1
    assert H.prior_from_history(dist, None) == dist


def test_catalogue_file_is_valid_json_on_disk():
    json.loads((REPO_ROOT / "services/api/app/data/misconception_catalog.json").read_text())
