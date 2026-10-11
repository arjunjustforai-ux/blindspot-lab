"""Reproduce the recorded evaluation runs.

Usage (from the repository root, with the API virtualenv active and the demo course seeded):

    python evaluation/scripts/run_evaluation.py --kinds rag assessment personalization
    python evaluation/scripts/make_report.py

Each run is stored in the database (visible in the Evaluation Lab) and exported to
evaluation/results/<kind>_<timestamp>.json plus evaluation/results/latest_<kind>.json.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.logging_setup import configure_logging  # noqa: E402
from app.services.evaluation.runner import create_and_execute  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kinds", nargs="+", default=["rag", "assessment", "personalization"],
                    choices=["rag", "assessment", "personalization"])
    ap.add_argument("--learners-per-profile", type=int, default=15)
    args = ap.parse_args()
    configure_logging()
    for kind in args.kinds:
        t0 = time.time()
        out = create_and_execute(kind, learners_per_profile=args.learners_per_profile)
        print(f"[{kind}] run {out['id']} finished in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
