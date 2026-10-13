"""EDDN: parser, lokalna baza cen, nasłuch (lokalny nadajnik ZeroMQ udający relay) i użycie świeższych cen."""

import json
import time
import zlib
from datetime import datetime, timezone, timedelta
from unittest import mock

import pytest

from edtrade import eddn, trade, verify
from edtrade.filters import MarketFilter
from edtrade.price_db import PriceDB


def iso(hours_ago=0.0):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def message(sell=60000, demand=5000, hours_ago=0.0, station="Nobleport", commodities=None):
    return {"systemName": "Luyten 674-15", "stationName": station, "marketId": 42, "timestamp": iso(hours_ago),
            "commodities": commodities if commodities is not None else [
                {"name": "Gold", "buyPrice": 0, "sellPrice": sell, "stock": 0, "demand": demand, "meanPrice": 47000,
                 "stockBracket": 0, "demandBracket": 3}]}


def raw(msg, schema="https://eddn.edcd.io/schemas/commodity/3"):
    return zlib.compress(json.dumps({"$schemaRef": schema, "header": {}, "message": msg}).encode())


def test_parse_filters_schema():
    assert eddn.parse(raw(message()))["stationName"] == "Nobleport"
    assert eddn.parse(raw(message(), "https://eddn.edcd.io/schemas/commodity/3/test")) is None
    assert eddn.parse(raw(message(), "https://eddn.edcd.io/schemas/journal/1")) is None
    assert eddn.parse(b"not zlib") is None


def test_db_keeps_newest_and_history_only_on_change(tmp_path):
    db = PriceDB(tmp_path / "p.db")
    assert db.upsert_market(message(sell=60000, hours_ago=2)) == 1
    assert db.upsert_market(message(sell=55000, hours_ago=3)) == 0      # starszy — pomijany
    assert db.upsert_market(message(sell=60000, hours_ago=1)) == 1      # ta sama cena — bez historii
    assert db.upsert_market(message(sell=58000, hours_ago=0)) == 1
    assert db.get("luyten 674-15", "NOBLEPORT", "gold").sell_price == 58000
    assert [h[2] for h in db.history(42, "gold")] == [60000, 58000]


def _buyer(hours_ago):
    return trade.MineralBuyer(station_name="Nobleport", system_name="Luyten 674-15", sell_price=66466, demand=400,
                              distance=19.0, distance_to_arrival=82, pad_size="large",
                              updated_at=iso(hours_ago))


def test_candidates_use_fresher_eddn_price(tmp_path):
    db = PriceDB(tmp_path / "p.db")
    db.upsert_market(message(sell=60000, demand=5000, hours_ago=0.1))
    with mock.patch.object(trade, "PRICE_DB", db), \
            mock.patch.object(trade, "find_mineral_buyers", return_value=[_buyer(hours_ago=20)]):
        t = trade.candidate_trades("gold", "Sol", 304, 45000, MarketFilter())[0]
    assert t.sell_price == 60000 and t.demand == 5000 and t.age_hours < 1
    with mock.patch.object(trade, "PRICE_DB", db), \
            mock.patch.object(trade, "find_mineral_buyers", return_value=[_buyer(hours_ago=0)]):
        assert trade.candidate_trades("gold", "Sol", 304, 45000, MarketFilter())[0].sell_price == 66466  # API świeższe


def test_buyer_dropped_when_eddn_says_no_demand(tmp_path):
    db = PriceDB(tmp_path / "p.db")
    db.upsert_market(message(sell=60000, demand=0))
    with mock.patch.object(trade, "PRICE_DB", db), \
            mock.patch.object(trade, "find_mineral_buyers", return_value=[_buyer(hours_ago=20)]):
        assert trade.candidate_trades("gold", "Sol", 304, 45000, MarketFilter()) == []


def test_route_hop_refreshed(tmp_path):
    db = PriceDB(tmp_path / "p.db")
    db.upsert_market(message(sell=60000))
    hop = trade.Hop("Sol", "Columbus", "Luyten 674-15", "Nobleport", "Gold", 100, 45000, 66466,
                    (66466 - 45000) * 100, 19, time.time() - 3600, time.time() - 30 * 3600)
    route = trade.TradeRoute(total_profit=hop.profit, hops=1, hops_list=[hop])
    assert verify.refresh_route_from_db(route, db, {"gold": "gold"}) == 1
    assert hop.sell_price == 60000 and route.total_profit == 15000 * 100


def test_listener_receives_from_local_relay(tmp_path):
    zmq = pytest.importorskip("zmq")
    pub = zmq.Context.instance().socket(zmq.PUB)
    port = pub.bind_to_random_port("tcp://127.0.0.1")
    db = PriceDB(tmp_path / "p.db")
    got = []
    listener = eddn.EDDNListener(db, url=f"tcp://127.0.0.1:{port}", on_market=got.append)
    assert listener.start()
    try:
        deadline = time.time() + 10
        while not got and time.time() < deadline:   # SUB łączy się asynchronicznie — nadawaj aż dotrze
            pub.send(raw(message(hours_ago=0)))
            time.sleep(0.2)
        assert got and db.get("Luyten 674-15", "Nobleport", "gold").sell_price == 60000
    finally:
        listener.stop()
        pub.close()
