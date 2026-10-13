"""Ocena okazji SAFE / OPTIMAL / RISKY i SWOT."""

import time
from datetime import datetime, timezone, timedelta

from edtrade import assess
from edtrade import tce_theme as tce
from edtrade.trade import NearbyTrade


def _iso(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def trade(per_t=3000, units=256, demand=5000, age=1, travel=300, ls=500):
    return NearbyTrade(commodity="gold", buy_price=1000, units=units, sell_price=1000 + per_t, demand=demand,
                       sell_station="X", distance_to_arrival=ls, updated_at=_iso(age) if age is not None else "",
                       travel_s=travel)


def test_best_fresh_deep_demand_is_optimal_and_strong():
    best, other = trade(), trade(per_t=500)
    a, b = assess.assess_all([best, other], assess.value_for_mode("per_hour"), capacity=256)
    assert a.verdict == assess.OPTIMAL and a.degree > 0.8
    assert "best in list" in a.strengths and "fresh prices" in a.strengths
    assert b.verdict == assess.SAFE  # mały zysk, ale pewny


def test_stale_prices_are_risky_and_threat_listed():
    a = assess.assess_all([trade(age=24 * 5)], assess.value_for_mode("per_hour"))[0]
    assert a.verdict == assess.RISKY
    assert any(t.startswith("prices 5 d") for t in a.threats)


def test_shallow_demand_raises_risk():
    deep = assess.assess_all([trade(demand=5000)], assess.value_for_mode("per_hour"))[0]
    shallow = assess.assess_all([trade(demand=256)], assess.value_for_mode("per_hour"))[0]
    assert shallow.risk > deep.risk and any("shallow demand" in t for t in shallow.threats)


def test_risk_degree_grows_with_age():
    d3 = assess.assess_all([trade(age=60, demand=300)], assess.value_for_mode("per_hour"))[0]
    d7 = assess.assess_all([trade(age=24 * 7, demand=300)], assess.value_for_mode("per_hour"))[0]
    assert d3.verdict == d7.verdict == assess.RISKY and d7.degree > d3.degree


def test_partial_hold_is_weakness():
    a = assess.assess_all([trade(units=100)], assess.value_for_mode("per_hour"), capacity=256)[0]
    assert "only 100/256 t" in a.weaknesses


def test_colour_intensity_levels():
    weak, strong = tce.verdict_color("optimal", 0.1), tce.verdict_color("optimal", 0.99)
    assert strong == tce.GREEN and weak != strong
    assert tce.verdict_tag("risky", 0.99) == "v_risky_3" and tce.verdict_tag("safe", 0.0) == "v_safe_0"


def test_route_hop_verdict():
    assert assess.assess_route_hop(1)[0] == assess.OPTIMAL
    assert assess.assess_route_hop(24 * 6)[0] == assess.RISKY


def test_cargo_sell_here_when_local_price_close():
    best = trade(per_t=3000)  # sprzedaż 4000 gdzie indziej
    a = assess.advise_cargo(100, best, None, here_price=3900, mean_price=3500)
    assert a.action == assess.SELL_HERE and a.badge == "▲ SELL HERE" and a.verdict == "optimal"
    assert "no trip" in a.strengths


def test_cargo_sell_there_when_much_better_and_carries_trade_verdict():
    best = trade(per_t=3000)
    best_v = assess.assess_all([best], assess.value_for_mode("per_hour"))[0]
    a = assess.advise_cargo(100, best, best_v, here_price=2000)
    assert a.action == assess.SELL_THERE and a.verdict == best_v.verdict
    assert a.strengths[0] == "+200,000 cr vs selling here"


def test_cargo_hold_on_loss_no_buyer_or_below_mean():
    assert assess.advise_cargo(10, None).action == assess.HOLD
    loss = assess.advise_cargo(10, trade(per_t=0), None, paid_price=5000)  # najlepiej 1000 < 5000
    assert loss.action == assess.HOLD and loss.threats == ["loss 4,000 cr/t"]
    low = assess.advise_cargo(10, None, None, here_price=500, mean_price=1000)
    assert low.action == assess.HOLD and low.verdict == "hold" and "50% below" in low.weaknesses[0]
