"""Ocena okazji handlowej na bieżąco: SAFE / OPTIMAL / RISKY + punkty SWOT i stopień (0–1).

Wartość = zysk oczekiwany względem najlepszej okazji na tej samej liście (w trybie rankingu),
ryzyko = szansa, że na miejscu będzie inaczej (wiek cen, płytki popyt, długi lot).
Progi to PRZYBLIŻENIA do strojenia po testach w grze — nie dane z gry.
"""

from dataclasses import dataclass, field
from typing import Optional

SAFE, OPTIMAL, RISKY = "safe", "optimal", "risky"
ICONS = {OPTIMAL: "=", SAFE: "▲", RISKY: "▼"}
LABELS = {OPTIMAL: "OPTIMAL", SAFE: "SAFE", RISKY: "RISKY"}

RISKY_FROM = 0.45     # ryzyko od tego progu → RISKY
OPTIMAL_FROM = 0.75   # wartość ≥ 75% najlepszej (przy umiarkowanym ryzyku) → OPTIMAL
SAFE_UNTIL = 0.25     # niskie ryzyko, mniejszy zysk → SAFE
VERY_SAFE_FROM = 0.8  # shade SAFE od tego progu → "VERY SAFE" (ryzyko ≤ 0.05)
LONG_TRIP_S = 30 * 60


@dataclass
class Assessment:
    verdict: str
    shade: float  # pozycja w gradiencie klasy: SAFE 0 zielony → 1 ciemnozielony (VERY SAFE);
                  # RISKY 0 czerwony (wysoki zysk) → 1 ciemnoczerwony (okazji pewnie już nie ma)
    value: float                       # 0–1 względem najlepszej okazji na liście
    risk: float                        # 0–1
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    opportunities: list[str] = field(default_factory=list)
    threats: list[str] = field(default_factory=list)

    @property
    def badge(self) -> str:
        if self.verdict == SAFE and self.shade >= VERY_SAFE_FROM:
            return f"{ICONS[SAFE]} VERY SAFE"
        return f"{ICONS[self.verdict]} {LABELS[self.verdict]}"

    def swot_text(self) -> str:
        """Strzałki (czytelniejsze niż +/−): ▲ za (S, O), ▼ przeciw (W, T): "▲S: short trip · ▼T: prices 5 d"."""
        parts = [(k, v) for k, v in (("▲S", self.strengths), ("▼W", self.weaknesses),
                                     ("▲O", self.opportunities), ("▼T", self.threats)) if v]
        return "  ·  ".join(f"{k}: {', '.join(v)}" for k, v in parts)


def age_risk(hours: Optional[float]) -> float:
    if hours is None:
        return 0.45
    if hours <= 6:
        return 0.0
    if hours <= 24:
        return 0.15
    if hours <= 72:
        return 0.4
    return 0.7


def demand_risk(demand: int, units: int) -> float:
    """Sprzedaż dużej partii w płytki popyt obniża cenę (i inni gracze też tam sprzedają)."""
    if units <= 0 or demand <= 0:
        return 0.0
    ratio = demand / units
    if ratio >= 3:
        return 0.0
    return 0.5 if ratio <= 1 else 0.5 * (3 - ratio) / 2


def combine(*risks: float) -> float:
    """Niezależne ryzyka: 1 − Π(1 − r)."""
    keep = 1.0
    for r in risks:
        keep *= 1 - max(0.0, min(1.0, r))
    return 1 - keep


def classify(value: float, risk: float) -> tuple[str, float]:
    """(werdykt, shade). OPTIMAL ma jeden kolor (limonka); SAFE i RISKY mają gradient."""
    if risk >= RISKY_FROM:
        gone = (risk - RISKY_FROM) / (1 - RISKY_FROM)  # im wyższe ryzyko, tym bardziej "już nie ma"
        return RISKY, min(1.0, 0.65 * gone + 0.35 * (1 - value))
    if value >= OPTIMAL_FROM:
        return OPTIMAL, 0.0
    if risk <= SAFE_UNTIL:
        return SAFE, 1 - risk / SAFE_UNTIL  # ryzyko 0 → VERY SAFE (ciemnozielony)
    # umiarkowane ryzyko przy przeciętnym zysku — RISKY z jasnej strony skali
    return RISKY, 0.35 * (1 - value)


def assess_trade(trade, best_value: float, value_of, capacity: int = 0) -> Assessment:
    """trade: NearbyTrade; value_of: funkcja wartości w bieżącym trybie (np. expected_per_hour)."""
    value = max(0.0, min(1.0, value_of(trade) / best_value)) if best_value > 0 else 0.0
    hours = trade.age_hours
    r_age = age_risk(hours)
    r_demand = demand_risk(trade.demand, trade.units)
    r_trip = 0.15 if trade.travel_s > LONG_TRIP_S else 0.0
    risk = combine(r_age, r_demand, r_trip)
    a = Assessment(*classify(value, risk), value=value, risk=risk)

    if value >= 0.95:
        a.strengths.append("best in list")
    elif value >= OPTIMAL_FROM:
        a.strengths.append(f"{value:.0%} of best")
    if trade.travel_s and trade.travel_s <= 8 * 60:
        a.strengths.append("short trip")
    if hours is not None and hours <= 6:
        a.strengths.append("fresh prices")

    if trade.distance_to_arrival > 5000:
        a.weaknesses.append(f"{trade.distance_to_arrival:,.0f} ls from star")
    if r_trip:
        a.weaknesses.append(f"{trade.travel_s / 60:.0f} min trip")
    if capacity and 0 < trade.units < capacity:
        a.weaknesses.append(f"only {trade.units}/{capacity} t")
    if value < 0.4:
        a.weaknesses.append("low profit vs best")

    if trade.demand >= 3 * max(trade.units, 1):
        a.opportunities.append("deep demand")
    if trade.profit_per_unit >= 20_000:
        a.opportunities.append(f"{trade.profit_per_unit:,} cr/t")

    if r_age >= 0.4:
        a.threats.append("prices " + ("unknown" if hours is None else f"{hours / 24:.0f} d" if hours >= 48 else f"{hours:.0f} h"))
    if r_demand:
        a.threats.append(f"shallow demand ({trade.demand:,})")
    return a


def assess_all(trades: list, value_of, capacity: int = 0) -> list[Assessment]:
    best = max((value_of(t) for t in trades), default=0.0)
    return [assess_trade(t, best, value_of, capacity) for t in trades]


def value_for_mode(mode: str):
    if mode == "total":
        return lambda t: t.expected_total
    if mode == "time":
        # najkrótsza droga: wartość = szybkość dotarcia (odwrotność czasu)
        return lambda t: 1.0 / t.travel_s if t.travel_s else 0.0
    return lambda t: t.expected_per_hour


def assess_route_hop(age_h: Optional[float]) -> tuple[str, float]:
    """Trasa ze Spansh jest już optymalna zyskowo — o werdykcie decyduje pewność cen celu."""
    risk = age_risk(age_h)
    return classify(1.0, risk)


# --- Ładownia: trzymać czy sprzedać? -------------------------------------------------------------

SELL_HERE, SELL_THERE, HOLD = "sell_here", "sell_there", "hold"
CARGO_BADGES = {SELL_HERE: "= SELL HERE", SELL_THERE: "► SELL THERE", HOLD: "■ HOLD"}


@dataclass
class CargoAdvice(Assessment):
    action: str = HOLD

    @property
    def badge(self) -> str:
        return CARGO_BADGES[self.action]


def advise_cargo(count: int, best=None, best_assessment: Optional[Assessment] = None,
                 here_price: int = 0, mean_price: int = 0, paid_price: int = 0) -> CargoAdvice:
    """best: najlepszy kupiec w okolicy (NearbyTrade) albo None; here_price: ile płaci stacja, na której jesteś.

    Kolor: SELL HERE = optimal (zielony), SELL THERE = werdykt tamtej okazji, HOLD = żółty.
    """
    there_price = best.sell_price if best is not None else 0
    there_expected = there_price * (best.confidence if best is not None else 0)
    top_price = max(here_price, there_price)

    def hold(shade: float, **swot) -> CargoAdvice:
        a = CargoAdvice("hold", shade, value=0.0, risk=0.0, action=HOLD)
        for key, items in swot.items():
            getattr(a, key).extend(items)
        return a

    if top_price <= 0:
        return hold(0.6, weaknesses=["no buyer in range"], opportunities=["increase range or fly further"])
    if paid_price and top_price < paid_price:
        return hold(min(1.0, 0.4 + (paid_price - top_price) / paid_price),
                    threats=[f"loss {paid_price - top_price:,} cr/t"], opportunities=["look for a better price"])
    if mean_price and top_price < 0.85 * mean_price:
        below = 1 - top_price / mean_price
        return hold(min(1.0, 0.3 + below), weaknesses=[f"price {below:.0%} below average"],
                    opportunities=["galactic average is higher"])

    if here_price and here_price >= 0.9 * there_expected:
        a = CargoAdvice("optimal", 0.0, value=1.0, risk=0.0, action=SELL_HERE)
        a.strengths.append("no trip")
        if mean_price and here_price >= mean_price:
            a.strengths.append(f"+{here_price / mean_price - 1:.0%} vs average")
        if there_price > here_price:
            a.weaknesses.append(f"elsewhere +{there_price - here_price:,} cr/t")
        if paid_price:
            a.opportunities.append(f"profit {here_price - paid_price:,} cr/t")
        a.shade = 0.0  # OPTIMAL — jeden kolor (limonka)
        return a

    base = best_assessment or Assessment(SAFE, 0.5, 1.0, 0.0)
    a = CargoAdvice(base.verdict, base.shade, value=base.value, risk=base.risk, action=SELL_THERE,
                    strengths=list(base.strengths), weaknesses=list(base.weaknesses),
                    opportunities=list(base.opportunities), threats=list(base.threats))
    gain = (there_price - here_price) * count
    if here_price:
        a.strengths.insert(0, f"+{gain:,} cr vs selling here")
    if paid_price:
        a.opportunities.append(f"profit {there_price - paid_price:,} cr/t")
    return a
