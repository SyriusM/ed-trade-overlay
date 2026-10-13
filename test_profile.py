"""Profil ryzyka SAFE / OPTIMAL / RISKY zmienia wybór okazji."""

from datetime import datetime, timezone, timedelta

from edtrade import trade as T


def _t(per_t, age_h, demand=10_000):
    return T.NearbyTrade(commodity="x", buy_price=1000, units=300, sell_price=1000 + per_t, demand=demand,
                         updated_at=(datetime.now(timezone.utc) - timedelta(hours=age_h)).isoformat(), travel_s=300)


def test_profiles_pick_differently():
    stale_big = _t(20_000, age_h=24 * 5)   # duży zysk, ceny sprzed 5 dni
    fresh_small = _t(12_000, age_h=1)      # mniejszy, pewny
    cands = [[stale_big], [fresh_small]]
    assert T.rank_trades(cands, "per_hour", "risky")[0] is stale_big
    assert T.rank_trades(cands, "per_hour", "safe")[0] is fresh_small
    # OPTIMAL: 20k × 0.5 = 10k < 12k × 1.0 → pewny
    assert T.rank_trades(cands, "per_hour", "optimal")[0] is fresh_small


def test_global_profile_used_by_default():
    stale_big, fresh_small = _t(20_000, 24 * 5), _t(12_000, 1)
    try:
        T.set_risk_profile("risky")
        assert T.rank_trades([[stale_big], [fresh_small]])[0] is stale_big
        T.set_risk_profile("nonsense")
        assert T.RISK_PROFILE == "auto"
    finally:
        T.set_risk_profile("auto")


def test_safe_penalises_shallow_demand():
    deep, shallow = _t(10_000, 1, demand=10_000), _t(11_000, 1, demand=300)
    assert T.rank_trades([[deep], [shallow]], "per_hour", "safe")[0] is deep
    assert T.rank_trades([[deep], [shallow]], "per_hour", "risky")[0] is shallow


def test_risky_prefers_expensive_goods_and_stays_careful_with_cheap():
    cheap_stale, cheap_fresh = _t(3_000, 24 * 5), _t(2_200, 1)
    # tani towar: stare ceny nie są warte ryzyka — RISKY wybiera pewny (jak OPTIMAL)
    assert T.rank_trades([[cheap_stale], [cheap_fresh]], "total", "risky")[0] is cheap_fresh
    # drogi towar: ryzyko się opłaca, a przy podobnym zysku całkowitym wygrywa droższy towar
    pricey = _t(25_000, 24 * 2, demand=100_000)
    pricey.units = 100                     # 2.5M za kurs, ceny sprzed 2 dni
    bulk = _t(8_000, 1)                    # 2.4M za kurs (300 t), świeże
    assert T.rank_trades([[pricey], [bulk]], "total", "risky")[0] is pricey
    assert T.rank_trades([[pricey], [bulk]], "total", "optimal")[0] is bulk


def test_optimal_prefers_expensive_only_when_fresh():
    pricey_fresh, bulk_fresh = _t(25_000, 2, demand=100_000), _t(8_000, 2)
    pricey_fresh.units = 100            # 2.5M vs 2.4M, oba świeże → droższy
    assert T.rank_trades([[pricey_fresh], [bulk_fresh]], "total", "optimal")[0] is pricey_fresh
    pricey_old = _t(25_000, 24 * 2, demand=100_000)
    pricey_old.units = 100              # ten sam, ale ceny sprzed 2 dni → OPTIMAL woli świeży
    assert T.rank_trades([[pricey_old], [bulk_fresh]], "total", "optimal")[0] is bulk_fresh
    assert T.rank_trades([[pricey_old], [bulk_fresh]], "total", "risky")[0] is pricey_old


def test_low_security_lowers_score_in_every_profile_and_can_be_avoided():
    from unittest import mock
    from edtrade.filters import MarketFilter
    safe_sys, low_sys = _t(10_000, 1), _t(11_000, 1)
    safe_sys.security, low_sys.security = "High", "Anarchy"
    try:
        T.set_security_prefs(1.0, False)
        for profile in ("safe", "optimal", "risky", "auto"):
            assert T.rank_trades([[safe_sys], [low_sys]], "per_hour", profile)[0] is safe_sys, profile
        T.set_security_prefs(0.0, False)  # waga 0 — bezpieczeństwo ignorowane
        assert T.rank_trades([[safe_sys], [low_sys]], "per_hour", "optimal")[0] is low_sys
        T.set_security_prefs(0.0, True)   # przełącznik: omijaj Low/Anarchy
        buyers = [T.MineralBuyer("A", "Anarchy Sys", 60000, 5000, "large", 10, 100),
                  T.MineralBuyer("B", "High Sys", 50000, 5000, "large", 10, 100)]
        with mock.patch.object(T, "find_mineral_buyers", return_value=buyers):
            got = T.candidate_trades("gold", "Sol", 100, 1000, MarketFilter(),
                                     security={"anarchy sys": "Anarchy", "high sys": "High"})
        assert [t.sell_station for t in got] == ["B"]
    finally:
        T.set_security_prefs(0.5, False)


def test_auto_picks_profile_per_trade():
    fresh = _t(5_000, 1)
    stale_pricey = _t(15_000, 24 * 5)
    lowsec = _t(5_000, 1)
    lowsec.security = "Low"
    assert T.auto_profile(fresh) == "optimal"
    assert T.auto_profile(stale_pricey) == "risky"
    assert T.auto_profile(lowsec) == "safe"
