"""Filtry rynków, ranking CR/H i ładunek z journala — bez sieci."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from edtrade import trade
from edtrade.filters import MarketFilter, filter_from_config
from edtrade.trade import MineralBuyer, travel_seconds


class TestFilters(unittest.TestCase):
    def test_from_config(self):
        self.assertEqual(filter_from_config({}, ship_large_pad=True).min_pad, "large")
        self.assertEqual(filter_from_config({}, ship_large_pad=False).min_pad, "medium")
        self.assertEqual(filter_from_config({"pad_filter": "large"}, False).min_pad, "large")
        self.assertEqual(filter_from_config({"pad_filter": "all"}, True).min_pad, "small")
        self.assertEqual(filter_from_config({"max_star_distance_ls": "abc"}, False).max_star_ls, 5000.0)

    def test_accepts(self):
        f = MarketFilter(min_pad="large", max_star_ls=5000, market_type="space")
        self.assertTrue(f.accepts("large", 100, "Coriolis"))
        self.assertFalse(f.accepts("medium", 100, "Outpost"))            # Plucker Camp
        self.assertFalse(f.accepts("large", 6000, "Coriolis"))
        self.assertFalse(f.accepts("large", 100, "CraterPort"))
        self.assertTrue(f.accepts(None, 100, None))                       # brak danych nie odrzuca
        self.assertTrue(MarketFilter(max_star_ls=0).star_ok(1_000_000))  # 0 = bez limitu


class TestRanking(unittest.TestCase):
    def test_travel_time(self):
        self.assertLess(travel_seconds(25, 3, 31.2), travel_seconds(15, 1216, 31.2))
        self.assertEqual(travel_seconds(0, 0), trade.supercruise_seconds(0) + trade.DOCKING_SECONDS)

    def _buyers(self):
        # Ten sam towar: Lamont płaci 4 cr więcej, ale ma 1216 ls supercruise (dane z gry, 246 t NLW)
        return [MineralBuyer("Lamont City", "Col 285", 6887, 2766, "large", 15.0, 1216, "", "Coriolis"),
                MineralBuyer("Rockwell Prospect", "Arcadian", 89837, 2762, "large", 25.0, 3, "", "AsteroidBase"),
                MineralBuyer("Plucker Camp", "NN 3009", 9999, 9000, "medium", 1.0, 13, "", "Outpost")]

    def test_best_buyer_by_profit_per_hour_and_pad(self):
        with mock.patch.object(trade, "find_mineral_buyers", return_value=self._buyers()):
            best = trade.best_buyer("nonlethalweapons", "NN 3009", 246, 0, MarketFilter(min_pad="large"), jump_range=31.2)
        self.assertEqual(best.sell_station, "Rockwell Prospect")
        self.assertEqual(best.units, 246)

    def test_units_limited_by_demand(self):
        buyers = [MineralBuyer("Small", "X", 50, 1000, "large", 5.0, 10, "", "Coriolis")]
        with mock.patch.object(trade, "find_mineral_buyers", return_value=buyers):
            best = trade.best_buyer("gold", "X", 304, 500, MarketFilter(min_pad="large"))
        self.assertEqual((best.units, best.total_profit), (50, 25000))

    def test_cargo_skips_limpets_and_mission_cargo(self):
        seen = []
        with mock.patch.object(trade, "_ardent_commodity_names", return_value=[]), \
                mock.patch.object(trade, "candidate_trades", side_effect=lambda name, *a, **k: seen.append(name) or []):
            trade.best_sales_for_cargo([{"Name": "drones", "Count": 10}, {"Name": "gold", "Count": 5, "MissionID": 1},
                                        {"Name": "nonlethalweapons", "Count": 246}], "NN 3009", MarketFilter())
        self.assertEqual(seen, ["nonlethalweapons"])


class TestRankModes(unittest.TestCase):
    """Każdy tryb wybiera innego kupca tego samego towaru (304 t, zakup po 1000 cr, zasięg 30 ly)."""

    def setUp(self):
        self.buyers = [
            MineralBuyer("Daleko Drogo", "A", 5000, 3000, "large", 90.0, 5000, "", "Coriolis"),  # max zysk, długi lot
            MineralBuyer("Szybko", "B", 5000, 2600, "large", 20.0, 10, "", "Coriolis"),         # najlepsze cr/h
            MineralBuyer("Za Rogiem", "C", 5000, 1100, "large", 0.0, 50, "", "Coriolis"),       # najkrótszy lot
        ]

    def _pick(self, mode):
        with mock.patch.object(trade, "find_mineral_buyers", return_value=self.buyers):
            return trade.best_buyer("gold", "C", 304, 1000, MarketFilter(min_pad="large", min_profit_per_t=0),
                                    mode=mode).sell_station

    def test_modes(self):
        self.assertEqual(self._pick("total"), "Daleko Drogo")
        self.assertEqual(self._pick("per_hour"), "Szybko")
        self.assertEqual(self._pick("time"), "Za Rogiem")

    def test_min_profit_per_t(self):
        with mock.patch.object(trade, "find_mineral_buyers", return_value=self.buyers):
            names = [t.sell_station for t in trade.candidate_trades("gold", "C", 304, 1000, MarketFilter())]
            cargo = [t.sell_station for t in trade.candidate_trades("gold", "C", 304, 0, MarketFilter())]
        self.assertNotIn("Za Rogiem", names)        # +100 cr/t < 500 cr/t (domyślny próg)
        self.assertIn("Za Rogiem", cargo)           # ładunek już w ładowni — każda sprzedaż się liczy

    def test_rank_trades_one_row_per_commodity(self):
        with mock.patch.object(trade, "find_mineral_buyers", return_value=self.buyers):
            cands = [trade.candidate_trades("gold", "C", 304, 1000, MarketFilter(min_profit_per_t=0)),
                     trade.candidate_trades("silver", "C", 10, 2900, MarketFilter(min_profit_per_t=0))]
        ranked = trade.rank_trades(cands, "total")
        self.assertEqual([t.commodity for t in ranked], ["gold", "silver"])


class TestCargoEvent(unittest.TestCase):
    def test_cargo_without_inventory_reads_cargo_json(self):
        import json, tempfile
        from edtrade.watcher import JournalWatcher
        with tempfile.TemporaryDirectory() as d:
            Path(d, "Cargo.json").write_text(json.dumps({"Inventory": [{"Name": "gold", "Count": 7}]}))
            got = []
            w = JournalWatcher(journal_dir=Path(d), on_cargo=got.append)
            w._dispatch([{"event": "Cargo", "Vessel": "Ship", "Count": 7}, {"event": "Cargo", "Vessel": "SRV", "Count": 2}])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["Inventory"], [{"Name": "gold", "Count": 7}])


if __name__ == "__main__":
    unittest.main()
