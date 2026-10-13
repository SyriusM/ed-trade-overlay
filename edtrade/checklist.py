"""Checklista trasy handlowej odhaczana automatycznie z journala (kup → leć → sprzedaj, hop po hopie).

Overlay nie dostaje fokusu w grze, więc ręczne potwierdzanie kroków jest niemożliwe — postęp
wynika z eventów MarketBuy / Docked / MarketSell.
"""

import csv
import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .materials import fetch_cached
from .trade import Hop, TradeRoute

logger = logging.getLogger(__name__)

FDEVIDS_COMMODITY_URL = "https://raw.githubusercontent.com/EDCD/FDevIDs/master/commodity.csv"
FDEVIDS_RARE_URL = "https://raw.githubusercontent.com/EDCD/FDevIDs/master/rare_commodity.csv"


def parse_commodity_names(*csv_texts: str) -> dict[str, str]:
    """FDevIDs commodity.csv / rare_commodity.csv → {symbol lowercase: nazwa wyświetlana}."""
    names = {}
    for text in csv_texts:
        for row in csv.DictReader(io.StringIO(text or "")):
            symbol = (row.get("symbol") or "").strip()
            if symbol:
                names[symbol.lower()] = (row.get("name") or "").strip()
    return names


def parse_commodity_ids(*csv_texts: str) -> dict[int, str]:
    """FDevIDs → {id towaru z Market.json: symbol lowercase} (symbole = nazwy towarów w Ardent)."""
    ids = {}
    for text in csv_texts:
        for row in csv.DictReader(io.StringIO(text or "")):
            try:
                ids[int(row.get("id") or 0)] = (row.get("symbol") or "").strip().lower()
            except ValueError:
                continue
    ids.pop(0, None)
    return ids


def load_commodity_ids(cache_dir: Optional[Path] = None) -> dict[int, str]:
    texts = [fetch_cached(url, fn, cache_dir) for url, fn in
             ((FDEVIDS_COMMODITY_URL, "commodity.csv"), (FDEVIDS_RARE_URL, "rare_commodity.csv"))]
    return parse_commodity_ids(*(t for t in texts if t))


def load_commodity_names(cache_dir: Optional[Path] = None) -> dict[str, str]:
    texts = [fetch_cached(url, fn, cache_dir) for url, fn in
             ((FDEVIDS_COMMODITY_URL, "commodity.csv"), (FDEVIDS_RARE_URL, "rare_commodity.csv"))]
    return parse_commodity_names(*(t for t in texts if t))


def _norm(name: str) -> str:
    n = "".join(ch for ch in name.lower() if ch.isalnum())
    return n[:-1] if n.endswith("s") else n


def _parse_ts(value: str) -> Optional[datetime]:
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


class RouteChecklist:
    """Postęp na trasie: indeks hopu + stan kroków bieżącego hopu."""

    def __init__(
        self,
        route: TradeRoute,
        commodity_names: dict[str, str],
        cargo: Optional[list[dict]] = None,
        docked: tuple[str, str] = ("", ""),
        created_at: Optional[datetime] = None,
    ):
        self.route = route
        self.names = commodity_names
        self.hops: list[Hop] = list(route.hops_list or [])
        # Journal ma rozdzielczość sekundową — bez obcięcia zakup w tej samej sekundzie byłby "historią"
        self.created_at = (created_at or datetime.now(timezone.utc)).replace(microsecond=0)
        self.docked = (docked[0].lower(), docked[1].lower())
        self.hop_index = 0
        self.finished = not self.hops
        self.last_buy_ts: Optional[datetime] = None
        self._trip: Optional[tuple] = None  # (hop, zakup, dokowanie w celu) — do kalibracji tempa
        self._reset_steps()
        # Zakup często dzieje się, zanim Spansh policzy trasę (40-180 s) — startowy stan z ładowni
        if self.hop and cargo:
            self.bought = sum(int(c.get("Count") or 0) for c in cargo if self._matches(c.get("Name", "")))
        self._sync_route()

    def _reset_steps(self) -> None:
        self.last_buy_ts = None
        self.bought = 0
        self.arrived = False
        self.sold = 0

    @property
    def hop(self) -> Optional[Hop]:
        return None if self.finished else self.hops[self.hop_index]

    def _matches(self, journal_type: str) -> bool:
        if not self.hop or not journal_type:
            return False
        display = self.names.get(journal_type.lower())
        for target in self.hop.names:  # cały ładunek hopu, nie tylko główny towar
            if display and display.lower() == target.lower():
                return True
            if not display and _norm(journal_type) == _norm(target):
                return True
        return False

    def at_destination(self) -> bool:
        hop = self.hop
        return bool(hop) and self.docked == (hop.destination_system.lower(), hop.destination_station.lower())

    def follows_plan(self, system: str, station: str) -> bool:
        """Dokowanie w celu bieżącego hopu — trasy nie przeliczamy, gracz ją realizuje."""
        hop = self.hop
        return bool(hop) and (system.lower(), station.lower()) == (
            hop.destination_system.lower(), hop.destination_station.lower())

    def on_event(self, ev: dict) -> bool:
        """Zwraca True, gdy stan checklisty się zmienił. Eventy sprzed utworzenia trasy są ignorowane
        (catch-up journala przy starcie odtwarza historię)."""
        changed = self._apply(ev)
        if changed:
            self._sync_route()
        return changed

    def _apply(self, ev: dict) -> bool:
        if self.finished:
            return False
        ts = _parse_ts(ev.get("timestamp", ""))
        if ts is not None and ts < self.created_at:
            return False
        event = ev.get("event", "")
        if event == "Docked" or (event == "Location" and ev.get("Docked")):
            self.docked = (ev.get("StarSystem", "").lower(), ev.get("StationName", "").lower())
            if self.at_destination() and not self.arrived:
                self.arrived = True
                if self.last_buy_ts is not None and ts is not None:
                    self._trip = (self.hop, self.last_buy_ts, ts)
                if not self.hop.names:  # dolot bez ładunku — nie ma czego sprzedać
                    self._advance()
                return True
            return False
        if event == "MarketBuy" and self._matches(ev.get("Type", "")):
            self.bought += int(ev.get("Count") or 0)
            self.last_buy_ts = ts
            return True
        if event == "MarketSell" and self._matches(ev.get("Type", "")) and self.at_destination():
            self.arrived = True
            self.sold += int(ev.get("Count") or 0)
            if self.sold >= self.bought:
                self._advance()
            return True
        return False

    def pop_trip(self) -> Optional[tuple]:
        """Zakończony lot hopu (hop, czas zakupu, czas dokowania w celu) — raz, potem None."""
        trip, self._trip = self._trip, None
        return trip

    def _advance(self) -> None:
        self.hop_index += 1
        self._reset_steps()
        if self.hop_index >= len(self.hops):
            self.finished = True

    def _sync_route(self) -> None:
        """Overlay czyta route._current_hop (1-based) i route._checklist_text."""
        self.route._current_hop = min(self.hop_index + 1, max(len(self.hops), 1))
        self.route._checklist_text = self.status_text()

    def status_text(self) -> str:
        if self.finished:
            return "[✓ trasa ukończona]"
        hop = self.hop
        amount = hop.amount or 0
        if self.bought >= amount > 0:
            buy = f"✓ kup {self.bought}/{amount}"
        elif self.bought:
            buy = f"◐ kup {self.bought}/{amount}"
        else:
            buy = f"▶ kup {amount}" if amount else "▶ kup"
        if self.arrived:
            fly = "✓ leć"
        else:
            fly = "▶ leć" if self.bought else "○ leć"
        if self.sold:
            sell = f"◐ sprzedaj {self.sold}/{self.bought}"
        else:
            sell = "▶ sprzedaj" if self.arrived else "○ sprzedaj"
        return f"[{buy} · {fly} · {sell}]"
