"""Eksploracja Guardian: najbliższe ruiny i struktury z artefaktami i blueprintami.

Źródło: Spansh /api/bodies/search — ciała z sygnałem "Guardian" (z FSS/DSS graczy), posortowane wg
odległości od Twojego systemu. Każde ciało ma `landmarks` z Codexu (prawdziwe próbki: test_data/
spansh_guardian_bodies.json):
  type "Guardian Ruin"      subtype "Unknown"                       — ruiny (artefakty, dane obelisków)
  type "Guardian Structure" subtype Bear/Bowl/Turtle/Lacrosse/…/"Unknown" — struktury (blueprinty)
  type "Guardian"           subtype "Guardian Relic Tower" / "Guardian Sentinel" / "Guardian Data Terminal" /
                                    "Guardian Pylon" / "Guardian Beacon" / "Guardian Codex" — obiekty na miejscu
Spansh nie rozróżnia typów ruin (Alpha/Beta/Gamma) — subtype ruin to zawsze "Unknown".

Co daje który typ struktury — z przewodników społeczności (Canonn); Spansh tego nie podaje.
"""

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import requests

logger = logging.getLogger(__name__)

SPANSH_BODIES_URL = "https://spansh.co.uk/api/bodies/search"
HEADERS = {"User-Agent": "EdTradeOverlay/0.1", "Accept": "application/json"}

RUINS = "ruins"
STRUCTURE = "structure"

# Typ struktury → rodzaj blueprintów (Canonn)
BLUEPRINT_KIND = {
    "Bear": "module", "Bowl": "module", "Turtle": "module",
    "Crossroads": "weapon", "Fistbump": "weapon", "Hammerbot": "weapon", "Lacrosse": "weapon",
    "Robolobster": "vessel", "Squid": "vessel", "Stickyhand": "vessel",
}
BLUEPRINT_LABELS = {"module": "blueprint modułów", "weapon": "blueprint broni", "vessel": "blueprint myśliwców"}
RUINS_REWARDS = "artefakty: Casket, Orb, Relic, Tablet, Totem, Urn · dane obelisków · Sentinel Weapon Parts"
STRUCTURE_REWARDS = "Power Cell, Power Conduit, Technology Component"

# Obiekty na miejscu (type "Guardian"): subtype → krótka etykieta; Codex pomijamy (to tylko wpis dziennika)
FEATURE_LABELS = {
    "Guardian Relic Tower": "wieża reliktu",
    "Guardian Sentinel": "Sentinel",
    "Guardian Data Terminal": "terminal danych",
    "Guardian Pylon": "pylon",
    "Guardian Beacon": "beacon",
}

# Filtr strony: klucz → (etykieta, warunek na GuardianBody)
FILTERS = {
    "all": "Wszystko",
    RUINS: "Ruiny (artefakty)",
    STRUCTURE: "Struktury (blueprinty)",
    "weapon": "Blueprint broni",
    "module": "Blueprint modułów",
    "vessel": "Blueprint myśliwców",
}


@dataclass
class GuardianSite:
    kind: str            # RUINS / STRUCTURE
    subtype: str         # typ struktury (Bear, Lacrosse…) albo "" gdy nieznany
    latitude: float
    longitude: float

    @property
    def blueprint(self) -> str:
        return BLUEPRINT_KIND.get(self.subtype, "")

    @property
    def label(self) -> str:
        if self.kind == RUINS:
            return "Ruiny"
        return f"Struktura {self.subtype}" if self.subtype else "Struktura (typ ?)"

    @property
    def coords(self) -> str:
        return f"{self.latitude:.4f}, {self.longitude:.4f}"


@dataclass
class GuardianBody:
    system: str
    body: str
    system_id64: int = 0
    distance_ly: float = 0.0
    distance_ls: float = 0.0
    gravity: float = 0.0
    landable: bool = False
    signals: int = 0                                    # liczba sygnałów Guardian z FSS
    sites: list[GuardianSite] = field(default_factory=list)
    features: Counter = field(default_factory=Counter)  # etykieta z FEATURE_LABELS → ile

    @property
    def kinds(self) -> set[str]:
        return {s.kind for s in self.sites}

    @property
    def blueprints(self) -> set[str]:
        return {s.blueprint for s in self.sites if s.blueprint}

    def matches(self, key: str) -> bool:
        if key in ("", "all"):
            return True
        if key in (RUINS, STRUCTURE):
            return key in self.kinds
        return key in self.blueprints

    @property
    def summary(self) -> str:
        """Co tu jest: "Ruiny ×2 · Struktura Lacrosse" (bez danych z Codexu: "sygnał Guardian ×N")."""
        if not self.sites:
            return f"sygnał Guardian ×{self.signals}" if self.signals else "sygnał Guardian"
        counts = Counter(s.label for s in self.sites)
        return " · ".join(f"{label} ×{n}" if n > 1 else label for label, n in counts.items())

    @property
    def rewards(self) -> str:
        parts = []
        if RUINS in self.kinds:
            parts.append(RUINS_REWARDS)
        if STRUCTURE in self.kinds:
            blueprints = ", ".join(BLUEPRINT_LABELS[k] for k in sorted(self.blueprints))
            parts.append(STRUCTURE_REWARDS + (f" · {blueprints}" if blueprints else ""))
        return " | ".join(parts) or "nieznane — brak wpisów Codexu"

    @property
    def rewards_short(self) -> str:
        """Do tabeli: "artefakty · blueprint broni" (pełny opis w `rewards`)."""
        parts = ["artefakty + dane"] if RUINS in self.kinds else []
        parts += [BLUEPRINT_LABELS[k] for k in sorted(self.blueprints)]
        if STRUCTURE in self.kinds and not self.blueprints:
            parts.append("części Guardian (typ struktury ?)")
        return " · ".join(parts) or "?"

    @property
    def features_text(self) -> str:
        return " · ".join(f"{label} ×{n}" for label, n in self.features.most_common())


def parse_body(record: dict) -> GuardianBody:
    """Rekord ciała z wyszukiwarki Spansh → GuardianBody (bez sieci — testowalne na próbkach)."""
    body = GuardianBody(
        system=record.get("system_name") or "",
        body=record.get("name") or "",
        system_id64=int(record.get("system_id64") or 0),
        distance_ly=float(record.get("distance") or 0.0),
        distance_ls=float(record.get("distance_to_arrival") or 0.0),
        gravity=float(record.get("gravity") or 0.0),
        landable=bool(record.get("is_landable")),
        signals=sum(int(s.get("count") or 0) for s in record.get("signals") or [] if s.get("name") == "Guardian"),
    )
    seen = set()
    for mark in record.get("landmarks") or []:
        kind_name, subtype = mark.get("type") or "", mark.get("subtype") or ""
        lat, lon = mark.get("latitude"), mark.get("longitude")
        if kind_name == "Guardian" and subtype in FEATURE_LABELS:
            body.features[FEATURE_LABELS[subtype]] += 1
            continue
        kind = {"Guardian Ruin": RUINS, "Guardian Structure": STRUCTURE}.get(kind_name)
        if kind is None or lat is None or lon is None:
            continue
        key = (kind, subtype, round(float(lat), 2), round(float(lon), 2))  # ten sam punkt zgłoszony kilka razy
        if key in seen:
            continue
        seen.add(key)
        body.sites.append(GuardianSite(kind, "" if subtype == "Unknown" else subtype, float(lat), float(lon)))
    return body


def search_guardian_sites(reference_system: str, kind: str = "all", limit: int = 40,
                          max_pages: int = 4, page_size: int = 100) -> list[GuardianBody]:
    """Najbliższe ciała z obiektami Guardian (sieć — wołać z wątku roboczego). Filtr `kind` z FILTERS."""
    found: list[GuardianBody] = []
    for page in range(max_pages):
        payload = {
            "filters": {"signals": [{"name": "Guardian", "comparison": "<=>", "value": [1, 9999]}]},
            "sort": [{"distance": {"direction": "asc"}}],
            "size": page_size, "page": page, "reference_system": reference_system,
        }
        resp = requests.post(SPANSH_BODIES_URL, json=payload, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        results = resp.json().get("results") or []
        found.extend(b for b in map(parse_body, results) if b.matches(kind))
        if len(found) >= limit or len(results) < page_size:
            break
    return found[:limit]
