"""Independent plug-back checks for template answers.

Each check substitutes the claimed answer back into the *defining condition* of the
problem (e.g. "at the new price and the claimed volume, total contribution equals the
old total contribution") rather than re-running the template's formula. A template
answer is only accepted if its plug-back check passes.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable
from typing import Any

Check = Callable[[dict[str, Any], Any], bool]


def _close(a: float, b: float, rel: float = 1e-3, abs_: float = 0.02) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_)


def _price_cut(p: dict[str, Any], a: float) -> bool:
    q_old = 1000.0
    q_new = q_old * (1 + a / 100)
    old_total = (p["price"] - p["var_cost"]) * q_old
    new_total = (p["new_price"] - p["var_cost"]) * q_new
    return _close(old_total, new_total, rel=2e-3)


def _price_inc(p: dict[str, Any], a: float) -> bool:
    q_old = 1000.0
    q_new = q_old * (1 - a / 100)
    return _close((p["price"] - p["var_cost"]) * q_old, (p["new_price"] - p["var_cost"]) * q_new, rel=2e-3)


def _promo(p: dict[str, Any], a: float) -> bool:
    rev0, vc0 = p["price"] * p["units"], p["var_cost"] * p["units"]
    rev1, vc1 = p["new_price"] * p["new_units"], p["var_cost"] * p["new_units"]
    return _close((rev1 - vc1) - (rev0 - vc0), a, abs_=0.5)


def _break_even(p: dict[str, Any], a: float) -> bool:
    profit = p["price"] * a - p["var_cost"] * a - p["fixed"]
    return abs(profit) <= max(1.0, 0.002 * p["fixed"])


def _special(p: dict[str, Any], a: float) -> bool:
    revenue = p["offer"] * p["units"]
    extra_cost = p["var_cost"] * p["units"]  # fixed costs unchanged by assumption
    return _close(revenue - extra_cost, a, abs_=0.5)


def _cm_ratio(p: dict[str, Any], a: float) -> bool:
    return _close(p["price"] * a / 100, p["price"] - p["var_cost"], abs_=0.05)


def _roas(p: dict[str, Any], a: float) -> bool:
    return _close(p["spend"] * a, p["revenue"], rel=2e-3)


def _campaign(p: dict[str, Any], a: float) -> bool:
    variable_costs = p["revenue"] * (1 - p["cm_ratio"])
    return _close(p["revenue"] - variable_costs - p["spend"], a, abs_=0.5)


def _be_roas(p: dict[str, Any], a: float) -> bool:
    spend = 1000.0
    revenue = spend * a
    return abs(revenue * p["cm_ratio"] - spend) <= 1.0


def _cac(p: dict[str, Any], a: float) -> bool:
    return _close(a * p["customers"], p["spend"], abs_=0.5)


def _clv(p: dict[str, Any], a: float) -> bool:
    monthly = sum(p["monthly_revenue"] * p["cm_ratio"] for _ in range(p["months"]))
    return _close(monthly, a, abs_=0.5)


def _payback(p: dict[str, Any], a: float) -> bool:
    return _close(a * p["monthly_revenue"] * p["cm_ratio"], p["cac"], abs_=1.0)


def _pp(p: dict[str, Any], a: float) -> bool:
    return _close(p["from"] + a, p["to"], abs_=1e-6)


def _pct(p: dict[str, Any], a: float) -> bool:
    return _close(p["from"] * (1 + a / 100), p["to"], abs_=0.01)


def _channel(p: dict[str, Any], a: float) -> bool:
    return _close(a / p["aov"] / p["visitors"] * 100, p["rate"], abs_=1e-4)


def _median(p: dict[str, Any], a: float) -> bool:
    vals = sorted(p["values"])
    below = sum(1 for v in vals if v < a)
    above = sum(1 for v in vals if v > a)
    return below == above and a in vals


def _mean_total(p: dict[str, Any], a: float) -> bool:
    return _close(a / p["orders"], p["mean"], abs_=0.01)


def _scenario(p: dict[str, Any], a: float) -> bool:
    rate = (a + p["spend"]) / p["cm_ratio"] / p["aov"] / p["visitors"] * 100
    return _close(rate, p["rate"], abs_=1e-3)


def _rate_vs_abs(p: dict[str, Any], correct_option: Any) -> bool:
    ca = p["visitors_a"] * p["rate_a"]
    cb = p["visitors_b"] * p["rate_b"]
    return correct_option == ("b" if cb > ca else "d")


CHECKS: dict[str, Check] = {
    "price_cut_volume": _price_cut,
    "price_increase_volume_loss": _price_inc,
    "promo_discount_contribution": _promo,
    "break_even_volume": _break_even,
    "special_order": _special,
    "unit_contribution_ratio": _cm_ratio,
    "roas_compute": _roas,
    "campaign_contribution": _campaign,
    "breakeven_roas": _be_roas,
    "cac_compute": _cac,
    "clv_contribution": _clv,
    "payback_months": _payback,
    "conversion_change_pp": _pp,
    "conversion_change_pct": _pct,
    "channel_revenue_compare": _channel,
    "mean_median": _median,
    "mean_median_total": _mean_total,
    "scenario_contribution": _scenario,
    "rate_vs_absolute": _rate_vs_abs,
}


def plug_back(template_key: str, params: dict[str, Any], answer: Any) -> bool | None:
    chk = CHECKS.get(template_key)
    if chk is None:
        return None
    try:
        return bool(chk(params, answer))
    except (KeyError, TypeError, ZeroDivisionError, statistics.StatisticsError):
        return False
