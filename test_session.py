"""Podsumowanie sesji z prawdziwych próbek MarketBuy/MarketSell usera."""

import json
from datetime import datetime, timezone
from pathlib import Path

from edtrade.session import SessionLedger

SAMPLES = [json.loads(l) for l in Path(__file__).with_name("test_data").joinpath("journal_samples.jsonl")
           .read_text().splitlines() if l.strip()]


def _trades():
    return [e for e in SAMPLES if e.get("event") in ("MarketBuy", "MarketSell")]


def test_sell_profit_from_avg_price_paid():
    ledger = SessionLedger()
    for ev in _trades():
        ledger.on_event(ev)
    s = ledger.summary()
    sell = [t for t in s.trades if t.kind == "sell" and t.commodity == "biowaste"][-1]
    assert sell.profit == 7872 - 54 * 246  # strata 5412
    assert s.spent > 0 and s.revenue > 0


def test_loadgame_resets_and_sets_start():
    ledger = SessionLedger()
    for ev in _trades():
        ledger.on_event(ev)
    ledger.on_event({"timestamp": "2026-10-13T10:00:00Z", "event": "LoadGame"})
    s = ledger.summary()
    assert s.trades == [] and s.started_at == datetime(2026, 10, 13, 10, tzinfo=timezone.utc)


def test_profit_per_hour_and_station():
    ledger = SessionLedger()
    ledger.on_event({"timestamp": "2026-10-13T10:00:00Z", "event": "LoadGame"})
    ledger.on_event({"timestamp": "2026-10-13T10:30:00Z", "event": "Docked", "StarSystem": "Sol",
                     "StationName": "Abraham Lincoln"})
    ledger.on_event({"timestamp": "2026-10-13T10:31:00Z", "event": "MarketSell", "Type": "gold", "Count": 100,
                     "SellPrice": 50000, "TotalSale": 5_000_000, "AvgPricePaid": 40000})
    s = ledger.summary()
    assert s.profit == 1_000_000 and s.trades[0].station == "Abraham Lincoln"
    assert s.profit_per_hour(datetime(2026, 10, 13, 12, tzinfo=timezone.utc)) == 500_000
    assert s.profit_per_hour(datetime(2026, 10, 13, 10, 1, tzinfo=timezone.utc)) == 0  # za krótko


def test_mined_goods_full_sale_is_profit():
    ledger = SessionLedger()
    ledger.on_event({"timestamp": "2026-10-13T10:31:00Z", "event": "MarketSell", "Type": "painite", "Count": 10,
                     "SellPrice": 300000, "TotalSale": 3_000_000, "AvgPricePaid": 0})
    assert ledger.summary().profit == 3_000_000
