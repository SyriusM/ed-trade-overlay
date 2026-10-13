"""Weryfikacja trasy cenami na żywo z gry (Market.json) — zanim kupisz / sprzedasz.

Trasa liczona jest z danych Spansh/Ardent (sprzed minut–dni). Gra zapisuje Market.json, gdy otworzysz
ekran rynku na stacji — wtedy porównujemy bieżący hop z rzeczywistością i poprawiamy go ceną z gry.
"""

import time
from dataclasses import dataclass
from typing import Optional

from .trade import Hop, StationMarket, MarketItem

OK, WARN, GONE = "ok", "warn", "gone"
BUY, SELL = "buy", "sell"

PRICE_TOLERANCE = 0.05   # zmiana ceny poniżej 5% — bez ostrzeżenia


@dataclass
class LiveCheck:
    level: str        # ok / warn / gone
    text: str
    phase: str        # buy / sell
    hop_index: int    # którego hopu dotyczy (0-based) — po przejściu dalej komunikat znika


def _norm(name: str) -> str:
    n = "".join(ch for ch in name.lower() if ch.isalnum())
    return n[:-1] if n.endswith("s") else n


def find_item(items: list[MarketItem], commodity: str, names: dict[str, str]) -> Optional[MarketItem]:
    """Market.json ma symbole (np. 'opal'), trasa nazwy wyświetlane ('Void Opal') — mapowanie przez FDevIDs."""
    target = commodity.lower()
    for item in items:
        display = names.get(item.name.lower())
        if (display and display.lower() == target) or _norm(item.name) == _norm(commodity):
            return item
    return None


def check_buy(hop: Hop, live: StationMarket, names: dict[str, str], hop_index: int = 0) -> LiveCheck:
    """Jesteś na stacji kupna: czy towar nadal jest, w jakiej cenie i ilości. Hop poprawiany cenami z gry."""
    item = find_item([i for i in live.exports if i.stock > 0 and i.buy_price > 0], hop.commodity, names)
    name = hop.commodity.upper()
    if item is None:
        return LiveCheck(GONE, f"✗ {name}: TOWARU JUŻ NIE MA", BUY, hop_index)
    new_per_t = hop.sell_price - item.buy_price
    if new_per_t <= 0:
        return LiveCheck(GONE, f"✗ {name} NIEOPŁACALNY (KUPNO {item.buy_price:,})", BUY, hop_index)
    warnings = []  # zysk/t spada tylko przez cenę kupna — "KUPNO +x%" wystarczy (pasek ma mało miejsca)
    if item.buy_price > hop.buy_price * (1 + PRICE_TOLERANCE):
        warnings.append(f"KUPNO +{item.buy_price / hop.buy_price - 1:.0%}")
    if item.stock < hop.amount:
        warnings.append(f"ZAPAS {item.stock:,} T")
    hop.buy_price = item.buy_price
    hop.amount = min(hop.amount, item.stock) if hop.amount else item.stock
    hop.profit = new_per_t * hop.amount
    hop.src_updated_at = time.time()
    if warnings:
        return LiveCheck(WARN, "⚠ " + " · ".join(warnings), BUY, hop_index)
    return LiveCheck(OK, "✓ CENY KUPNA POTWIERDZONE", BUY, hop_index)


def check_sell(hop: Hop, live: StationMarket, names: dict[str, str], hop_index: int = 0) -> LiveCheck:
    """Jesteś w celu: czy stacja nadal skupuje towar i za ile."""
    item = find_item([i for i in live.imports if i.sell_price > 0], hop.commodity, names)
    name = hop.commodity.upper()
    if item is None:
        return LiveCheck(WARN, f"⚠ TU JUŻ NIE SKUPUJĄ {name} — ZOBACZ OKOLICĘ", SELL, hop_index)
    level, text = OK, "✓ CENA SPRZEDAŻY POTWIERDZONA"
    if item.sell_price < hop.sell_price * (1 - PRICE_TOLERANCE):
        level, text = WARN, f"⚠ SPRZEDAŻ {item.sell_price / hop.sell_price - 1:.0%} ({item.sell_price:,})"
    hop.sell_price = item.sell_price
    hop.profit = (hop.sell_price - hop.buy_price) * hop.amount
    hop.dst_updated_at = time.time()
    return LiveCheck(level, text, SELL, hop_index)


def refresh_route_from_db(route, db, symbol_of: dict[str, str]) -> int:
    """Hopy trasy (Spansh) z cenami z lokalnej bazy EDDN, jeśli świeższe. Zwraca liczbę poprawionych cen.

    symbol_of: nazwa wyświetlana (lowercase) → symbol (np. "void opal" → "opal").
    """
    changed = 0
    for hop in route.hops_list or []:
        symbol = symbol_of.get(hop.commodity.lower(), hop.commodity.lower())
        old_profit = hop.profit
        src = db.get(hop.source_system, hop.source_station, symbol)
        if src is not None and src.updated_at > (hop.src_updated_at or 0) and src.buy_price > 0:
            hop.buy_price, hop.src_updated_at = src.buy_price, src.updated_at
            changed += 1
        dst = db.get(hop.destination_system, hop.destination_station, symbol)
        if dst is not None and dst.updated_at > (hop.dst_updated_at or 0) and dst.sell_price > 0:
            hop.sell_price, hop.dst_updated_at = dst.sell_price, dst.updated_at
            changed += 1
        if hop.profit:
            hop.profit = (hop.sell_price - hop.buy_price) * hop.amount
            route.total_profit += hop.profit - old_profit
    return changed
