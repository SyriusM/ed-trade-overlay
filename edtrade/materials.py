"""Tracker materiałów inżynieryjnych: co gracz ma (event Materials) vs wymagania blueprintów.

Dane pobierane w runtime i cache'owane lokalnie (blueprints.json to dane Frontier — nie commitujemy):
- EDCD/FDevIDs material.csv — mapowanie symbolu z journala na nazwę/typ/rarity,
- EDCD/coriolis-data blueprints.json — składniki każdego grade'u blueprintu.
"""

import csv
import io
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

FDEVIDS_MATERIALS_URL = "https://raw.githubusercontent.com/EDCD/FDevIDs/master/material.csv"
BLUEPRINTS_URL = "https://raw.githubusercontent.com/EDCD/coriolis-data/master/modifications/blueprints.json"
DEFAULT_CACHE_DIR = Path.home() / ".local" / "share" / "ed-trade-overlay"
CACHE_MAX_AGE_S = 7 * 24 * 3600

# Pojemność magazynu wg rarity — potwierdzone na journalu usera (Carbon 300, Shield Emitters 250,
# Focus Crystals 200, Compound Shielding 150).
STORAGE_CAP = {1: 300, 2: 250, 3: 200, 4: 150, 5: 100}

MATERIAL_TYPES = ("Raw", "Manufactured", "Encoded")


@dataclass
class MaterialInfo:
    symbol: str = ""
    name: str = ""
    type: str = ""
    rarity: int = 0

    @property
    def cap(self) -> int:
        return STORAGE_CAP.get(self.rarity, 0)


@dataclass
class Blueprint:
    key: str = ""
    name: str = ""
    module: str = ""
    grades: dict[int, dict[str, int]] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.module}: {self.name}" if self.module else self.name


@dataclass
class Need:
    name: str = ""
    type: str = "?"
    rarity: int = 0
    need: int = 0
    have: int = 0

    @property
    def missing(self) -> int:
        return max(0, self.need - self.have)


def fetch_cached(url: str, filename: str, cache_dir: Optional[Path] = None) -> Optional[str]:
    """Świeży cache (<7 dni) → z dysku; inaczej pobierz i zapisz; błąd sieci → stary cache albo None."""
    path = (cache_dir or DEFAULT_CACHE_DIR) / filename
    if path.is_file() and time.time() - path.stat().st_mtime < CACHE_MAX_AGE_S:
        return path.read_text(encoding="utf-8")
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "EdTradeOverlay/0.1"})
        resp.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(resp.text, encoding="utf-8")
        return resp.text
    except Exception as e:
        logger.error("Pobieranie %s nie powiodło się: %s", url, e)
        return path.read_text(encoding="utf-8") if path.is_file() else None


def parse_material_table(text: str) -> dict[str, MaterialInfo]:
    """material.csv (id,symbol,rarity,type,category,name) → {symbol lowercase: MaterialInfo}."""
    table = {}
    for row in csv.DictReader(io.StringIO(text)):
        symbol = (row.get("symbol") or "").strip()
        if not symbol:
            continue
        try:
            rarity = int(row.get("rarity") or 0)
        except ValueError:
            rarity = 0
        table[symbol.lower()] = MaterialInfo(
            symbol=symbol, name=(row.get("name") or "").strip(), type=(row.get("type") or "").strip(), rarity=rarity,
        )
    return table


def parse_blueprints(text: str) -> dict[str, Blueprint]:
    """blueprints.json (coriolis-data) → {klucz: Blueprint}."""
    result = {}
    for key, raw in json.loads(text).items():
        modules = raw.get("modulename") or []
        grades = {}
        for grade, data in (raw.get("grades") or {}).items():
            try:
                grades[int(grade)] = {name.strip(): int(n) for name, n in (data.get("components") or {}).items()}
            except (TypeError, ValueError):
                continue
        result[key] = Blueprint(key=key, name=raw.get("name", key), module=modules[0] if modules else "", grades=grades)
    return result


def load_material_table(cache_dir: Optional[Path] = None) -> dict[str, MaterialInfo]:
    text = fetch_cached(FDEVIDS_MATERIALS_URL, "material.csv", cache_dir)
    return parse_material_table(text) if text else {}


def load_blueprints(cache_dir: Optional[Path] = None) -> dict[str, Blueprint]:
    text = fetch_cached(BLUEPRINTS_URL, "blueprints.json", cache_dir)
    try:
        return parse_blueprints(text) if text else {}
    except (json.JSONDecodeError, AttributeError) as e:
        logger.error("Nieczytelny blueprints.json: %s", e)
        return {}


def parse_materials_event(event: dict) -> dict[str, int]:
    """Event Materials → {symbol lowercase: ilość}. Mapujemy po Name (symbol), nie po Name_Localised (język klienta)."""
    inventory = {}
    for kind in MATERIAL_TYPES:
        for item in event.get(kind) or []:
            name = (item.get("Name") or "").lower()
            if name:
                inventory[name] = inventory.get(name, 0) + int(item.get("Count") or 0)
    return inventory


def requirements(bp: Blueprint, grade_from: int, grade_to: int, rolls_per_grade: int) -> dict[str, int]:
    """Suma składników dla grade'ów grade_from..grade_to, każdy grade × rolls_per_grade."""
    total: dict[str, int] = {}
    for grade in range(grade_from, grade_to + 1):
        for name, n in bp.grades.get(grade, {}).items():
            total[name] = total.get(name, 0) + n * rolls_per_grade
    return total


def missing_for(
    bp: Blueprint,
    grade_from: int,
    grade_to: int,
    rolls_per_grade: int,
    inventory: dict[str, int],
    table: dict[str, MaterialInfo],
) -> list[Need]:
    """Potrzebne vs posiadane; najpierw braki (malejąco), potem reszta alfabetycznie."""
    by_name = {info.name.lower(): info for info in table.values()}
    needs = []
    for name, need in requirements(bp, grade_from, grade_to, rolls_per_grade).items():
        info = by_name.get(name.lower())
        if info is None:
            needs.append(Need(name=name, need=need))
            continue
        needs.append(Need(name=info.name, type=info.type, rarity=info.rarity, need=need,
                          have=inventory.get(info.symbol.lower(), 0)))
    needs.sort(key=lambda n: (-n.missing, n.name))
    return needs
