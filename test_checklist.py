"""Testy checklisty trasy — trasa i format eventów z prawdziwych danych (Spansh Sol/Columbus, journal usera)."""

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from edtrade.checklist import RouteChecklist, parse_commodity_names
from edtrade.trade import Hop, TradeRoute

NAMES = parse_commodity_names(
    "id,symbol,category,name\n1,Silver,Metals,Silver\n2,Gold,Metals,Gold\n3,Tritium,Chemicals,Tritium\n"
    "4,Opal,Minerals,Void Opal\n5,Biowaste,Waste,Biowaste\n"
)
T0 = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def ts(minutes: int) -> str:
    return (T0 + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def route_sol_columbus() -> TradeRoute:
    hops = [
        Hop("Sol", "Columbus", "61 Cygni", "Broglie Terminal", "Silver", 304, 34895, 48100),
        Hop("61 Cygni", "Broglie Terminal", "Ross 104", "Shiner Port", "Gold", 304, 47645, 61182),
        Hop("Ross 104", "Shiner Port", "WISE 1647+5632", "Perrin Enterprise", "Tritium", 304, 49617, 61889),
    ]
    return TradeRoute(hops=3, hops_list=hops)


def buy(t, typ, n):
    return {"timestamp": ts(t), "event": "MarketBuy", "MarketID": 1, "Type": typ, "Count": n, "BuyPrice": 1, "TotalCost": n}


def sell(t, typ, n):
    return {"timestamp": ts(t), "event": "MarketSell", "MarketID": 2, "Type": typ, "Count": n, "SellPrice": 2, "TotalSale": 2 * n}


def dock(t, system, station):
    return {"timestamp": ts(t), "event": "Docked", "StarSystem": system, "StationName": station}


class TestChecklist(unittest.TestCase):
    def new(self, cargo=None):
        return RouteChecklist(route_sol_columbus(), NAMES, cargo=cargo, docked=("Sol", "Columbus"), created_at=T0)

    def test_full_route(self):
        c = self.new()
        self.assertEqual(c.status_text(), "[▶ kup 304 · ○ leć · ○ sprzedaj]")
        self.assertTrue(c.on_event(buy(1, "silver", 304)))
        self.assertEqual(c.status_text(), "[✓ kup 304/304 · ▶ leć · ○ sprzedaj]")
        self.assertTrue(c.follows_plan("61 Cygni", "broglie terminal"))
        self.assertTrue(c.on_event(dock(10, "61 Cygni", "Broglie Terminal")))
        self.assertTrue(c.on_event(sell(11, "silver", 304)))
        self.assertEqual((c.hop_index, c.route._current_hop), (1, 2))
        c.on_event(buy(12, "gold", 304)); c.on_event(dock(20, "Ross 104", "Shiner Port")); c.on_event(sell(21, "gold", 304))
        c.on_event(buy(22, "tritium", 304)); c.on_event(dock(30, "WISE 1647+5632", "Perrin Enterprise"))
        self.assertTrue(c.on_event(sell(31, "tritium", 304)))
        self.assertTrue(c.finished)
        self.assertEqual(c.route._checklist_text, "[✓ trasa ukończona]")
        self.assertFalse(c.on_event(buy(40, "gold", 1)))

    def test_partial_buy_and_split_sale(self):
        c = self.new()
        c.on_event(buy(1, "silver", 200))
        self.assertIn("◐ kup 200/304", c.status_text())
        c.on_event(dock(10, "61 Cygni", "Broglie Terminal"))
        c.on_event(sell(11, "silver", 100))
        self.assertEqual(c.hop_index, 0)
        self.assertIn("◐ sprzedaj 100/200", c.status_text())
        c.on_event(sell(12, "silver", 100))
        self.assertEqual(c.hop_index, 1)

    def test_sale_elsewhere_and_other_commodity_ignored(self):
        c = self.new()
        c.on_event(buy(1, "silver", 304))
        self.assertFalse(c.on_event(sell(2, "silver", 304)))           # wciąż w Sol, nie w celu
        self.assertFalse(c.on_event(buy(3, "biowaste", 10)))           # inny towar
        c.on_event(dock(10, "Barnard's Star", "Miller Depot"))          # zły port
        self.assertFalse(c.arrived)
        self.assertFalse(c.follows_plan("Barnard's Star", "Miller Depot"))

    def test_history_before_route_ignored_and_cargo_counts(self):
        c = self.new(cargo=[{"Name": "silver", "Count": 304}, {"Name": "drones", "Count": 10}])
        self.assertEqual(c.bought, 304)                                  # kupione zanim Spansh policzył trasę
        self.assertFalse(c.on_event(buy(-5, "silver", 304)))             # catch-up historii
        self.assertEqual(c.bought, 304)

    def test_symbol_differs_from_display_name(self):
        route = TradeRoute(hops=1, hops_list=[Hop("A", "a", "B", "b", "Void Opal", 10, 1, 2)])
        c = RouteChecklist(route, NAMES, docked=("A", "a"), created_at=T0)
        self.assertTrue(c.on_event(buy(1, "opal", 10)))                  # journal: Opal ↔ Spansh: Void Opal

    def test_real_journal_event_format(self):
        samples = [json.loads(l) for l in (Path(__file__).parent / "test_data" / "journal_samples.jsonl").read_text().splitlines()]
        mb, ms = (next(e for e in samples if e["event"] == n) for n in ("MarketBuy", "MarketSell"))
        route = TradeRoute(hops=1, hops_list=[Hop("X", "x", "Y", "y", "Biowaste", 246, 54, 32)])
        c = RouteChecklist(route, NAMES, docked=("X", "x"), created_at=datetime(2026, 10, 12, tzinfo=timezone.utc))
        self.assertTrue(c.on_event(mb))
        c.on_event({"timestamp": "2026-10-12T20:00:00Z", "event": "Docked", "StarSystem": "Y", "StationName": "y"})
        self.assertTrue(c.on_event(ms))
        self.assertTrue(c.finished)

    def test_event_in_same_second_as_route_creation(self):
        created = T0 + timedelta(milliseconds=600)
        c = RouteChecklist(route_sol_columbus(), NAMES, docked=("Sol", "Columbus"), created_at=created)
        self.assertTrue(c.on_event(buy(0, "silver", 304)))               # journal: 12:00:00, trasa: 12:00:00.6

    def test_empty_route(self):
        c = RouteChecklist(TradeRoute(), NAMES, created_at=T0)
        self.assertTrue(c.finished)
        self.assertFalse(c.follows_plan("Sol", "Columbus"))


if __name__ == "__main__":
    unittest.main()
