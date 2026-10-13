"""Kalibracja tempa z realnych kursów i jej wpływ na czas w rankingach."""

from datetime import datetime, timezone, timedelta

from edtrade import trade as T
from edtrade.checklist import RouteChecklist
from edtrade.pilot import PilotCalibration


def test_factor_needs_min_samples_and_uses_median(tmp_path):
    p = PilotCalibration(tmp_path / "pilot.json")
    assert p.add(300, 200) and p.add(400, 200)
    assert p.factor == 1.0  # za mało kursów
    assert p.add(260, 200)
    assert p.factor == 1.5  # mediana 1.3 / 1.5 / 2.0
    assert not p.add(5000, 200)  # przerwa / objazd — odrzucony
    assert PilotCalibration(tmp_path / "pilot.json").factor == 1.5  # zapisane na dysku


def test_travel_seconds_scaled_by_factor():
    base = T.travel_seconds(60, 1000, 30, calibrated=False)
    try:
        T.set_pilot_factor(1.5)
        assert T.travel_seconds(60, 1000, 30) == base * 1.5
    finally:
        T.set_pilot_factor(1.0)


def test_checklist_reports_trip_once():
    route = T.TradeRoute(hops=1, hops_list=[T.Hop("Sol", "Columbus", "61 Cygni", "Broglie Terminal", "Silver", 10, 1, 2)])
    start = datetime(2026, 10, 13, 10, tzinfo=timezone.utc)
    c = RouteChecklist(route, {"silver": "Silver"}, docked=("Sol", "Columbus"), created_at=start)
    iso = lambda m: (start + timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")
    c.on_event({"timestamp": iso(1), "event": "MarketBuy", "Type": "silver", "Count": 10})
    c.on_event({"timestamp": iso(6), "event": "Docked", "StarSystem": "61 Cygni", "StationName": "Broglie Terminal"})
    hop, bought, docked = c.pop_trip()
    assert (docked - bought).total_seconds() == 300 and hop.destination_system == "61 Cygni"
    assert c.pop_trip() is None
