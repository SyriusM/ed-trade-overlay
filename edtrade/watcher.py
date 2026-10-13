"""Journal watcher — śledzi żywy plik journala Elite Dangerous.

Wykrywa eventy Docked i Loadout, emituje callbacki.
Obsługuje rotację pliku (gra tworzy nowy przy każdym starcie).
"""

import glob
import json
import logging
import os
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Baza ścieżek Steam — sprawdzana kolejno

# Pola Cargo.json: event="Cargo", Inventory=[{"Name":"...", "Count":N, ...}]
_CARGO_FIELDS = ("Name", "Count", "Stolen")
_STEAM_ROOTS = [
    Path.home() / ".local" / "share" / "Steam",
    Path.home() / ".steam" / "steam",
    Path.home() / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
]

# Nazwa użytkownika Windows (Wine) — często "steamuser", czasem inna
_STEAM_USER = "steamuser"

# Końcówka ścieżki do Saved Games ED
_SAVED_GAMES_END = Path("Saved Games") / "Frontier Developments" / "Elite Dangerous"


def _find_journal_dir() -> Optional[Path]:
    """Znajdź katalog journala ED, sprawdzając kilka lokalizacji Steam.

    1. Próbuje znanej ścieżki z steamuser.
    2. Jeśli nie istnieje — szuka globem dowolnego użytkownika
       w compatdata/359320/pfx/drive_c/users/*/Saved Games/...
    """
    # 1) Znana ścieżka z steamuser
    for root in _STEAM_ROOTS:
        candidate = root / "steamapps" / "compatdata" / "359320" / "pfx" / "drive_c" / "users" / _STEAM_USER
        if (candidate / _SAVED_GAMES_END).is_dir():
            return candidate / _SAVED_GAMES_END

    # 2) Fallback glob — dowolna nazwa użytkownika
    for root in _STEAM_ROOTS:
        compat = root / "steamapps" / "compatdata" / "359320" / "pfx" / "drive_c" / "users"
        if not compat.is_dir():
            continue
        pattern = str(compat / "*/Saved Games/Frontier Developments/Elite Dangerous")
        matches = glob.glob(pattern)
        if matches:
            # Zwróć pierwszą (alphabetically pierwsza = najstarsza, ale to i tak fallback)
            return Path(matches[0])

    return None

# Pola interesujących nas eventów
INTERESTING_EVENTS = {"Docked", "Loadout", "StartedSession", "Location", "Cargo", "Market", "Materials", "MarketBuy", "MarketSell"}


class JournalWatcher:
    """Śledzi najnowszy plik journala ED i emituje eventy."""

    def __init__(
        self,
        journal_dir: Optional[Path] = None,
        on_docked: Optional[Callable] = None,
        on_loadout: Optional[Callable] = None,
        on_cargo: Optional[Callable] = None,
        on_location: Optional[Callable] = None,
        on_market: Optional[Callable] = None,
        on_materials: Optional[Callable] = None,
        on_trade: Optional[Callable] = None,
    ):
        self.journal_dir = journal_dir
        if self.journal_dir is None:
            self.journal_dir = _find_journal_dir()
        self.on_docked = on_docked
        self.on_loadout = on_loadout
        self.on_cargo = on_cargo
        self.on_location = on_location
        self.on_market = on_market
        self.on_materials = on_materials
        self.on_trade = on_trade
        self._latest_file: Optional[Path] = None
        self._file_pos: int = 0
        self._running = False
        self._player_cargo: list[dict] = []

    def _find_latest_journal(self) -> Optional[Path]:
        """Znajdź najnowszy plik journala wg mtime."""
        if not self.journal_dir or not self.journal_dir.is_dir():
            logger.warning("Katalog journala nie istnieje: %s", self.journal_dir)
            return None

        journals = sorted(
            self.journal_dir.glob("Journal.*.log"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not journals:
            logger.warning("Brak plików journala w %s", self.journal_dir)
            return None

        latest = journals[0]
        if self._latest_file != latest:
            logger.info("Wykryto nowy journal: %s", latest.name)
            self._latest_file = latest
            self._file_pos = 0  # reset pozycji przy rotacji
        return latest

    def _read_new_lines(self) -> list[dict]:
        """Odczytaj nowe linie z aktualnego pliku journala."""
        journal = self._find_latest_journal()
        if not journal or not journal.is_file():
            return []

        try:
            with open(journal, "r", encoding="utf-8") as f:
                f.seek(self._file_pos)
                lines = f.readlines()
                self._file_pos = f.tell()
        except (OSError, IOError) as e:
            logger.error("Błąd odczytu journala: %s", e)
            return []

        events = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Częściowo zapisana linia (gra dopisuje w locie) → JSONDecodeError → pomijamy
            try:
                data = json.loads(line)
                event_type = data.get("event", "")
                if event_type in INTERESTING_EVENTS:
                    events.append(data)
            except json.JSONDecodeError:
                continue

        return events

    def run(self, poll_interval: float = 1.0):
        """Główna pętla obserwatora.

        Blokuje do momentu przerwania (KeyboardInterrupt / stop()).
        """
        self._running = True
        logger.info("Watcher startuje, journal_dir=%s", self.journal_dir)

        # Początkowe przejście — wczytaj stare linie
        self._find_latest_journal()
        self._load_cargo_json()
        self._load_market_json()
        events = self._read_new_lines()
        self._dispatch(events)

        while self._running:
            try:
                time.sleep(poll_interval)
            except (KeyboardInterrupt, SystemExit):
                self._running = False
                break

            events = self._read_new_lines()
            if events:
                self._dispatch(events)

    def _dispatch(self, events: list[dict]):
        """Przekaż eventy do handlerów."""
        for ev in events:
            event_type = ev.get("event", "")
            # "Location" z Docked=true = dokowanie (gra nie wysyła osobnego "Docked")
            if event_type == "Location" and ev.get("Docked"):
                event_type = "Docked"
            if event_type == "Docked":
                logger.debug("Docked: %s/%s", ev.get("StarSystem"), ev.get("StationName"))
                if self.on_docked:
                    try:
                        self.on_docked(ev)
                    except Exception:
                        logger.exception("Błąd w on_docked")
            elif event_type == "Loadout":
                capacity = ev.get("CargoCapacity", ev.get("Capacity", 0))
                ship = ev.get("Ship", "unknown")
                logger.debug("Loadout: statek=%s, capacity=%.1f", ship, capacity)
                if self.on_loadout:
                    try:
                        self.on_loadout(ev)
                    except Exception:
                        logger.exception("Błąd w on_loadout")
            elif event_type == "Cargo":
                cargo_list = ev.get("Cargo", [])
                logger.debug("Cargo: %d pozycji", len(cargo_list))
                if self.on_cargo:
                    try:
                        self.on_cargo(ev)
                    except Exception:
                        logger.exception("Błąd w on_cargo")
            elif event_type == "Market":
                logger.debug("Market event: market_id=%d, station=%s/%s",
                            ev.get("MarketID"), ev.get("StarSystem"), ev.get("StationName"))
                if self.on_market:
                    try:
                        self.on_market(ev)
                    except Exception:
                        logger.exception("Błąd w on_market")
            elif event_type == "Materials":
                if self.on_materials:
                    try:
                        self.on_materials(ev)
                    except Exception:
                        logger.exception("Błąd w on_materials")
            elif event_type in ("MarketBuy", "MarketSell"):
                if self.on_trade:
                    try:
                        self.on_trade(ev)
                    except Exception:
                        logger.exception("Błąd w on_trade")
            elif event_type == "Location":
                system = ev.get("StarSystem", "")
                station = ev.get("Station", "")
                logger.debug("Location: %s%s", system, f"/{station}" if station else "")
                if self.on_location:
                    try:
                        self.on_location(ev)
                    except Exception:
                        logger.exception("Błąd w on_location")

    def _load_cargo_json(self) -> None:
        """Załaduj Cargo.json na start (analogicznie do skanowania journala).

        Plik może nie istnieć lub być niekompletny — bezpieczne pomijamy.
        """
        cargo_file = self.journal_dir / "Cargo.json"
        if not cargo_file.is_file():
            logger.debug("Cargo.json nie istnieje: %s", cargo_file)
            return

        try:
            with open(cargo_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            inventory = data.get("Inventory", [])
            logger.info("Cargo.json odczytany: %d pozycji", len(inventory))
            self._player_cargo = inventory
        except (json.JSONDecodeError, OSError, IOError) as e:
            logger.warning("Błąd odczytu Cargo.json: %s", e)

    def _load_market_json(self) -> None:
        """Załaduj Market.json na start (analogicznie do _load_cargo_json).

        Plik może nie istnieć lub być niekompletny — bezpieczne pomijamy.
        """
        market_file = self.journal_dir / "Market.json"
        if not market_file.is_file():
            logger.debug("Market.json nie istnieje: %s", market_file)
            return

        try:
            with open(market_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            market_id = data.get("MarketID")
            items_count = len(data.get("Items", []))
            logger.info("Market.json odczytany: market_id=%d, items=%d", market_id, items_count)
        except (json.JSONDecodeError, OSError, IOError) as e:
            logger.warning("Błąd odczytu Market.json: %s", e)

    def stop(self):
        """Zatrzymaj watchera."""
        self._running = False
