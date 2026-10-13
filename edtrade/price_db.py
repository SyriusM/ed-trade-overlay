"""Lokalna baza cen zasilana z EDDN (i z Twojego Market.json) — świeższa niż API, z historią.

Tabela `prices`: ostatnia znana cena towaru na rynku (klucz: market_id + towar).
Tabela `history`: zmiany cen (tylko gdy cena się zmieniła) — podstawa wykresów i trendów; 30 dni.
Nazwy towarów to symbole z gry, małymi literami (jak w Ardent / FDevIDs).
"""

import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_PATH = Path.home() / ".local" / "share" / "ed-trade-overlay" / "prices.db"
HISTORY_DAYS = 30


@dataclass
class PriceRecord:
    market_id: int
    system: str
    station: str
    commodity: str
    buy_price: int
    sell_price: int
    stock: int
    demand: int
    mean_price: int
    updated_at: float  # epoch s


def _epoch(value) -> float:
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return time.time()
    return (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).timestamp()


class PriceDB:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        with self._lock, self._conn:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS prices (
                    market_id INTEGER, system TEXT, station TEXT, commodity TEXT,
                    buy INTEGER, sell INTEGER, stock INTEGER, demand INTEGER, mean INTEGER, updated REAL,
                    PRIMARY KEY (market_id, commodity));
                CREATE INDEX IF NOT EXISTS prices_station ON prices (system COLLATE NOCASE, station COLLATE NOCASE);
                CREATE TABLE IF NOT EXISTS history (
                    market_id INTEGER, commodity TEXT, buy INTEGER, sell INTEGER, updated REAL);
                CREATE INDEX IF NOT EXISTS history_key ON history (market_id, commodity, updated);
            """)
            self._conn.execute("DELETE FROM history WHERE updated < ?", (time.time() - HISTORY_DAYS * 86400,))
        self.messages = 0  # ile rynków przyjęto w tej sesji (do statusu)

    def upsert_market(self, message: dict) -> int:
        """Komunikat EDDN commodity/3 (pole `message`) → baza. Zwraca liczbę zapisanych towarów.

        Starszy niż to, co już mamy dla tego rynku — pomijany (EDDN potrafi dostarczyć spóźnione dane).
        """
        market_id = int(message.get("marketId") or 0)
        system, station = message.get("systemName", ""), message.get("stationName", "")
        updated = _epoch(message.get("timestamp"))
        if not market_id or not system or not station:
            return 0
        rows = []
        for c in message.get("commodities") or []:
            name = str(c.get("name") or "").lower()
            if name:
                rows.append((market_id, system, station, name, int(c.get("buyPrice") or 0),
                             int(c.get("sellPrice") or 0), int(c.get("stock") or 0), int(c.get("demand") or 0),
                             int(c.get("meanPrice") or 0), updated))
        if not rows:
            return 0
        with self._lock, self._conn:
            newest = self._conn.execute("SELECT MAX(updated) FROM prices WHERE market_id = ?", (market_id,)).fetchone()[0]
            if newest is not None and newest >= updated:
                return 0
            old = {r[0]: (r[1], r[2]) for r in self._conn.execute(
                "SELECT commodity, buy, sell FROM prices WHERE market_id = ?", (market_id,))}
            self._conn.execute("DELETE FROM prices WHERE market_id = ?", (market_id,))  # towar zniknął = nie ma go
            self._conn.executemany("INSERT INTO prices VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            self._conn.executemany("INSERT INTO history VALUES (?,?,?,?,?)", [
                (market_id, r[3], r[4], r[5], updated) for r in rows if old.get(r[3]) != (r[4], r[5])])
        self.messages += 1
        return len(rows)

    def get(self, system: str, station: str, commodity: str) -> Optional[PriceRecord]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM prices WHERE system = ? COLLATE NOCASE AND station = ? COLLATE NOCASE AND commodity = ?",
                (system, station, commodity.lower())).fetchone()
        return PriceRecord(*row) if row else None

    def station_updated(self, system: str, station: str) -> Optional[float]:
        """Kiedy ostatnio widzieliśmy rynek stacji (None = nigdy)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(updated) FROM prices WHERE system = ? COLLATE NOCASE AND station = ? COLLATE NOCASE",
                (system, station)).fetchone()
        return row[0] if row else None

    def history(self, market_id: int, commodity: str) -> list[tuple[float, int, int]]:
        """[(epoch, kupno, sprzedaż)] od najstarszych."""
        with self._lock:
            return self._conn.execute("SELECT updated, buy, sell FROM history WHERE market_id = ? AND commodity = ? "
                                      "ORDER BY updated", (market_id, commodity.lower())).fetchall()

    def count(self) -> tuple[int, int]:
        with self._lock:
            markets = self._conn.execute("SELECT COUNT(DISTINCT market_id) FROM prices").fetchone()[0]
            rows = self._conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
        return markets, rows
