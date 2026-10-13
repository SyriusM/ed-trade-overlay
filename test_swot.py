"""Testy analizy SWOT przed rekomendacją handlu."""

import unittest

from edtrade import swot
from edtrade.trade import HopCommodity, Hop, NearbyTrade, TradeEngine, TradeRoute

NOW = 1_800_000_000.0
H = 3600


def live(items, station="Abraham Lincoln", system="Sol", age_s=60):
    return swot.live_market_from_json({
        "timestamp": "2027-01-15T08:00:00Z", "StarSystem": system, "StationName": station, "MarketID": 1,
        "Items": [{"Name": f"${n.lower()}_name;", "Name_Localised": n, "BuyPrice": b, "SellPrice": 0,
                   "Stock": st, "Demand": 0} for n, b, st in items]}) if items is not None else None


def with_ts(market, ts):
    market.timestamp = ts
    return market


def hop(commodities, src_age_h=1, dst_age_h=1, distance=20.0):
    h = Hop(source_system="Sol", source_station="Abraham Lincoln", destination_system="LP 71-165",
            destination_station="Starbase Pratchett", distance=distance,
            source_updated_at=NOW - src_age_h * H, destination_updated_at=NOW - dst_age_h * H)
    h.commodities = [HopCommodity(name=n, amount=a, buy_price=b, sell_price=s, profit=a * (s - b), supply=sup, demand=dem)
                     for n, a, b, s, sup, dem in commodities]
    h.commodity, h.amount = h.commodities[0].name, sum(c.amount for c in h.commodities)
    return h


def route(*hops):
    r = TradeRoute(total_profit=sum(c.profit for h in hops for c in h.commodities))
    r.hops_list = list(hops)
    return r


class TestRouteSwot(unittest.TestCase):
    def test_gold_missing_on_live_market_is_rejected(self):
        r = route(hop([("Gold", 256, 9000, 50000, 5000, 9000)]))
        market = with_ts(live([("Silver", 4000, 500)]), NOW - 60)
        swot.apply_to_route(r, 256, market, now=NOW)
        self.assertIn("Gold", r.error)
        self.assertTrue(r.error.startswith("odrzucona"))

    def test_live_price_above_sell_price_is_rejected(self):
        r = route(hop([("Gold", 256, 9000, 10000, 5000, 9000)]))
        swot.apply_to_route(r, 256, with_ts(live([("Gold", 12000, 900)]), NOW - 60), now=NOW)
        self.assertIn("cena kupna", r.error)

    def test_low_live_stock_is_weakness_not_rejection(self):
        r = route(hop([("Gold", 256, 9000, 20000, 5000, 9000)]))
        swot.apply_to_route(r, 256, with_ts(live([("Gold", 9000, 1)]), NOW - 60), now=NOW)
        self.assertEqual(r.error, "")
        self.assertIn("podaż 1/256", r._swot.weaknesses)
        self.assertEqual(r._swot.profit, 11000)
        self.assertIn("podaż 1/256", r._swot.short())

    def test_minor_commodity_missing_keeps_route(self):
        r = route(hop([("Cobalt", 140, 1000, 5000, None, None), ("Silver", 1, 4000, 4500, None, None)]))
        swot.apply_to_route(r, 256, with_ts(live([("Cobalt", 1000, 500)]), NOW - 60), now=NOW)
        self.assertEqual(r.error, "")
        self.assertIn("brak Silver na rynku", r._swot.weaknesses)
        self.assertIn("mix 2 towarów", r._swot.opportunities)

    def test_old_market_json_is_not_live(self):
        r = route(hop([("Gold", 256, 9000, 50000, 5000, 9000)]))
        swot.apply_to_route(r, 256, with_ts(live([("Silver", 4000, 500)]), NOW - 5 * H), now=NOW)
        self.assertEqual(r.error, "")
        self.assertIn("brak danych live", r._swot.threats)

    def test_other_station_market_json_is_ignored(self):
        r = route(hop([("Gold", 256, 9000, 50000, 5000, 9000)]))
        swot.apply_to_route(r, 256, with_ts(live([], station="Daedalus"), NOW - 60), now=NOW)
        self.assertEqual(r.error, "")

    def test_stale_destination_data(self):
        r = route(hop([("Gold", 256, 9000, 50000, 5000, 9000)], dst_age_h=7))
        swot.apply_to_route(r, 256, None, now=NOW)
        self.assertIn("dane 7h", r._swot.threats)
        r = route(hop([("Gold", 256, 9000, 50000, 5000, 9000)], dst_age_h=100))
        swot.apply_to_route(r, 256, None, now=NOW)
        self.assertIn("za stare", r.error)

    def test_spansh_supply_and_demand(self):
        r = route(hop([("Gold", 256, 9000, 50000, 100, 50)]))
        swot.apply_to_route(r, 256, None, now=NOW)
        self.assertIn("podaż 100/256", r._swot.weaknesses)
        self.assertIn("popyt 50/100", r._swot.weaknesses)
        self.assertIn("ładownia 19%", r._swot.weaknesses)
        self.assertIn("wolne 206T", r._swot.opportunities)

    def test_full_load_shows_strengths(self):
        r = route(hop([("Gold", 256, 9000, 20000, 5000, 9000)]))
        swot.apply_to_route(r, 256, with_ts(live([("Gold", 9000, 5000)]), NOW - 60), now=NOW)
        self.assertEqual(r._swot.reasons(), ["zysk 2.8M", "11k/t"])

    def test_later_hop_rejected_rejects_route(self):
        bad = hop([("Gold", 256, 9000, 50000, 5000, 0)])
        r = route(hop([("Gold", 256, 9000, 50000, 5000, 9000)]), bad)
        swot.apply_to_route(r, 256, None, now=NOW)
        self.assertIn("brak popytu", r.error)

    def test_jumps_and_security(self):
        r = route(hop([("Gold", 256, 9000, 50000, 5000, 9000)], distance=45.0))
        swot.apply_to_route(r, 256, None, now=NOW, jump_range=20.0, security="$GAlAXY_MAP_INFO_state_anarchy;")
        self.assertIn("3 skoki", r._swot.threats)
        self.assertIn("anarchia", r._swot.threats)

    def test_errored_route_untouched(self):
        r = TradeRoute(error="Spansh polling timeout")
        swot.apply_to_route(r, 256, None, now=NOW)
        self.assertFalse(hasattr(r, "_swot"))


class TestSpanshParse(unittest.TestCase):
    def test_supply_demand_and_timestamps(self):
        data = {"result": [{
            "distance": 23.7, "total_profit": 165120, "cumulative_profit": 165120,
            "source": {"system": "Sol", "station": "Abraham Lincoln", "market_updated_at": 1791901229},
            "destination": {"system": "LP 71-165", "station": "Starbase Pratchett", "market_updated_at": 1791880780},
            "commodities": [{"amount": 256, "name": "Biowaste", "total_profit": 165120,
                             "source_commodity": {"buy_price": 109, "supply": 78658},
                             "destination_commodity": {"sell_price": 754, "demand": 3756}}]}]}
        r = TradeEngine()._parse_spansh_result(data, "Sol", "Abraham Lincoln")
        h = r.hops_list[0]
        self.assertEqual((h.commodities[0].supply, h.commodities[0].demand), (78658, 3756))
        self.assertEqual((h.source_updated_at, h.destination_updated_at), (1791901229, 1791880780))


class TestNearbySwot(unittest.TestCase):
    def trade(self, commodity="Gold", stock=500, demand=5000, station="Starbase Pratchett", age_h=1):
        from datetime import datetime, timezone
        ts = datetime.fromtimestamp(NOW - age_h * H, timezone.utc).isoformat()
        return NearbyTrade(commodity=commodity, buy_price=9000, stock=stock, units=min(256, stock),
                           sell_station=station, sell_system="LP 71-165", sell_price=20000, demand=demand,
                           updated_at=ts)

    def test_live_market_drops_missing_commodity(self):
        market = with_ts(live([("Silver", 4000, 500)]), NOW - 60)
        kept, _ = swot.screen_trades([self.trade()], 256, market, ("Sol", "Abraham Lincoln"), now=NOW)
        self.assertEqual(kept, [])

    def test_db_stock_zero_dropped_and_low_stock_noted(self):
        kept, swots = swot.screen_trades([self.trade(stock=0), self.trade("Silver", stock=12)], 256, now=NOW)
        self.assertEqual([t.commodity for t in kept], ["Silver"])
        self.assertIn("podaż 12/256", swots[id(kept[0])].weaknesses)
        self.assertIn("brak danych live", swots[id(kept[0])].threats)

    def test_stale_buyer_dropped(self):
        kept, _ = swot.screen_trades([self.trade(age_h=80)], 256, now=NOW)
        self.assertEqual(kept, [])

    def test_partners_at_same_station_are_an_opportunity(self):
        kept, swots = swot.screen_trades([self.trade(stock=100), self.trade("Silver", stock=100)], 256, now=NOW)
        self.assertIn("+ Silver", swots[id(kept[0])].opportunities)


if __name__ == "__main__":
    unittest.main()
