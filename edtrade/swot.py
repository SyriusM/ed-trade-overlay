"""Analiza SWOT kandydata na handel — zanim overlay coś poleci.

Mocne strony:  zysk za pełny ładunek, marża na tonę.
Słabe strony:  mała podaż/popyt względem ładunku, mała część ładowni.
Szanse:        wolne miejsce do dopełnienia, kilka towarów w jednym ładunku.
Zagrożenia:    wiek danych rynku, brak potwierdzenia na żywym rynku (Market.json), wiele skoków, niskie bezpieczeństwo.

Twarde odrzucenie (kandydat znika z rekomendacji): towaru nie ma na żywym rynku albo kosztuje tu więcej, niż da się
za niego dostać; popyt 0 u kupca; dane rynku starsze niż STALE_REJECT_H.
"""

import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

STALE_WARN_H = 6.0       # od tylu godzin wiek danych jest zagrożeniem pokazywanym graczowi
STALE_REJECT_H = 72.0    # starsze dane = kandydat odrzucony
LOW_FILL = 0.5           # ładunek poniżej połowy ładowni to słaba strona
PRICE_UP = 0.10          # cena live wyższa o 10%+ od tej, którą liczył Spansh
LIVE_MAX_AGE_S = 3600    # Market.json starszy niż godzina to poprzednia wizyta, nie żywy rynek

# Etykiety (PL); po scaleniu katalogu tłumaczeń przejdą do edtrade/i18n.py
LABELS = {
    "profit": "zysk {value}",
    "per_t": "{value}/t",
    "supply": "podaż {have}/{need}",
    "demand": "popyt {have}/{need}",
    "fill": "ładownia {pct}%",
    "free": "wolne {tons}T",
    "mix": "mix {n} towarów",
    "age": "dane {age}",
    "no_live": "brak danych live",
    "live_ok": "rynek live ✓",
    "price_up": "{name} drożej o {pct}%",
    "jumps": "{n} skoki",
    "security": "{value}",
    "no_stock": "brak {name} na rynku",
    "not_profitable": "{name}: cena kupna ≥ sprzedaży",
    "no_demand": "brak popytu na {name}",
    "stale": "dane {age} — za stare",
}

LOW_SECURITY = {"anarchy": "anarchia", "lawless": "anarchia", "low": "niskie bezp."}


def _t(key: str, **values) -> str:
    return LABELS[key].format(**values)


def norm(name: str) -> str:
    """'$gold_name;' / 'Gold' / 'Low Temperature Diamonds' → klucz porównywalny między journalem a Spansh."""
    name = (name or "").lower()
    if name.startswith("$") and name.endswith("_name;"):
        name = name[1:-6]
    return "".join(ch for ch in name if ch.isalnum())


def short_money(value: float) -> str:
    value = float(value)
    if abs(value) >= 1e6:
        return f"{value / 1e6:.1f}M"
    if abs(value) >= 1e3:
        return f"{value / 1e3:.0f}k"
    return f"{value:.0f}"


def age_text(hours: float) -> str:
    if hours < 1:
        return "<1h"
    return f"{hours:.0f}h" if hours < 48 else f"{hours / 24:.0f}d"


def _ts(value) -> float:
    """Unix (Spansh market_updated_at) albo ISO (Ardent updatedAt, journal) → unix; 0 gdy brak."""
    if not value:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.timestamp()


@dataclass
class LiveItem:
    buy_price: int = 0
    sell_price: int = 0
    stock: int = 0
    demand: int = 0


@dataclass
class LiveMarket:
    """Żywy rynek stacji z Market.json — zapisywany przez grę po otwarciu ekranu rynku."""
    system: str = ""
    station: str = ""
    market_id: int = 0
    timestamp: float = 0.0
    items: dict = field(default_factory=dict)  # norm(nazwa) → LiveItem

    def is_at(self, system: str, station: str, now: Optional[float] = None) -> bool:
        """Ta stacja i świeży odczyt (z tej wizyty) — dopiero wtedy żywy rynek przeważa nad danymi Spansh/Ardent."""
        if self.timestamp and (now or time.time()) - self.timestamp > LIVE_MAX_AGE_S:
            return False
        return (self.station.lower() == (station or "").lower()
                and (not system or not self.system or self.system.lower() == system.lower()))

    def get(self, name: str) -> Optional[LiveItem]:
        return self.items.get(norm(name))


def live_market_from_json(data: dict) -> LiveMarket:
    market = LiveMarket(system=data.get("StarSystem", ""), station=data.get("StationName", ""),
                        market_id=int(data.get("MarketID") or 0), timestamp=_ts(data.get("timestamp")))
    for item in data.get("Items") or []:
        live = LiveItem(buy_price=int(item.get("BuyPrice") or 0), sell_price=int(item.get("SellPrice") or 0),
                        stock=int(item.get("Stock") or 0), demand=int(item.get("Demand") or 0))
        for key in {norm(item.get("Name", "")), norm(item.get("Name_Localised", ""))} - {""}:
            market.items[key] = live
    return market


def load_live_market(journal_dir: Optional[Path]) -> Optional[LiveMarket]:
    if not journal_dir:
        return None
    path = Path(journal_dir) / "Market.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return live_market_from_json(json.load(f))
    except (OSError, ValueError) as e:
        logger.debug("Market.json niedostępny (%s): %s", path, e)
        return None


@dataclass
class Swot:
    strengths: list = field(default_factory=list)
    weaknesses: list = field(default_factory=list)
    opportunities: list = field(default_factory=list)
    threats: list = field(default_factory=list)
    rejected: str = ""          # powód twardego odrzucenia; pusty = kandydat dopuszczony
    profit: int = 0             # zysk po korekcie o żywy rynek

    def reasons(self, n: int = 2) -> list[str]:
        """Najważniejsze powody dla gracza: odrzucenie, potem słabości i zagrożenia, a gdy ich brak — mocne strony."""
        ordered = ([self.rejected] if self.rejected else []) + self.weaknesses + self.threats
        return (ordered or self.strengths)[:n]

    def short(self, n: int = 2) -> str:
        return " · ".join(self.reasons(n))

    def merge(self, other: "Swot") -> None:
        for name in ("strengths", "weaknesses", "opportunities", "threats"):
            mine = getattr(self, name)
            mine.extend(x for x in getattr(other, name) if x not in mine)
        self.rejected = self.rejected or other.rejected


def _age_check(swot: Swot, updated_at, now: float) -> None:
    ts = _ts(updated_at)
    if not ts:
        return
    hours = max(0.0, (now - ts) / 3600)
    if hours >= STALE_REJECT_H:
        swot.rejected = swot.rejected or _t("stale", age=age_text(hours))
    elif hours >= STALE_WARN_H:
        swot.threats.append(_t("age", age=age_text(hours)))


def _security_check(swot: Swot, security: str) -> None:
    key = (security or "").lower()
    for word, label in LOW_SECURITY.items():
        if word in key:
            swot.threats.append(_t("security", value=label))
            return


def _fill_checks(swot: Swot, amount: int, capacity: int) -> None:
    if capacity <= 0:
        return
    if amount < capacity * LOW_FILL:
        swot.weaknesses.append(_t("fill", pct=int(100 * amount / capacity)))
    if amount < capacity:
        swot.opportunities.append(_t("free", tons=capacity - amount))


def assess_hop(hop, capacity: int, live: Optional[LiveMarket] = None, now: Optional[float] = None,
               jump_range: float = 0.0, security: str = "") -> Swot:
    """SWOT jednego hopu z trasy Spansh. Żywy rynek liczy się tylko, gdy to stacja kupna hopu."""
    now = now or time.time()
    swot = Swot()
    items = list(hop.commodities) or []
    live = live if live is not None and live.is_at(hop.source_system, hop.source_station, now) else None

    profit, amount, dropped = 0, 0, {}
    for c in items:
        units, buy = c.amount, c.buy_price
        if live is not None:
            item = live.get(c.name)
            if item is None or item.stock <= 0 or item.buy_price <= 0:
                dropped[c.name] = _t("no_stock", name=c.name)
                continue
            if item.buy_price >= c.sell_price:
                dropped[c.name] = _t("not_profitable", name=c.name)
                continue
            if item.stock < units:
                swot.weaknesses.append(_t("supply", have=item.stock, need=units))
                units = item.stock
            if buy and item.buy_price > buy * (1 + PRICE_UP):
                swot.threats.append(_t("price_up", name=c.name, pct=int(100 * (item.buy_price - buy) / buy)))
            buy = item.buy_price
        elif c.supply is not None and c.supply < units:
            swot.weaknesses.append(_t("supply", have=c.supply, need=units))
            units = c.supply
        if c.demand is not None and c.demand <= 0:
            dropped[c.name] = _t("no_demand", name=c.name)
            continue
        if c.demand is not None and c.demand < units:
            swot.weaknesses.append(_t("demand", have=c.demand, need=units))
            units = c.demand
        if units <= 0:
            continue
        amount += units
        profit += units * (c.sell_price - buy)

    swot.profit = profit
    swot.weaknesses[:0] = list(dropped.values())
    # Główny towar hopu niedostępny = to już inny handel niż ten, który policzył Spansh
    if items and (items[0].name in dropped or profit <= 0):
        swot.rejected = dropped.get(items[0].name) or next(iter(dropped.values()), _t("no_stock", name=items[0].name))
    if profit > 0:
        swot.strengths.append(_t("profit", value=short_money(profit)))
        if amount:
            swot.strengths.append(_t("per_t", value=short_money(profit / amount)))
    _fill_checks(swot, amount, capacity)
    if len(items) > 1:
        swot.opportunities.append(_t("mix", n=len(items)))

    if live is None:
        _age_check(swot, getattr(hop, "source_updated_at", 0), now)
    _age_check(swot, getattr(hop, "destination_updated_at", 0), now)
    if jump_range and hop.distance > jump_range:
        swot.threats.append(_t("jumps", n=math.ceil(hop.distance / jump_range)))
    _security_check(swot, security)
    return swot


def assess_route(route, capacity: int, live: Optional[LiveMarket] = None, now: Optional[float] = None,
                 jump_range: float = 0.0, security: str = "") -> Swot:
    """SWOT całej trasy: hop odrzucony = trasa odrzucona (plan się rozsypuje w połowie)."""
    now = now or time.time()
    total = Swot()
    hops = route.hops_list or []
    if not hops:
        return total
    first_live = live is not None and live.is_at(hops[0].source_system, hops[0].source_station, now)
    for i, hop in enumerate(hops):
        swot = assess_hop(hop, capacity, live if i == 0 else None, now, jump_range, security if i == 0 else "")
        total.merge(swot)
        total.profit += swot.profit
    if not first_live:
        total.threats.insert(0, _t("no_live"))
    else:
        total.strengths.append(_t("live_ok"))
    return total


def apply_to_route(route, capacity: int, live: Optional[LiveMarket] = None, now: Optional[float] = None,
                   jump_range: float = 0.0, security: str = ""):
    """Ocena przed rekomendacją: odrzucona trasa dostaje błąd z powodem, dopuszczona — `_swot` z uwagami."""
    if route.error or not route.hops_list:
        return route
    swot = assess_route(route, capacity, live, now, jump_range, security)
    route._swot = swot
    if swot.rejected:
        logger.info("SWOT odrzuca trasę: %s", swot.rejected)
        route.error = f"odrzucona: {swot.rejected}"
    else:
        logger.info("SWOT: S=%s W=%s O=%s T=%s", swot.strengths, swot.weaknesses, swot.opportunities, swot.threats)
    return route


def assess_trade(trade, capacity: int, live: Optional[LiveMarket] = None, live_station: tuple = (),
                 now: Optional[float] = None) -> Swot:
    """SWOT okazji z zakładki Okolica (NearbyTrade). live_station = (system, stacja kupna)."""
    now = now or time.time()
    swot = Swot()
    units, buy = trade.units, trade.buy_price
    live_ok = bool(live_station) and live is not None and live.is_at(*live_station, now=now)
    if trade.buy_price > 0 and live_ok:
        item = live.get(trade.commodity)
        if item is None or item.stock <= 0 or item.buy_price <= 0:
            swot.rejected = _t("no_stock", name=trade.commodity)
            return swot
        if item.buy_price >= trade.sell_price:
            swot.rejected = _t("not_profitable", name=trade.commodity)
            return swot
        buy = item.buy_price
        units = min(capacity or units, item.stock, trade.demand or item.stock)
        if item.stock < capacity:
            swot.weaknesses.append(_t("supply", have=item.stock, need=capacity))
    elif trade.buy_price > 0:
        if trade.stock <= 0:
            swot.rejected = _t("no_stock", name=trade.commodity)
            return swot
        if trade.stock < capacity:
            swot.weaknesses.append(_t("supply", have=trade.stock, need=capacity))
        swot.threats.append(_t("no_live"))
    if trade.demand and trade.demand < units:
        units = trade.demand
    if trade.demand and capacity and trade.demand < capacity:
        swot.weaknesses.append(_t("demand", have=trade.demand, need=capacity))
    swot.profit = units * (trade.sell_price - buy)
    if swot.profit <= 0:
        swot.rejected = _t("not_profitable", name=trade.commodity)
        return swot
    swot.strengths.append(_t("profit", value=short_money(swot.profit)))
    swot.strengths.append(_t("per_t", value=short_money(trade.sell_price - buy)))
    if trade.buy_price > 0:
        _fill_checks(swot, units, capacity)
    _age_check(swot, trade.updated_at, now)
    return swot


def screen_trades(trades: list, capacity: int, live: Optional[LiveMarket] = None, live_station: tuple = (),
                  now: Optional[float] = None) -> tuple[list, dict]:
    """Odsiewa odrzucone okazje (kolejność zachowana); zwraca (dopuszczone, {id(trade): Swot}).

    Szansa: inne towary z tej listy sprzedawane w tej samej stacji — razem dopełnią ładownię.
    """
    kept, swots = [], {}
    for trade in trades:
        swot = assess_trade(trade, capacity, live, live_station, now)
        if swot.rejected:
            logger.info("SWOT odrzuca %s → %s: %s", trade.commodity, trade.sell_station, swot.rejected)
            continue
        kept.append(trade)
        swots[id(trade)] = swot
    for trade in kept:
        partners = [o.commodity for o in kept if o is not trade and o.sell_station == trade.sell_station
                    and o.sell_system == trade.sell_system]
        if partners and capacity and trade.units < capacity:
            swots[id(trade)].opportunities.append("+ " + ", ".join(partners[:2]))
    return kept, swots
