"""Podsumowanie sesji handlowej z journala (jak panele Credit/Summary w TCE).

Gra zaczyna nowy plik journala przy każdym uruchomieniu, a watcher przy starcie czyta
cały bieżący plik — więc sesja = zakupy i sprzedaże z bieżącego pliku, od `LoadGame`.
Zysk sprzedaży = TotalSale − AvgPricePaid × Count (towar wydobyty: AvgPricePaid 0 → cała sprzedaż).
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _parse_ts(value: str) -> Optional[datetime]:
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


@dataclass
class Trade:
    timestamp: datetime
    kind: str            # "buy" / "sell"
    commodity: str       # symbol z journala (np. "biowaste")
    count: int
    price: int           # cena za tonę
    total: int           # TotalCost / TotalSale
    profit: int = 0      # tylko sprzedaż
    system: str = ""
    station: str = ""


@dataclass
class SessionSummary:
    started_at: Optional[datetime] = None
    trades: list[Trade] = field(default_factory=list)

    @property
    def sells(self) -> list[Trade]:
        return [t for t in self.trades if t.kind == "sell"]

    @property
    def profit(self) -> int:
        return sum(t.profit for t in self.sells)

    @property
    def revenue(self) -> int:
        return sum(t.total for t in self.sells)

    @property
    def spent(self) -> int:
        return sum(t.total for t in self.trades if t.kind == "buy")

    @property
    def tons_sold(self) -> int:
        return sum(t.count for t in self.sells)

    @property
    def best_sale(self) -> Optional[Trade]:
        return max(self.sells, key=lambda t: t.profit, default=None)

    def hours(self, now: Optional[datetime] = None) -> float:
        if self.started_at is None:
            return 0.0
        return max(0.0, ((now or datetime.now(timezone.utc)) - self.started_at).total_seconds() / 3600)

    def profit_per_hour(self, now: Optional[datetime] = None) -> int:
        """cr/h od startu sesji; poniżej 5 min za mało danych → 0."""
        hours = self.hours(now)
        return int(self.profit / hours) if hours >= 5 / 60 else 0


class SessionLedger:
    """Zbiera eventy z wątku watchera; `summary()` zwraca kopię dla wątku Tk."""

    def __init__(self):
        self._lock = threading.Lock()
        self._summary = SessionSummary()
        self._docked = ("", "")

    def on_event(self, ev: dict) -> bool:
        """Zwraca True, gdy podsumowanie się zmieniło."""
        event = ev.get("event", "")
        ts = _parse_ts(ev.get("timestamp", ""))
        with self._lock:
            if event == "LoadGame":
                self._summary = SessionSummary(started_at=ts)
                return True
            if event == "Docked" or (event == "Location" and ev.get("Docked")):
                self._docked = (ev.get("StarSystem", ""), ev.get("StationName", ""))
                return False
            if event not in ("MarketBuy", "MarketSell") or ts is None:
                return False
            if self._summary.started_at is None:
                self._summary.started_at = ts  # journal bez LoadGame (np. test) — sesja od 1. transakcji
            count = int(ev.get("Count") or 0)
            if event == "MarketBuy":
                trade = Trade(ts, "buy", ev.get("Type", ""), count, int(ev.get("BuyPrice") or 0),
                              int(ev.get("TotalCost") or 0))
            else:
                total = int(ev.get("TotalSale") or 0)
                trade = Trade(ts, "sell", ev.get("Type", ""), count, int(ev.get("SellPrice") or 0), total,
                              profit=total - int(ev.get("AvgPricePaid") or 0) * count)
            trade.system, trade.station = self._docked
            self._summary.trades.append(trade)
            return True

    def summary(self) -> SessionSummary:
        with self._lock:
            return SessionSummary(self._summary.started_at, list(self._summary.trades))
