"""Parametric question templates with deterministic, verifiable answers.

Each template generates a scenario from a seeded RNG, computes the answer with
plain arithmetic, and lists *misconception signatures*: the specific (wrong)
answers that a catalogued misconception predicts. Signature matching is the core
of the rule-based misconception detector (a "bug library" approach).

Templates are domain knowledge for Marketing & Business Analytics. A template is
only used in a course after retrieval finds source units supporting it.
"""

from __future__ import annotations

import random
import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

CONTEXTS = [
    ("a direct-to-consumer skincare brand", "skincare kit", "kits"),
    ("an online bookstore", "hardcover book", "books"),
    ("a neighbourhood café", "cold brew bottle", "bottles"),
    ("a sports retailer", "pair of running shoes", "pairs"),
    ("a meal-kit startup", "weekly meal box", "boxes"),
    ("a stationery company", "premium notebook", "notebooks"),
    ("a fitness studio", "class pass", "passes"),
    ("an electronics store", "pair of earbuds", "pairs"),
]

SUBSCRIPTION_CONTEXTS = [
    ("a meal-kit subscription", "subscriber"),
    ("a music-streaming service", "member"),
    ("a software-as-a-service tool", "account"),
    ("a pet-food subscription box", "subscriber"),
    ("an online language course", "learner"),
]


def num(x: float, places: int = 2) -> str:
    """Round for display without trailing zeros: 2.000 -> "2", 1.3333 -> "1.333"."""
    return f"{x:.{places}f}".rstrip("0").rstrip(".")


def inr(x: float) -> str:
    """Format rupees with Indian digit grouping (e.g. ₹1,25,000)."""
    neg = x < 0
    x = abs(x)
    whole = int(round(x)) if abs(x - round(x)) < 1e-9 else None
    if whole is None:
        s = f"{x:,.2f}"
        return ("-" if neg else "") + "₹" + s
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups) + "," + tail
    return ("-" if neg else "") + "₹" + s


def pct(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}%".replace(".0%", "%") if nd else f"{x:.0f}%"


@dataclass
class Generated:
    template_key: str
    concept_key: str
    subconcept_key: str | None
    family: str
    question_type: str
    difficulty: int
    stem: str
    explanation: str
    worked_steps: list[str]
    params: dict[str, Any]
    numeric_answer: float | None = None
    tolerance: float | None = None
    tolerance_mode: str | None = None
    unit: str | None = None
    options: list[dict[str, str]] = field(default_factory=list)
    correct_option_id: str | None = None
    assumptions: str | None = None
    signatures: list[dict[str, Any]] = field(default_factory=list)
    source_query: str = ""


@dataclass
class Template:
    key: str
    concept_key: str
    subconcept_key: str | None
    family: str
    question_type: str
    difficulty: int
    source_query: str
    build: Callable[[random.Random, dict[str, Any] | None], Generated]


TEMPLATES: dict[str, Template] = {}


def template(key: str, concept: str, sub: str | None, family: str, qtype: str, difficulty: int, source_query: str):
    def deco(fn: Callable[[random.Random, dict[str, Any] | None], Generated]):
        TEMPLATES[key] = Template(key, concept, sub, family, qtype, difficulty, source_query, fn)
        return fn

    return deco


def _ctx(rng: random.Random) -> tuple[str, str, str]:
    return rng.choice(CONTEXTS)


def _g(t: str, **kw: Any) -> Generated:
    tpl = TEMPLATES[t]
    return Generated(
        template_key=t, concept_key=tpl.concept_key, subconcept_key=tpl.subconcept_key, family=tpl.family,
        question_type=tpl.question_type, difficulty=tpl.difficulty, source_query=tpl.source_query, **kw,
    )


# ---------------------------------------------------------------------------
# Contribution margin
# ---------------------------------------------------------------------------


@template("price_cut_volume", "contribution_margin", "price_volume", "price_volume", "numerical", 2,
          "price cut volume increase needed to preserve contribution variable cost")
def _price_cut_volume(rng: random.Random, o: dict[str, Any] | None) -> Generated:
    o = o or {}
    while True:
        price = o.get("price") or rng.choice([100, 120, 150, 200, 250, 400, 500, 800, 1000, 1200])
        vc = o.get("var_cost") or round(price * rng.choice([0.4, 0.5, 0.6, 0.65, 0.7]))
        new_price = o.get("new_price") or round(price * (1 - rng.choice([0.05, 0.1, 0.15, 0.2])))
        old_cm, new_cm = price - vc, new_price - vc
        if new_cm > 0.12 * price or o:
            break
    business, product, units = o.get("context") or _ctx(rng)
    ans = (old_cm / new_cm - 1) * 100
    rev = (price / new_price - 1) * 100
    cut = (price - new_price) / price * 100
    stem = (
        f"{business[0].upper() + business[1:]} sells a {product} for {inr(price)}. The variable cost is {inr(vc)} per "
        f"unit. Management proposes reducing the selling price to {inr(new_price)} while the variable cost stays "
        f"unchanged. By what percentage must sales volume increase to keep total contribution the same as before?"
    )
    steps = [
        f"Original contribution per unit = {inr(price)} − {inr(vc)} = {inr(old_cm)}.",
        f"New contribution per unit = {inr(new_price)} − {inr(vc)} = {inr(new_cm)}.",
        f"Required volume = old ÷ new contribution per unit = {old_cm} ÷ {new_cm} = {num(old_cm / new_cm, 3)}× the "
        f"original volume.",
        f"Required increase = ({num(old_cm / new_cm, 3)} − 1) × 100 = {num(ans, 1)}%.",
    ]
    return _g(
        "price_cut_volume", stem=stem, explanation=" ".join(steps)
        + f" Preserving revenue instead would need only {rev:.1f}% more volume, which ignores variable costs.",
        worked_steps=steps, numeric_answer=round(ans, 2), tolerance=0.6, tolerance_mode="abs", unit="%",
        assumptions="Variable cost per unit and fixed costs are unchanged; all units sell at the new price.",
        params={"price": price, "var_cost": vc, "new_price": new_price, "old_cm": old_cm, "new_cm": new_cm,
                "context": [business, product, units], "price_cut_pct": round(cut, 2)},
        signatures=[
            {"misconception_key": "contribution_vs_revenue", "value": round(rev, 2), "tolerance": 0.6,
             "label": f"{num(rev, 1)}% keeps revenue (price × units) constant, not contribution"},
            {"misconception_key": None, "hypothesis": "proportional_reasoning", "value": round(cut, 2),
             "tolerance": 0.6, "label": f"{cut:.1f}% simply mirrors the size of the price cut"},
        ],
    )


@template("price_increase_volume_loss", "contribution_margin", "price_volume", "price_volume_increase", "numerical",
          3, "price change volume needed to preserve contribution variable cost")
def _price_increase(rng: random.Random, o: dict[str, Any] | None) -> Generated:
    o = o or {}
    price = o.get("price") or rng.choice([200, 250, 300, 400, 500, 600])
    vc = o.get("var_cost") or round(price * rng.choice([0.5, 0.6, 0.7]))
    new_price = o.get("new_price") or round(price * (1 + rng.choice([0.1, 0.15, 0.2, 0.25])))
    business, product, units = o.get("context") or _ctx(rng)
    old_cm, new_cm = price - vc, new_price - vc
    ans = (1 - old_cm / new_cm) * 100
    rev = (1 - price / new_price) * 100
    stem = (
        f"{business[0].upper() + business[1:]} is considering raising the price of its {product} from {inr(price)} to "
        f"{inr(new_price)}. The variable cost stays at {inr(vc)} per unit. What is the largest percentage fall in "
        f"sales volume the business could accept and still earn the same total contribution as before?"
    )
    steps = [
        f"Contribution per unit rises from {inr(old_cm)} to {inr(new_cm)}.",
        f"Volume can fall to {old_cm} ÷ {new_cm} = {num(old_cm / new_cm, 3)} of the original level.",
        f"Maximum acceptable fall = (1 − {num(old_cm / new_cm, 3)}) × 100 = {num(ans, 1)}%.",
    ]
    return _g(
        "price_increase_volume_loss", stem=stem,
        explanation=" ".join(steps) + f" Using revenue instead would suggest only {rev:.1f}%, ignoring variable costs.",
        worked_steps=steps, numeric_answer=round(ans, 2), tolerance=0.6, tolerance_mode="abs", unit="%",
        assumptions="Variable cost per unit and fixed costs are unchanged.",
        params={"price": price, "var_cost": vc, "new_price": new_price, "old_cm": old_cm, "new_cm": new_cm,
                "context": [business, product, units]},
        signatures=[{"misconception_key": "contribution_vs_revenue", "value": round(rev, 2), "tolerance": 0.6,
                     "label": f"{num(rev, 1)}% keeps revenue constant rather than contribution"}],
    )


@template("promo_discount_contribution", "contribution_margin", "price_volume", "promo_total_contribution",
          "numerical", 2, "discount reduces contribution per unit total contribution revenue")
def _promo(rng: random.Random, o: dict[str, Any] | None) -> Generated:
    o = o or {}
    price = o.get("price") or rng.choice([400, 500, 600, 800, 1000])
    vc = o.get("var_cost") or round(price * rng.choice([0.5, 0.55, 0.6]))
    disc = o.get("discount") or rng.choice([10, 15, 20])
    q0 = o.get("units") or rng.choice([200, 300, 400, 500])
    q1 = o.get("new_units") or round(q0 * rng.choice([1.15, 1.2, 1.25, 1.3]))
    business, product, units = o.get("context") or _ctx(rng)
    p1 = round(price * (1 - disc / 100))
    c0, c1 = (price - vc) * q0, (p1 - vc) * q1
    ans = c1 - c0
    rev_change = p1 * q1 - price * q0
    stem = (
        f"{business[0].upper() + business[1:]} sells {q0} {units} a week at {inr(price)} each; the variable cost is "
        f"{inr(vc)} per unit. A {disc}% discount (new price {inr(p1)}) is expected to raise weekly sales to {q1} "
        f"{units}. What is the change in total weekly contribution, in rupees? (Use a negative number for a fall.)"
    )
    steps = [
        f"Current contribution = ({inr(price)} − {inr(vc)}) × {q0} = {inr(c0)}.",
        f"With the discount = ({inr(p1)} − {inr(vc)}) × {q1} = {inr(c1)}.",
        f"Change = {inr(c1)} − {inr(c0)} = {inr(ans)}.",
    ]
    return _g(
        "promo_discount_contribution", stem=stem,
        explanation=" ".join(steps) + f" Revenue changes by {inr(rev_change)}, which is not the same as contribution.",
        worked_steps=steps, numeric_answer=float(ans), tolerance=1.0, tolerance_mode="abs", unit="₹",
        assumptions="Fixed costs are unchanged; all units sell at the discounted price.",
        params={"price": price, "var_cost": vc, "discount": disc, "units": q0, "new_units": q1, "new_price": p1,
                "context": [business, product, units]},
        signatures=[
            {"misconception_key": "revenue_vs_profit", "value": float(rev_change), "tolerance": 1.0,
             "label": "Reports the change in revenue instead of contribution"},
            {"misconception_key": "contribution_vs_revenue", "value": float(rev_change), "tolerance": 1.0,
             "label": "Reports the change in revenue instead of contribution"},
        ],
    )


@template("break_even_volume", "contribution_margin", "break_even", "break_even", "numerical", 1,
          "break-even volume fixed costs divided by contribution margin per unit")
def _break_even(rng: random.Random, o: dict[str, Any] | None) -> Generated:
    o = o or {}
    price = o.get("price") or rng.choice([250, 400, 500, 750, 1000])
    vc = o.get("var_cost") or round(price * rng.choice([0.4, 0.5, 0.6]))
    cm = price - vc
    fixed = o.get("fixed") or cm * rng.choice([150, 200, 250, 300, 400, 600])
    business, product, units = o.get("context") or _ctx(rng)
    ans = fixed / cm
    steps = [f"Contribution per unit = {inr(price)} − {inr(vc)} = {inr(cm)}.",
             f"Break-even volume = {inr(fixed)} ÷ {inr(cm)} = {ans:,.0f} {units}."]
    return _g(
        "break_even_volume",
        stem=(f"{business[0].upper() + business[1:]} has monthly fixed costs of {inr(fixed)}. Its {product} sells for "
              f"{inr(price)} with a variable cost of {inr(vc)} per unit. How many {units} must it sell each month to "
              f"break even?"),
        explanation=" ".join(steps), worked_steps=steps, numeric_answer=round(ans, 2), tolerance=0.5,
        tolerance_mode="abs", unit=units, assumptions="Price and variable cost per unit are constant.",
        params={"price": price, "var_cost": vc, "fixed": fixed, "cm": cm, "context": [business, product, units]},
        signatures=[{"misconception_key": "revenue_vs_profit", "value": round(fixed / price, 2), "tolerance": 0.5,
                     "label": "Divides fixed costs by price (revenue) instead of contribution per unit"}],
    )


@template("special_order", "contribution_margin", "marginal_cost", "incremental_decision", "numerical", 3,
          "one-off order marginal incremental cost average total cost spare capacity")
def _special_order(rng: random.Random, o: dict[str, Any] | None) -> Generated:
    o = o or {}
    vc = o.get("var_cost") or rng.choice([150, 200, 250, 300, 400])
    atc = o.get("avg_total_cost") or round(vc * rng.choice([1.25, 1.3, 1.4]))
    offer = o.get("offer") or round((vc + atc) / 2)
    n = o.get("units") or rng.choice([80, 100, 150, 200, 250])
    business, product, units = o.get("context") or _ctx(rng)
    ans = (offer - vc) * n
    steps = ["Only variable cost changes with this order; fixed costs are paid anyway.",
             f"Incremental contribution = ({inr(offer)} − {inr(vc)}) × {n} = {inr(ans)}."]
    return _g(
        "special_order",
        stem=(f"{business[0].upper() + business[1:]} has spare capacity. Its variable cost is {inr(vc)} per "
              f"{product} and its average total cost, including allocated rent, is {inr(atc)}. A one-off customer "
              f"offers {inr(offer)} each for {n} {units}, and fixed costs will not change. By how many rupees would "
              f"accepting the order change profit?"),
        explanation=" ".join(steps) + " Comparing with average total cost wrongly charges the order for rent that is "
        "paid regardless.",
        worked_steps=steps, numeric_answer=float(ans), tolerance=1.0, tolerance_mode="abs", unit="₹",
        assumptions="Spare capacity exists, fixed costs are unchanged and the order does not affect other sales.",
        params={"var_cost": vc, "avg_total_cost": atc, "offer": offer, "units": n, "context": [business, product, units]},
        signatures=[{"misconception_key": "total_vs_marginal_cost", "value": float((offer - atc) * n),
                     "tolerance": 1.0, "label": "Uses average total cost (including fixed costs) for the decision"}],
    )


@template("unit_contribution_ratio", "contribution_margin", None, "cm_ratio", "numerical", 1,
          "contribution margin ratio price minus variable cost divided by price")
def _cm_ratio(rng: random.Random, o: dict[str, Any] | None) -> Generated:
    o = o or {}
    price = o.get("price") or rng.choice([200, 250, 400, 500, 800, 1000, 1200])
    vc = o.get("var_cost") or round(price * rng.choice([0.45, 0.55, 0.6, 0.7, 0.75]))
    business, product, units = o.get("context") or _ctx(rng)
    ans = (price - vc) / price * 100
    steps = [f"Contribution per unit = {inr(price)} − {inr(vc)} = {inr(price - vc)}.",
             f"Contribution margin ratio = {inr(price - vc)} ÷ {inr(price)} = {ans:.1f}%."]
    return _g(
        "unit_contribution_ratio",
        stem=(f"{business[0].upper() + business[1:]} sells a {product} for {inr(price)}; the variable cost is "
              f"{inr(vc)} per unit. What is the contribution margin ratio, in percent?"),
        explanation=" ".join(steps), worked_steps=steps, numeric_answer=round(ans, 2), tolerance=0.6,
        tolerance_mode="abs", unit="%", params={"price": price, "var_cost": vc, "context": [business, product, units]},
        signatures=[{"misconception_key": None, "hypothesis": "inverted_ratio", "value": round(vc / price * 100, 2),
                     "tolerance": 0.6, "label": "Reports the variable-cost ratio instead"}],
    )


# ---------------------------------------------------------------------------
# ROAS
# ---------------------------------------------------------------------------


@template("roas_compute", "roas", None, "roas_basic", "numerical", 1,
          "ROAS attributed revenue divided by advertising spend")
def _roas(rng: random.Random, o: dict[str, Any] | None) -> Generated:
    o = o or {}
    spend = o.get("spend") or rng.choice([20000, 40000, 50000, 80000, 120000])
    roas = o.get("roas") or rng.choice([1.5, 2.0, 2.5, 3.2, 4.0, 6.0])
    rev = round(spend * roas)
    business, _, _ = o.get("context") or _ctx(rng)
    steps = [f"ROAS = attributed revenue ÷ ad spend = {inr(rev)} ÷ {inr(spend)} = {rev / spend:.2f}."]
    return _g(
        "roas_compute",
        stem=(f"{business[0].upper() + business[1:]} spent {inr(spend)} on a search campaign that is credited with "
              f"{inr(rev)} of revenue. What is the campaign's ROAS (as a multiple, e.g. 2.5)?"),
        explanation=steps[0], worked_steps=steps, numeric_answer=round(rev / spend, 3), tolerance=0.05,
        tolerance_mode="abs", unit="x", params={"spend": spend, "revenue": rev, "context": [business, "", ""]},
        signatures=[{"misconception_key": None, "hypothesis": "inverted_ratio", "value": round(spend / rev, 3),
                     "tolerance": 0.02, "label": "Divides spend by revenue"}],
    )


@template("campaign_contribution", "roas", "break_even_roas", "campaign_profit", "numerical", 2,
          "contribution after advertising attributed revenue times contribution margin ratio minus advertising spend")
def _campaign_contribution(rng: random.Random, o: dict[str, Any] | None) -> Generated:
    o = o or {}
    spend = o.get("spend") or rng.choice([20000, 30000, 50000, 60000, 80000])
    m = o.get("cm_ratio") or rng.choice([0.25, 0.3, 0.35, 0.4, 0.5])
    roas = o.get("roas") or rng.choice([1.6, 1.8, 2.0, 2.2, 3.0, 3.5])
    rev = round(spend * roas)
    business, _, _ = o.get("context") or _ctx(rng)
    ans = rev * m - spend
    steps = [f"Contribution from attributed sales = {inr(rev)} × {m:.0%} = {inr(rev * m)}.",
             f"Contribution after advertising = {inr(rev * m)} − {inr(spend)} = {inr(ans)}."]
    return _g(
        "campaign_contribution",
        stem=(f"{business[0].upper() + business[1:]} spent {inr(spend)} on social ads credited with {inr(rev)} of "
              f"revenue (ROAS {roas:.1f}). Its contribution margin ratio is {m:.0%}. What is the campaign's "
              f"contribution after advertising, in rupees? (Use a negative number for a loss.)"),
        explanation=" ".join(steps) + f" Break-even ROAS here is 1 ÷ {m:.0%} = {1 / m:.2f}.",
        worked_steps=steps, numeric_answer=float(ans), tolerance=1.0, tolerance_mode="abs", unit="₹",
        assumptions="All attributed revenue is incremental and earns the stated contribution margin ratio.",
        params={"spend": spend, "revenue": rev, "cm_ratio": m, "roas": roas, "context": [business, "", ""]},
        signatures=[{"misconception_key": "roas_vs_profitability", "value": float(rev - spend), "tolerance": 1.0,
                     "label": "Treats revenue minus ad spend as profit (ignores variable costs)"}],
    )


@template("breakeven_roas", "roas", "break_even_roas", "breakeven_roas", "numerical", 2,
          "break-even ROAS equals 1 divided by contribution margin ratio")
def _breakeven_roas(rng: random.Random, o: dict[str, Any] | None) -> Generated:
    o = o or {}
    m = o.get("cm_ratio") or rng.choice([0.2, 0.25, 0.3, 0.4, 0.5, 0.6])
    business, product, _ = o.get("context") or _ctx(rng)
    ans = 1 / m
    steps = [f"A campaign breaks even when revenue × {m:.0%} = ad spend.", f"So ROAS must be 1 ÷ {m:.0%} = {ans:.2f}."]
    return _g(
        "breakeven_roas",
        stem=(f"{business[0].upper() + business[1:]} earns a {m:.0%} contribution margin ratio on its {product}. What "
              f"is the minimum ROAS a campaign needs for its contribution to cover its advertising spend?"),
        explanation=" ".join(steps), worked_steps=steps, numeric_answer=round(ans, 3), tolerance=0.05,
        tolerance_mode="abs", unit="x", params={"cm_ratio": m, "context": [business, product, ""]},
        signatures=[{"misconception_key": "roas_vs_profitability", "value": 1.0, "tolerance": 0.01,
                     "label": "Assumes a ROAS of 1 is break-even"}],
    )


# ---------------------------------------------------------------------------
# CAC / CLV
# ---------------------------------------------------------------------------


@template("cac_compute", "cac_clv", None, "cac_basic", "numerical", 1,
          "customer acquisition cost spend divided by new customers")
def _cac(rng: random.Random, o: dict[str, Any] | None) -> Generated:
    o = o or {}
    n = o.get("customers") or rng.choice([400, 500, 800, 1000, 1200, 1500])
    cac = o.get("cac") or rng.choice([150, 200, 250, 300, 450, 600])
    spend = n * cac
    business, who = o.get("context") or rng.choice(SUBSCRIPTION_CONTEXTS)
    steps = [f"CAC = {inr(spend)} ÷ {n:,} = {inr(cac)}."]
    return _g(
        "cac_compute",
        stem=(f"{business[0].upper() + business[1:]} spent {inr(spend)} on sales and marketing last quarter and "
              f"acquired {n:,} new {who}s. What was its customer acquisition cost (CAC) in rupees?"),
        explanation=steps[0], worked_steps=steps, numeric_answer=float(cac), tolerance=0.5, tolerance_mode="abs",
        unit="₹", params={"spend": spend, "customers": n, "context": [business, who]},
        signatures=[],
    )


@template("clv_contribution", "cac_clv", None, "clv", "numerical", 2,
          "customer lifetime value monthly contribution expected lifetime contribution not revenue")
def _clv(rng: random.Random, o: dict[str, Any] | None) -> Generated:
    o = o or {}
    r = o.get("monthly_revenue") or rng.choice([300, 400, 500, 600, 800, 1000])
    m = o.get("cm_ratio") or rng.choice([0.3, 0.35, 0.4, 0.5])
    life = o.get("months") or rng.choice([6, 10, 12, 15, 18, 24])
    business, who = o.get("context") or rng.choice(SUBSCRIPTION_CONTEXTS)
    ans = r * m * life
    steps = [f"Monthly contribution = {inr(r)} × {m:.0%} = {inr(r * m)}.",
             f"CLV = {inr(r * m)} × {life} months = {inr(ans)}."]
    return _g(
        "clv_contribution",
        stem=(f"A {who} of {business} pays {inr(r)} per month, the contribution margin ratio is {m:.0%}, and the "
              f"expected lifetime is {life} months. What is the contribution-based customer lifetime value (CLV) in "
              f"rupees?"),
        explanation=" ".join(steps), worked_steps=steps, numeric_answer=round(ans, 2), tolerance=1.0,
        tolerance_mode="abs", unit="₹", assumptions="Constant monthly revenue and margin; no discounting.",
        params={"monthly_revenue": r, "cm_ratio": m, "months": life, "context": [business, who]},
        signatures=[{"misconception_key": "cac_vs_clv", "value": float(r * life), "tolerance": 1.0,
                     "label": "Builds lifetime value from revenue instead of contribution"}],
    )


@template("payback_months", "cac_clv", "payback", "payback", "numerical", 2,
          "payback period CAC divided by monthly contribution per customer")
def _payback(rng: random.Random, o: dict[str, Any] | None) -> Generated:
    o = o or {}
    r = o.get("monthly_revenue") or rng.choice([400, 500, 600, 800, 1000])
    m = o.get("cm_ratio") or rng.choice([0.25, 0.3, 0.4, 0.5])
    months = o.get("months") or rng.choice([3, 4, 5, 6, 8])
    cac = round(r * m * months)
    business, who = o.get("context") or rng.choice(SUBSCRIPTION_CONTEXTS)
    steps = [f"Monthly contribution = {inr(r)} × {m:.0%} = {inr(r * m)}.",
             f"Payback = {inr(cac)} ÷ {inr(r * m)} = {cac / (r * m):.2f} months."]
    return _g(
        "payback_months",
        stem=(f"{business[0].upper() + business[1:]} spends {inr(cac)} to acquire each {who}. A {who} pays {inr(r)} "
              f"per month at a {m:.0%} contribution margin ratio. How many months does it take to recover the "
              f"acquisition cost?"),
        explanation=" ".join(steps), worked_steps=steps, numeric_answer=round(cac / (r * m), 3), tolerance=0.05,
        tolerance_mode="abs", unit="months",
        params={"cac": cac, "monthly_revenue": r, "cm_ratio": m, "context": [business, who]},
        signatures=[{"misconception_key": "cac_vs_clv", "value": round(cac / r, 3), "tolerance": 0.05,
                     "label": "Divides CAC by revenue instead of contribution"}],
    )


# ---------------------------------------------------------------------------
# Revenue & conversion
# ---------------------------------------------------------------------------


@template("conversion_change_pp", "revenue_conversion", "pp_vs_percent", "pp_change", "numerical", 1,
          "percentage point change difference between two percentages conversion rate")
def _pp(rng: random.Random, o: dict[str, Any] | None) -> Generated:
    o = o or {}
    a = o.get("from") or rng.choice([2.0, 2.5, 3.0, 4.0, 5.0])
    b = o.get("to") or a + rng.choice([0.5, 1.0, 1.5, 2.0])
    business, _, _ = o.get("context") or _ctx(rng)
    steps = [f"Percentage-point change = {b:g}% − {a:g}% = {b - a:g} points."]
    return _g(
        "conversion_change_pp",
        stem=(f"The checkout conversion rate at {business} rose from {a:g}% to {b:g}%. By how many percentage points "
              f"did it rise?"),
        explanation=steps[0] + f" (As a percent change that would be {(b - a) / a * 100:.1f}%.)", worked_steps=steps,
        numeric_answer=round(b - a, 3), tolerance=0.01, tolerance_mode="abs", unit="percentage points",
        params={"from": a, "to": b, "context": [business, "", ""]},
        signatures=[{"misconception_key": "pp_vs_percent_change", "value": round((b - a) / a * 100, 2),
                     "tolerance": 0.6, "label": "Gives the percent change instead of the percentage-point change"}],
    )


@template("conversion_change_pct", "revenue_conversion", "pp_vs_percent", "pct_change", "numerical", 2,
          "percent change relative to starting value conversion rate percentage points")
def _pct(rng: random.Random, o: dict[str, Any] | None) -> Generated:
    o = o or {}
    a = o.get("from") or rng.choice([2.0, 2.5, 4.0, 5.0, 8.0])
    b = o.get("to") or a + rng.choice([0.5, 1.0, 2.0])
    business, _, _ = o.get("context") or _ctx(rng)
    ans = (b - a) / a * 100
    steps = [f"Percent change = ({b:g} − {a:g}) ÷ {a:g} = {ans:.1f}%."]
    return _g(
        "conversion_change_pct",
        stem=(f"An email campaign's click-through rate at {business} went from {a:g}% to {b:g}%. What is the percent "
              f"change in the click-through rate?"),
        explanation=steps[0] + f" The percentage-point change is {b - a:g}.", worked_steps=steps,
        numeric_answer=round(ans, 2), tolerance=0.6, tolerance_mode="abs", unit="%",
        params={"from": a, "to": b, "context": [business, "", ""]},
        signatures=[{"misconception_key": "pp_vs_percent_change", "value": round(b - a, 3), "tolerance": 0.01,
                     "label": "Gives the percentage-point difference instead of the percent change"}],
    )


@template("rate_vs_absolute", "revenue_conversion", "rate_vs_absolute", "rate_vs_absolute", "mcq", 2,
          "high conversion rate does not guarantee more conversions absolute conversions visitors")
def _rate_vs_abs(rng: random.Random, o: dict[str, Any] | None) -> Generated:
    o = o or {}
    va = o.get("visitors_a") or rng.choice([400, 600, 800, 1000])
    ra = o.get("rate_a") or rng.choice([6.0, 7.0, 8.0, 9.0])
    vb = o.get("visitors_b") or va * rng.choice([4, 5, 6])
    rb = o.get("rate_b") or rng.choice([2.0, 2.5, 3.0])
    ca, cb = va * ra / 100, vb * rb / 100
    if abs(ca - cb) < 1:
        vb += 500
        cb = vb * rb / 100
    business, _, _ = o.get("context") or _ctx(rng)
    better = "B" if cb > ca else "A"
    opts = [
        {"id": "a", "text": f"Page A, because its conversion rate ({ra:g}%) is higher"},
        {"id": "b", "text": f"Page B: about {cb:,.0f} customers compared with {ca:,.0f} for page A"},
        {"id": "c", "text": "Both pages produced the same number of customers"},
        {"id": "d", "text": f"Page A: about {ca:,.0f} customers compared with {cb:,.0f} for page B"},
    ]
    correct = "b" if better == "B" else "d"
    steps = [f"Page A customers = {va:,} × {ra:g}% = {ca:,.0f}.", f"Page B customers = {vb:,} × {rb:g}% = {cb:,.0f}."]
    return _g(
        "rate_vs_absolute",
        stem=(f"{business[0].upper() + business[1:]} ran two landing pages last month. Page A converted {ra:g}% of "
              f"{va:,} visitors; page B converted {rb:g}% of {vb:,} visitors. Which page produced more customers?"),
        explanation=" ".join(steps) + " The conversion rate alone does not tell you which page produced more customers.",
        worked_steps=steps, options=opts, correct_option_id=correct,
        params={"visitors_a": va, "rate_a": ra, "visitors_b": vb, "rate_b": rb, "context": [business, "", ""]},
        signatures=[{"misconception_key": "conversion_rate_vs_absolute", "option_id": "a",
                     "label": "Chooses by conversion rate alone"}],
    )


@template("channel_revenue_compare", "revenue_conversion", "rate_vs_absolute", "channel_revenue", "numerical", 2,
          "conversions visitors conversion rate average order value revenue by channel")
def _channel_rev(rng: random.Random, o: dict[str, Any] | None) -> Generated:
    o = o or {}
    v = o.get("visitors") or rng.choice([5000, 8000, 10000, 20000, 25000])
    r = o.get("rate") or rng.choice([1.5, 2.0, 2.5, 3.0, 4.0])
    aov = o.get("aov") or rng.choice([800, 1200, 1500, 2000, 2500])
    business, _, _ = o.get("context") or _ctx(rng)
    conv = v * r / 100
    ans = conv * aov
    steps = [f"Conversions = {v:,} × {r:g}% = {conv:,.0f}.", f"Revenue = {conv:,.0f} × {inr(aov)} = {inr(ans)}."]
    return _g(
        "channel_revenue_compare",
        stem=(f"A referral channel sent {v:,} visitors to {business}. {r:g}% of them bought, with an average order "
              f"value of {inr(aov)}. How much revenue (₹) did the channel generate?"),
        explanation=" ".join(steps), worked_steps=steps, numeric_answer=float(ans), tolerance=1.0,
        tolerance_mode="abs", unit="₹", params={"visitors": v, "rate": r, "aov": aov, "context": [business, "", ""]},
        signatures=[{"misconception_key": "conversion_rate_vs_absolute", "value": float(r * aov), "tolerance": 1.0,
                     "label": "Multiplies the rate by order value without the number of visitors"}],
    )


# ---------------------------------------------------------------------------
# Decisions under assumptions
# ---------------------------------------------------------------------------


def _order_values(rng: random.Random) -> list[int]:
    base = sorted(rng.sample(range(5, 16), 4))
    vals = [b * 100 for b in base]
    vals.append(rng.choice([6000, 7500, 8800, 9600, 12000]))
    return vals


@template("mean_median", "decision_assumptions", "mean_median", "typical_value", "numerical", 1,
          "median typical order skewed data mean pulled up by large order")
def _mean_median(rng: random.Random, o: dict[str, Any] | None) -> Generated:
    o = o or {}
    vals = o.get("values") or _order_values(rng)
    business, _, _ = o.get("context") or _ctx(rng)
    med = statistics.median(vals)
    mean = statistics.mean(vals)
    shown = vals[:]
    rng.shuffle(shown)
    steps = [f"Sorted: {', '.join(inr(v) for v in sorted(vals))}.", f"The median (middle value) is {inr(med)}.",
             f"The mean, {inr(mean)}, is pulled up by the single large order."]
    return _g(
        "mean_median",
        stem=(f"Five recent orders at {business} were worth {', '.join(inr(v) for v in shown)}. What value best "
              f"describes a typical order, in rupees?"),
        explanation=" ".join(steps), worked_steps=steps, numeric_answer=float(med), tolerance=0.5,
        tolerance_mode="abs", unit="₹", params={"values": vals, "context": [business, "", ""]},
        signatures=[{"misconception_key": "mean_vs_median", "value": round(float(mean), 2), "tolerance": 0.5,
                     "label": "Uses the mean, which the outlier pulls upwards"}],
    )


@template("mean_median_total", "decision_assumptions", "mean_median", "total_from_mean", "numerical", 2,
          "mean multiplied by count gives total median typical")
def _mean_total(rng: random.Random, o: dict[str, Any] | None) -> Generated:
    o = o or {}
    n = o.get("orders") or rng.choice([200, 250, 400, 500])
    mean = o.get("mean") or rng.choice([1800, 2200, 2600, 3000])
    median = o.get("median") or round(mean * rng.choice([0.4, 0.5, 0.6]))
    business, _, _ = o.get("context") or _ctx(rng)
    ans = n * mean
    steps = [f"Totals come from the mean: {n} × {inr(mean)} = {inr(ans)}.",
             "The median describes a typical order but cannot be multiplied up to a total for skewed data."]
    return _g(
        "mean_median_total",
        stem=(f"Last week {business} received {n} orders. The mean order value was {inr(mean)} and the median was "
              f"{inr(median)}. What was the total value of the week's orders, in rupees?"),
        explanation=" ".join(steps), worked_steps=steps, numeric_answer=float(ans), tolerance=1.0,
        tolerance_mode="abs", unit="₹", params={"orders": n, "mean": mean, "median": median,
                                                "context": [business, "", ""]},
        signatures=[{"misconception_key": "mean_vs_median", "value": float(n * median), "tolerance": 1.0,
                     "label": "Multiplies the median (not the mean) by the count"}],
    )


@template("scenario_contribution", "decision_assumptions", "sensitivity", "scenario", "numerical", 3,
          "scenario analysis contribution after ad spend conversion rate average order value contribution margin ratio")
def _scenario(rng: random.Random, o: dict[str, Any] | None) -> Generated:
    o = o or {}
    visitors = o.get("visitors") or rng.choice([20000, 30000, 40000, 50000])
    rate = o.get("rate") or rng.choice([1.0, 1.5, 2.0, 2.5])
    aov = o.get("aov") or rng.choice([1200, 1500, 1800, 2000])
    m = o.get("cm_ratio") or rng.choice([0.3, 0.35, 0.4])
    spend = o.get("spend") or rng.choice([50000, 80000, 100000, 150000])
    business, _, _ = o.get("context") or _ctx(rng)
    orders = visitors * rate / 100
    rev = orders * aov
    ans = rev * m - spend
    steps = [f"Orders = {visitors:,} × {rate:g}% = {orders:,.0f}.", f"Revenue = {orders:,.0f} × {inr(aov)} = {inr(rev)}.",
             f"Contribution = {inr(rev)} × {m:.0%} = {inr(rev * m)}.",
             f"After ad spend: {inr(rev * m)} − {inr(spend)} = {inr(ans)}."]
    return _g(
        "scenario_contribution",
        stem=(f"In the pessimistic scenario for a campaign run by {business}: {visitors:,} visitors, a {rate:g}% conversion "
              f"rate, an average order value of {inr(aov)}, a {m:.0%} contribution margin ratio and {inr(spend)} of "
              f"ad spend. What is the contribution after ad spend, in rupees?"),
        explanation=" ".join(steps), worked_steps=steps, numeric_answer=float(round(ans, 2)), tolerance=1.0,
        tolerance_mode="abs", unit="₹",
        params={"visitors": visitors, "rate": rate, "aov": aov, "cm_ratio": m, "spend": spend,
                "context": [business, "", ""]},
        signatures=[
            {"misconception_key": "revenue_vs_profit", "value": float(round(rev - spend, 2)), "tolerance": 1.0,
             "label": "Subtracts ad spend from revenue rather than contribution"},
            {"misconception_key": "roas_vs_profitability", "value": float(round(rev - spend, 2)), "tolerance": 1.0,
             "label": "Subtracts ad spend from revenue rather than contribution"},
        ],
    )


def generate(key: str, seed: int, overrides: dict[str, Any] | None = None) -> Generated:
    return TEMPLATES[key].build(random.Random(seed), overrides)


def templates_for_concept(concept_key: str) -> list[Template]:
    return [t for t in TEMPLATES.values() if t.concept_key == concept_key]
