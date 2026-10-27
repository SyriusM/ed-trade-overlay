"""Podpowiedzi do pól panelu: towary, minerały, systemy i stacje — lista dopasowań po kilku literach.

Towary i minerały: lokalnie z EDCD FDevIDs (commodity.csv / rare_commodity.csv, w cache na dysku).
Systemy: Spansh /api/systems/field_values/system_names?q=… (min_max: [{name, id64, x, y, z}]).
Stacje: wszystkie stacje wybranego systemu (Ardent, jak strona System), filtrowane lokalnie.
"""

import csv
import io
import logging
import threading
from typing import Callable, Optional

import requests

from .materials import fetch_cached

logger = logging.getLogger(__name__)

SPANSH_SYSTEM_NAMES_URL = "https://spansh.co.uk/api/systems/field_values/system_names"
HEADERS = {"User-Agent": "EdTradeOverlay/0.1", "Accept": "application/json"}
FDEVIDS_COMMODITY_URL = "https://raw.githubusercontent.com/EDCD/FDevIDs/master/commodity.csv"
FDEVIDS_RARE_URL = "https://raw.githubusercontent.com/EDCD/FDevIDs/master/rare_commodity.csv"
MINERAL_CATEGORIES = frozenset({"Minerals", "Metals"})
EXTRA_MINERALS = ("Tritium",)  # kopalny, ale w FDevIDs kategoria Chemicals
LIMIT = 12


def filter_names(names, typed: str, limit: int = LIMIT) -> list[str]:
    """Dopasowania bez wielkości liter: najpierw początek nazwy, potem początek słowa, potem fragment."""
    typed = typed.strip().lower()
    unique = sorted(set(n for n in names if n), key=str.lower)
    if not typed:
        return unique[:limit]
    starts, words, inside = [], [], []
    for name in unique:
        low = name.lower()
        if low.startswith(typed):
            starts.append(name)
        elif any(word.startswith(typed) for word in low.split()):
            words.append(name)
        elif typed in low:
            inside.append(name)
    return (starts + words + inside)[:limit]


def parse_catalog(*csv_texts: str) -> tuple[list[str], list[str]]:
    """FDevIDs CSV → (wszystkie towary, minerały do kopania) — nazwy wyświetlane."""
    commodities, minerals = set(), set(EXTRA_MINERALS)
    for text in csv_texts:
        for row in csv.DictReader(io.StringIO(text or "")):
            name = (row.get("name") or "").strip()
            if not name or (row.get("category") or "") == "NonMarketable":
                continue
            commodities.add(name)
            if row.get("category") in MINERAL_CATEGORIES:
                minerals.add(name)
    return sorted(commodities), sorted(minerals & commodities)


class Catalog:
    """Listy towarów/minerałów ładowane raz w tle; do czasu załadowania — puste listy."""

    def __init__(self):
        self.commodities: list[str] = []
        self.minerals: list[str] = []
        self._lock = threading.Lock()
        self._loaded = False

    def load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            try:
                texts = [fetch_cached(url, fn) for url, fn in
                         ((FDEVIDS_COMMODITY_URL, "commodity.csv"), (FDEVIDS_RARE_URL, "rare_commodity.csv"))]
                self.commodities, self.minerals = parse_catalog(*(t for t in texts if t))
                self._loaded = bool(self.commodities)
            except Exception:
                logger.exception("Podpowiedzi: lista towarów")


def system_names(typed: str, limit: int = LIMIT) -> list[str]:
    """Systemy pasujące do wpisanego tekstu (sieć). Spansh zwraca je w swojej kolejności — sortujemy jak lokalne."""
    if len(typed.strip()) < 2:
        return []
    resp = requests.get(SPANSH_SYSTEM_NAMES_URL, params={"q": typed.strip()}, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    names = [s.get("name", "") for s in resp.json().get("min_max") or [] if s.get("name")]
    return merge_remote(names, typed, limit)


def merge_remote(names: list[str], typed: str, limit: int = LIMIT) -> list[str]:
    """Wyniki z sieci są dopasowane luźno: pasujące tekstowo na górę, reszta w kolejności serwera (nie znika)."""
    matched = filter_names(names, typed, limit)
    seen = {n.lower() for n in matched}
    rest = [n for n in names if n.lower() not in seen and not seen.add(n.lower())]
    return (matched + rest)[:limit]


class StationNames:
    """Stacje systemu, wybieranego w sąsiednim polu: pobrane raz na system (cache), filtrowane lokalnie."""

    def __init__(self, fetch: Callable[[str], list]):
        self._fetch = fetch
        self._cache: dict[str, list[str]] = {}

    def __call__(self, system: str, typed: str, limit: int = LIMIT) -> list[str]:
        key = system.strip().lower()
        if not key:
            return []
        if key not in self._cache:
            self._cache[key] = [getattr(s, "name", "") or "" for s in self._fetch(system.strip())]
        return filter_names(self._cache[key], typed, limit)


def recent_first(recent: Optional[list[str]], found: list[str], typed: str, limit: int = LIMIT) -> list[str]:
    """Ostatnio używane (np. bieżący system) pasujące do tekstu — na górze listy, bez duplikatów."""
    top = filter_names(recent or [], typed, limit)
    return (top + [n for n in found if n.lower() not in {t.lower() for t in top}])[:limit]
