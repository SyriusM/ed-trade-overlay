"""Testy parsera TradeEngine."""

import sys
import unittest

# Dodaj katalog wyżej do sys.path
sys.path.insert(0, "/home/syriusm/Projekty/ed-trade-overlay")

from edtrade.trade import TradeEngine, StationInfo, TradeRoute


class TestTradeRoute(unittest.TestCase):
    def test_profit_per_ton(self):
        route = TradeRoute(cargo_used=10, total_profit=50000)
        self.assertAlmostEqual(route.profit_per_ton, 5000.0)

    def test_profit_per_ton_zero_cargo(self):
        route = TradeRoute(cargo_used = 0, total_profit=0)
        self.assertEqual(route.profit_per_ton,0.0)

    def test_summary_no_error(self):
        route = TradeRoute(
            destination_system="Wolf 359",
            destination_station="Bountiful Landing",
            buy_item="Exhaust Component",
            buy_quantity=120,
            buy_price=130,
            sell_price=195,
            total_profit=7800,
            cargo_used=120,
            jumps=1,
            hops=1,
        )
        s = route.summary()
        self.assertIn("Wolf 359", s)
        self.assertIn("Exhaust Component", s)
        self.assertIn("7,800cr", s)

    def test_summary_with_error(self):
        route = TradeRoute(error="database is locked")
        self.assertIn("database is locked", route.summary())


class TestParseOutput(unittest.TestCase):
    """Test parsowania surowego outputu z trade run."""

    def setUp(self):
        self.engine = TradeEngine()

    def test_parse_basic_route(self):
        output = """
=== Route from Alpha Centauri/KNW-03H ===
Buy Exhaust Component x120 at KNW-03H (130cr)
Fly to Wolf 359 (1 jumps, 3.9 ly)
Sell Exhaust Component x120 at Bountiful Landing (195cr), profit 7,800cr
=== Summary ===
Total profit: 7,800cr
"""
        route = self.engine._parse_output(output, "Alpha Centauri", "KNW-03H")
        self.assertEqual(route.buy_item, "Exhaust Component")
        self.assertEqual(route.buy_quantity, 120)
        self.assertEqual(route.buy_price, 130)
        self.assertEqual(route.sell_price, 195)
        self.assertEqual(route.total_profit, 7800)
        self.assertEqual(route.cargo_used, 120)
        self.assertEqual(route.jumps, 1)
        self.assertEqual(route.destination_system, "Wolf 359")

    def test_parse_multi_hop_route(self):
        output = """
=== Route from Sol/Argo ===
Buy Data Core x50 at Argo (250cr)
Fly to LHS 3034 (2 jumps, 12.4 ly)
Sell Data Core x50 at LHS 3034 Station (420cr), profit 8,500cr
Fly to Epsilon Eridani (3 jumps, 20.1 ly)
Buy Food Ration x200 at Epsilon Eridani Station (15cr)
Fly to Sol (2 jumps, 4.5 ly)
Sell Food Ration x200 at Sol Station (35cr), profit 4,000cr
=== Summary ===
Total profit: 12,500cr
"""
        route = self.engine._parse_output(output, "Sol", "Argo")
        # Parser bierze ostatni buy/sell — to jest MVP, wielohop to future
        self.assertIn(route.buy_item, ["Data Core", "Food Ration"])
        self.assertGreater(route.total_profit, 0)

    def test_parse_empty_output(self):
        route = self.engine._parse_output("", "Sol", "Test")
        self.assertEqual(route.buy_item, "")
        self.assertEqual(route.total_profit, 0)

    def test_parse_no_profit(self):
        output = """
=== Route from Sol/Test ===
Buy Tritium x10 at Test Station (10cr)
Fly to Sol (1 jumps, 0.0 ly)
Sell Tritium x10 at Sol Station (8cr), profit -20cr
"""
        route = self.engine._parse_output(output, "Sol", "Test")
        self.assertEqual(route.total_profit, -20)


class TestStationInfo(unittest.TestCase):
    def test_defaults(self):
        s = StationInfo()
        self.assertEqual(s.name, "")
        self.assertIsNone(s.pad_size)
        self.assertEqual(s.distance_to_arrival, 0.0)
        self.assertEqual(s.services, {})

    def test_from_dict(self):
        s = StationInfo(
            name="Abraham Lincoln",
            system_name="Sol",
            body_name="Earth",
            distance_to_arrival=504.6,
            pad_size="large",
            station_type="Orbis",
            allegiance="Federation",
            government="Democracy",
            primary_economy="Service",
            services={"shipyard": True, "outfitting": True, "refuel": False},
        )
        self.assertEqual(s.name, "Abraham Lincoln")
        self.assertEqual(s.pad_size, "large")
        self.assertEqual(s.distance_to_arrival, 504.6)
        self.assertTrue(s.services["shipyard"])
        self.assertFalse(s.services["refuel"])


class TestSearchStations(unittest.TestCase):
    """Test realnego wywołania Ardent API."""

    def test_search_sol(self):
        from edtrade.trade import search_stations
        stations = search_stations("Sol")
        self.assertIsInstance(stations, list)
        self.assertGreater(len(stations), 0, "Ardent zwrócił pustą listę dla Sol")
        # Sprawdzam pola pierwszej stacji
        s = stations[0]
        self.assertIsInstance(s, StationInfo)
        self.assertTrue(s.name)
        self.assertTrue(s.system_name)
        # Pad size: 1=small, 2=medium, 3=large
        self.assertIn(s.pad_size, [None, "small", "medium", "large"])
        # Usługi — słownik
        self.assertIsInstance(s.services, dict)
        self.assertGreater(len(s.services), 0, "Oczekiwano przynajmniej jednej usługi")

    def test_search_unknown_system(self):
        from edtrade.trade import search_stations
        # System który może nie istnieć — API zwraca pustą listę
        stations = search_stations("XYZNONEXISTENT123")
        self.assertIsInstance(stations, list)


if __name__ == "__main__":
    unittest.main()


class TestStationMarket(unittest.TestCase):
    """Filtrowanie rynku stacji — bez sieci (requests.get podmienione)."""

    def _run(self, rows, status=200, station="Abraham Lincoln"):
        from unittest import mock
        from edtrade import trade
        resp = mock.Mock(status_code=status, json=mock.Mock(return_value=rows), raise_for_status=mock.Mock())
        with mock.patch.object(trade.requests, "get", return_value=resp):
            return trade.get_station_market("Sol", station)

    def test_filters_and_sorts(self):
        def row(name, station="Abraham Lincoln", **kw):
            base = {"commodityName": name, "stationName": station, "buyPrice": 0, "sellPrice": 0,
                    "stock": 0, "demand": 0, "meanPrice": 100, "updatedAt": "2026-10-13T10:00:00.000Z"}
            return {**base, **kw}
        rows = [
            row("cheap", buyPrice=50, stock=10),
            row("pricey", buyPrice=150, stock=10),
            row("nodemand", sellPrice=999),
            row("good", sellPrice=300, demand=5),
            row("better", sellPrice=400, demand=5, updatedAt="2026-10-13T11:00:00.000Z"),
            row("other", station="Daedalus", sellPrice=5000, demand=5),
        ]
        m = self._run(rows, station="abraham lincoln")
        self.assertEqual(m.error, "")
        self.assertEqual(m.station_name, "Abraham Lincoln")
        self.assertEqual([i.name for i in m.exports], ["cheap", "pricey"])
        self.assertEqual([i.name for i in m.imports], ["better", "good"])
        self.assertEqual(m.updated_at, "2026-10-13T11:00:00.000Z")

    def test_unknown_station_and_system(self):
        self.assertIn("Brak danych", self._run([], station="X").error)
        self.assertIn("nie znaleziony", self._run({}, status=404).error)


class TestLargePad(unittest.TestCase):
    """Anaconda (pad L) nie może dostać trasy przez outposty z padami S/M."""

    def _payload(self, requires_large_pad: bool) -> dict:
        from unittest import mock
        from edtrade import trade
        engine = trade.TradeEngine()
        engine.requires_large_pad = requires_large_pad
        resp = mock.Mock(json=mock.Mock(return_value={}), raise_for_status=mock.Mock())
        with mock.patch.object(trade.requests, "post", return_value=resp) as post:
            engine.calculate_route_via_spansh("NN 3009", "Plucker Camp")
        return post.call_args.kwargs["data"]

    def test_payload(self):
        self.assertEqual(self._payload(True).get("requires_large_pad"), "1")
        self.assertNotIn("requires_large_pad", self._payload(False))

    def test_ship_sizes(self):
        from edtrade.trade import ship_needs_large_pad
        for ship in ("Anaconda", "anaconda", "type9", "cutter", "federation_corvette", "type7"):
            self.assertTrue(ship_needs_large_pad(ship), ship)
        for ship in ("python", "krait_mkii", "type6", "asp", "", None):
            self.assertFalse(ship_needs_large_pad(ship), ship)


def _spansh_segment(src, dst, comms, cumulative):
    return {"source": {"system": src, "station": src}, "destination": {"system": dst, "station": dst},
            "distance": 10.0, "total_profit": sum(c[4] for c in comms), "cumulative_profit": cumulative,
            "commodities": [{"name": n, "amount": a, "total_profit": p,
                             "source_commodity": {"buy_price": b}, "destination_commodity": {"sell_price": s}}
                            for n, a, b, s, p in comms]}


class TestFullHold(unittest.TestCase):
    """Spansh dopełnia ładownię kilkoma towarami — liczy się cały ładunek, nie pierwszy towar z listy."""

    def test_hop_counts_whole_load(self):
        from edtrade.trade import TradeEngine
        # Wynik Spansh Ham Dock → Rota Obscura (400 t ładowni): 1 t srebra to tylko dopełnienie
        data = {"result": [_spansh_segment("Ham Dock", "Rota Obscura", [
            ("Silver", 1, 30363, 41188, 10825), ("Cobalt", 140, 845, 20108, 2696820),
            ("Polymers", 172, 47, 9332, 1597020), ("Biowaste", 1, 31, 85, 54)], 4304719)]}
        route = TradeEngine()._parse_spansh_result(data, "Ham Dock", "Ham Dock")
        hop = route.hops_list[0]
        self.assertEqual(hop.commodity, "Cobalt")
        self.assertEqual((hop.buy_price, hop.sell_price), (845, 20108))
        self.assertEqual(hop.amount, 314)
        self.assertEqual(hop.profit, 4304719)
        self.assertEqual(route.total_profit, 4304719)
        self.assertEqual(route.cargo_used, 314)
        self.assertEqual(route.buy_quantity, 140)
        self.assertEqual(hop.names, ["Cobalt", "Polymers", "Silver", "Biowaste"])
        self.assertEqual(hop.cargo_text(), "Cobalt ×140 + Polymers ×172 +2")

    def test_single_commodity_text(self):
        from edtrade.trade import Hop
        self.assertEqual(Hop(commodity="Gold", amount=400).cargo_text(), "Gold ×400")

    def test_capital_from_balance(self):
        from unittest import mock
        from edtrade import trade
        engine = trade.TradeEngine()
        self.assertEqual(engine.capital, trade.UNLIMITED_CAPITAL)  # saldo nieznane → limitem jest ładownia
        engine.credits = 59_538_834
        resp = mock.Mock(json=mock.Mock(return_value={}), raise_for_status=mock.Mock())
        with mock.patch.object(trade.requests, "post", return_value=resp) as post:
            engine.calculate_route_via_spansh("Apárctias", "Almadrava")
        self.assertEqual(post.call_args.kwargs["data"]["starting_capital"], 59_538_834)


class TestCreditsFromJournal(unittest.TestCase):
    def test_loadgame_and_trades(self):
        from edtrade.watcher import JournalWatcher
        from pathlib import Path
        w = JournalWatcher(journal_dir=Path("/nonexistent"))
        w._dispatch([{"event": "MarketBuy", "TotalCost": 5}])
        self.assertIsNone(w.credits)
        w._dispatch([{"event": "LoadGame", "Credits": 1_000_000},
                     {"event": "MarketBuy", "TotalCost": 300_000},
                     {"event": "MarketSell", "TotalSale": 450_000}])
        self.assertEqual(w.credits, 1_150_000)
