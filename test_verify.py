"""Weryfikacja hopu cenami na żywo (Market.json) i tekst do schowka."""

from edtrade import verify
from edtrade.main import copy_text
from edtrade.trade import Hop, MarketItem, StationMarket

NAMES = {"silver": "Silver", "opal": "Void Opal"}


def hop(**kw):
    base = dict(source_system="Sol", source_station="Columbus", destination_system="61 Cygni",
                destination_station="Broglie Terminal", commodity="Silver", amount=304, buy_price=34895,
                sell_price=48100, profit=(48100 - 34895) * 304)
    base.update(kw)
    return Hop(**base)


def market(exports=(), imports=()):
    return StationMarket(system_name="Sol", station_name="Columbus", exports=list(exports), imports=list(imports))


def test_buy_confirmed_updates_hop():
    h = hop()
    c = verify.check_buy(h, market([MarketItem("silver", buy_price=34900, stock=5000)]), NAMES)
    assert c.level == verify.OK and h.buy_price == 34900 and h.src_updated_at > 0


def test_buy_gone_when_missing_or_unprofitable():
    assert verify.check_buy(hop(), market(), NAMES).level == verify.GONE
    c = verify.check_buy(hop(), market([MarketItem("silver", buy_price=50000, stock=5000)]), NAMES)
    assert c.level == verify.GONE and "NIEOPŁACALNY" in c.text


def test_buy_warns_on_price_and_stock():
    h = hop()
    c = verify.check_buy(h, market([MarketItem("silver", buy_price=40000, stock=120)]), NAMES)
    assert c.level == verify.WARN and "KUPNO +15%" in c.text and "ZAPAS 120 T" in c.text
    assert h.amount == 120 and h.profit == (48100 - 40000) * 120


def test_symbol_maps_to_display_name():
    c = verify.check_buy(hop(commodity="Void Opal", buy_price=100, sell_price=1000),
                         market([MarketItem("opal", buy_price=100, stock=50)]), NAMES)
    assert c.level != verify.GONE


def test_sell_check():
    h = hop()
    ok = verify.check_sell(h, market(imports=[MarketItem("silver", sell_price=48000, demand=900)]), NAMES)
    assert ok.level == verify.OK
    low = verify.check_sell(h, market(imports=[MarketItem("silver", sell_price=40000, demand=900)]), NAMES)
    assert low.level == verify.WARN and "SPRZEDAŻ -17%" in low.text and h.sell_price == 40000
    assert verify.check_sell(h, market(), NAMES).level == verify.WARN


def test_copy_text_modes():
    assert copy_text("HIP 12345", "Ackerman Market", "station") == "Ackerman Market"
    assert copy_text("HIP 12345", "Ackerman Market", "system") == "HIP 12345"
    assert copy_text("HIP 12345", "Ackerman Market", "both") == "Ackerman Market (HIP 12345)"
    assert copy_text("HIP 12345", "", "station") == "HIP 12345"
