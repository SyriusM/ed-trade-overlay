"""Analiza SWOT kandydata na handel — zanim overlay coś poleci.

Mocne strony:  zysk za pełny ładunek, marża na tonę.
Słabe strony:  mała podaż/popyt względem ładunku, mała część ładowni.
Szanse:        wolne miejsce do dopełnienia, kilka towarów w jednym ładunku.
Zagrożenia:    wiek danych rynku, brak potwierdzenia na żywym rynku (Market.json), wiele skoków, niskie bezpieczeństwo.

Twarde odrzucenie (kandydat znika z rekomendacji): towaru nie ma na żywym rynku albo kosztuje tu więcej, niż da się
za niego dostać; popyt 0 u kupca; dane rynku za stare dla wybranej strategii.

Strategia (config `trade_strategy`) ustawia progi i wagi: risky = maksymalny zysk, toleruje małą podaż i stare dane;
optimal = domyślna równowaga; safe = świeże dane, głęboka podaż, mniej skoków, bez anarchii.
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

PRICE_UP = 0.10          # cena live wyższa o 10%+ od tej, którą liczył Spansh
LIVE_MAX_AGE_S = 3600    # Market.json starszy niż godzina to poprzednia wizyta, nie żywy rynek



@dataclass(frozen=True)
class Strategy:
    stale_warn_h: float      # od tylu godzin wiek danych jest zagrożeniem pokazywanym graczowi
    stale_reject_h: float    # starsze dane = kandydat odrzucony
    low_fill: float          # ładunek poniżej tej części ładowni to słaba strona
    min_cover: float         # podaż/popyt pokrywające mniej niż tę część ładunku = odrzucenie (0 = tylko uwaga)
    reject_low_security: bool
    max_jumps: int           # więcej skoków na hop = odrzucenie (0 = bez limitu)
    penalty: float           # o ile każda słabość/zagrożenie obniża pozycję w rankingu
    hold_gain: float         # o ile więcej musi dać kupiec w okolicy, żeby nie sprzedawać ładunku tutaj


STRATEGIES = {
    "risky": Strategy(stale_warn_h=24, stale_reject_h=240, low_fill=0.2, min_cover=0.0, reject_low_security=False,
                      max_jumps=0, penalty=0.0, hold_gain=0.05),
    "optimal": Strategy(stale_warn_h=6, stale_reject_h=72, low_fill=0.5, min_cover=0.0, reject_low_security=False,
                        max_jumps=0, penalty=0.05, hold_gain=0.10),
    "safe": Strategy(stale_warn_h=2, stale_reject_h=24, low_fill=0.5, min_cover=0.5, reject_low_security=True,
                     max_jumps=2, penalty=0.15, hold_gain=0.25),
}
DEFAULT_STRATEGY = "optimal"
STRATEGY_LABELS = {"risky": "Ryzykowna (max zysk)", "optimal": "Optymalna", "safe": "Bezpieczna (pewny handel)"}


def get_strategy(name) -> Strategy:
    return name if isinstance(name, Strategy) else STRATEGIES.get(name or DEFAULT_STRATEGY, STRATEGIES[DEFAULT_STRATEGY])


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
    "too_thin": "{what} {have}/{need} — za mało",
    "too_far": "{n} skoki — za daleko",
    "unsafe": "{value} — za ryzykownie",
    "sell_here": "sprzedaj tutaj",
    "sell_here_best": "tu najlepiej w okolicy",
    "hold_for": "wieź dalej: +{pct}% w {station}",
    "sell_at": "{station}: {price} cr",
    "borderline": "na granicy: {station} +{pct}%",
    "not_bought_here": "tu nie kupują",
    "no_buyer": "brak kupca w zasięgu",
    "no_price_here": "brak ceny tutaj",
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
    penalty: float = 0.0        # waga strategii za każdą słabość/zagrożenie

    @property
    def rank_factor(self) -> float:
        """Mnożnik wyniku w rankingu: safe mocniej spycha ryzykowne okazje w dół, risky wcale."""
        return max(0.2, 1.0 - self.penalty * (len(self.weaknesses) + len(self.threats)))

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


def _age_check(swot: Swot, updated_at, now: float, st: Strategy) -> None:
    ts = _ts(updated_at)
    if not ts:
        return
    hours = max(0.0, (now - ts) / 3600)
    if hours >= st.stale_reject_h:
        swot.rejected = swot.rejected or _t("stale", age=age_text(hours))
    elif hours >= st.stale_warn_h:
        swot.threats.append(_t("age", age=age_text(hours)))


def _cover_check(swot: Swot, key: str, have: int, need: int, st: Strategy) -> None:
    """Podaż/popyt mniejsze niż ładunek: uwaga, a w strategii safe przy płytkim rynku — odrzucenie."""
    if need > 0 and have < need * st.min_cover:
        swot.rejected = swot.rejected or _t("too_thin", what=LABELS[key].split()[0], have=have, need=need)
    else:
        swot.weaknesses.append(_t(key, have=have, need=need))


def _security_check(swot: Swot, security: str, st: Strategy) -> None:
    key = (security or "").lower()
    for word, label in LOW_SECURITY.items():
        if word in key:
            if st.reject_low_security and label == "anarchia":
                swot.rejected = swot.rejected or _t("unsafe", value=label)
            else:
                swot.threats.append(_t("security", value=label))
            return


def _jumps_check(swot: Swot, distance: float, jump_range: float, st: Strategy) -> None:
    if not jump_range or distance <= jump_range:
        return
    jumps = math.ceil(distance / jump_range)
    if st.max_jumps and jumps > st.max_jumps:
        swot.rejected = swot.rejected or _t("too_far", n=jumps)
    else:
        swot.threats.append(_t("jumps", n=jumps))


def _fill_checks(swot: Swot, amount: int, capacity: int, st: Strategy) -> None:
    if capacity <= 0:
        return
    if amount < capacity * st.low_fill:
        swot.weaknesses.append(_t("fill", pct=int(100 * amount / capacity)))
    if amount < capacity:
        swot.opportunities.append(_t("free", tons=capacity - amount))


def assess_hop(hop, capacity: int, live: Optional[LiveMarket] = None, now: Optional[float] = None,
               jump_range: float = 0.0, security: str = "", strategy=DEFAULT_STRATEGY) -> Swot:
    """SWOT jednego hopu z trasy Spansh. Żywy rynek liczy się tylko, gdy to stacja kupna hopu."""
    now = now or time.time()
    st = get_strategy(strategy)
    swot = Swot(penalty=st.penalty)
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
                _cover_check(swot, "supply", item.stock, units, st)
                units = item.stock
            if buy and item.buy_price > buy * (1 + PRICE_UP):
                swot.threats.append(_t("price_up", name=c.name, pct=int(100 * (item.buy_price - buy) / buy)))
            buy = item.buy_price
        elif c.supply is not None and c.supply < units:
            _cover_check(swot, "supply", c.supply, units, st)
            units = c.supply
        if c.demand is not None and c.demand <= 0:
            dropped[c.name] = _t("no_demand", name=c.name)
            continue
        if c.demand is not None and c.demand < units:
            _cover_check(swot, "demand", c.demand, units, st)
            units = c.demand
        if units <= 0:
            continue
        amount += units
        profit += units * (c.sell_price - buy)

    swot.profit = profit
    swot.weaknesses[:0] = list(dropped.values())
    # Główny towar hopu niedostępny = to już inny handel niż ten, który policzył Spansh
    if items and (items[0].name in dropped or profit <= 0):
        swot.rejected = swot.rejected or dropped.get(items[0].name) or next(iter(dropped.values()), _t("no_stock", name=items[0].name))
    if profit > 0:
        swot.strengths.append(_t("profit", value=short_money(profit)))
        if amount:
            swot.strengths.append(_t("per_t", value=short_money(profit / amount)))
    _fill_checks(swot, amount, capacity, st)
    if len(items) > 1:
        swot.opportunities.append(_t("mix", n=len(items)))

    if live is None:
        _age_check(swot, getattr(hop, "source_updated_at", 0), now, st)
    _age_check(swot, getattr(hop, "destination_updated_at", 0), now, st)
    _jumps_check(swot, hop.distance, jump_range, st)
    _security_check(swot, security, st)
    return swot


def assess_route(route, capacity: int, live: Optional[LiveMarket] = None, now: Optional[float] = None,
                 jump_range: float = 0.0, security: str = "", strategy=DEFAULT_STRATEGY) -> Swot:
    """SWOT całej trasy: hop odrzucony = trasa odrzucona (plan się rozsypuje w połowie)."""
    now = now or time.time()
    total = Swot(penalty=get_strategy(strategy).penalty)
    hops = route.hops_list or []
    if not hops:
        return total
    first_live = live is not None and live.is_at(hops[0].source_system, hops[0].source_station, now)
    for i, hop in enumerate(hops):
        swot = assess_hop(hop, capacity, live if i == 0 else None, now, jump_range, security if i == 0 else "",
                          strategy)
        total.merge(swot)
        total.profit += swot.profit
    if not first_live:
        total.threats.insert(0, _t("no_live"))
    else:
        total.strengths.append(_t("live_ok"))
    return total


def apply_to_route(route, capacity: int, live: Optional[LiveMarket] = None, now: Optional[float] = None,
                   jump_range: float = 0.0, security: str = "", strategy=DEFAULT_STRATEGY):
    """Ocena przed rekomendacją: odrzucona trasa dostaje błąd z powodem, dopuszczona — `_swot` z uwagami."""
    if route.error or not route.hops_list:
        return route
    swot = assess_route(route, capacity, live, now, jump_range, security, strategy)
    route._swot = swot
    if swot.rejected:
        logger.info("SWOT odrzuca trasę: %s", swot.rejected)
        route.error = f"odrzucona: {swot.rejected}"
    else:
        logger.info("SWOT: S=%s W=%s O=%s T=%s", swot.strengths, swot.weaknesses, swot.opportunities, swot.threats)
    return route


def assess_trade(trade, capacity: int, live: Optional[LiveMarket] = None, live_station: tuple = (),
                 now: Optional[float] = None, strategy=DEFAULT_STRATEGY, jump_range: float = 0.0) -> Swot:
    """SWOT okazji z zakładki Okolica (NearbyTrade). live_station = (system, stacja kupna)."""
    now = now or time.time()
    st = get_strategy(strategy)
    swot = Swot(penalty=st.penalty)
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
            _cover_check(swot, "supply", item.stock, capacity, st)
    elif trade.buy_price > 0:
        if trade.stock <= 0:
            swot.rejected = _t("no_stock", name=trade.commodity)
            return swot
        if trade.stock < capacity:
            _cover_check(swot, "supply", trade.stock, capacity, st)
        swot.threats.append(_t("no_live"))
    if trade.demand and trade.demand < units:
        units = trade.demand
    if trade.demand and capacity and trade.demand < capacity:
        _cover_check(swot, "demand", trade.demand, capacity, st)
    swot.profit = units * (trade.sell_price - buy)
    if swot.profit <= 0:
        swot.rejected = _t("not_profitable", name=trade.commodity)
        return swot
    swot.strengths.append(_t("profit", value=short_money(swot.profit)))
    swot.strengths.append(_t("per_t", value=short_money(trade.sell_price - buy)))
    if trade.buy_price > 0:
        _fill_checks(swot, units, capacity, st)
    _age_check(swot, trade.updated_at, now, st)
    _jumps_check(swot, trade.distance, jump_range, st)
    return swot


def screen_trades(trades: list, capacity: int, live: Optional[LiveMarket] = None, live_station: tuple = (),
                  now: Optional[float] = None, strategy=DEFAULT_STRATEGY, jump_range: float = 0.0) -> tuple[list, dict]:
    """Odsiewa odrzucone okazje (kolejność zachowana); zwraca (dopuszczone, {id(trade): Swot}).

    Szansa: inne towary z tej listy sprzedawane w tej samej stacji — razem dopełnią ładownię.
    """
    kept, swots = [], {}
    for trade in trades:
        swot = assess_trade(trade, capacity, live, live_station, now, strategy, jump_range)
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


SELL, HOLD, BORDERLINE = "sell", "hold", "borderline"
ARROWS = {SELL: "▲", HOLD: "▼", BORDERLINE: "●"}
TAGS = {SELL: "good", HOLD: "bad", BORDERLINE: "warn"}   # zielony / czerwony / bursztynowy w tabeli panelu


@dataclass
class CargoVerdict:
    """Czy sprzedać towar z ładowni na tej stacji, czy wieźć dalej — wg SWOT i strategii."""
    level: str = BORDERLINE
    here_price: int = 0
    here_total: int = 0
    best: object = None          # NearbyTrade najlepszego kupca w okolicy (po odsianiu SWOT) albo None
    best_total: int = 0
    gain_pct: int = 0            # o ile % więcej da najlepszy kupiec niż sprzedaż tutaj
    note: str = ""

    @property
    def arrow(self) -> str:
        return ARROWS[self.level]

    @property
    def tag(self) -> str:
        return TAGS[self.level]


def cargo_verdict(count: int, here_price: int, candidates: list, strategy=DEFAULT_STRATEGY,
                  now: Optional[float] = None, jump_range: float = 0.0, capacity: int = 0) -> CargoVerdict:
    """▲ sprzedaj tutaj / ▼ trzymaj, bo w okolicy płacą wyraźnie więcej / ● na granicy (wg progu strategii).

    candidates: NearbyTrade dla tego towaru z innych stacji (buy_price=0 — towar już w ładowni).
    Kupcy odrzuceni przez SWOT (stare dane, za daleko dla strategii) nie liczą się jako lepsza oferta.
    """
    st = get_strategy(strategy)
    kept, swots = screen_trades(candidates, capacity or count, now=now, strategy=st, jump_range=jump_range)
    best = max(kept, key=lambda t: t.sell_price * min(count, t.demand or count) * swots[id(t)].rank_factor,
               default=None)
    v = CargoVerdict(here_price=here_price, here_total=here_price * count, best=best)
    if best is not None:
        v.best_total = best.sell_price * min(count, best.demand or count)
    if here_price <= 0:
        v.level = HOLD if best is not None else BORDERLINE
        v.note = _t("not_bought_here") + " · " + (
            _t("sell_at", station=best.sell_station, price=f"{best.sell_price:,}") if best else _t("no_buyer"))
        return v
    if best is None:
        v.level, v.note = SELL, _t("sell_here")
        return v
    gain = v.best_total / v.here_total - 1 if v.here_total else 0.0
    v.gain_pct = int(round(100 * gain))
    if gain >= st.hold_gain:
        v.level = HOLD
        v.note = _t("hold_for", station=best.sell_station, price=f"{best.sell_price:,}", pct=v.gain_pct)
    elif gain >= st.hold_gain / 2:
        v.level = BORDERLINE
        v.note = _t("borderline", station=best.sell_station, pct=v.gain_pct)
    else:
        v.level = SELL
        v.note = _t("sell_here_best") if gain <= 0 else _t("sell_here")
    return v
