"""Karta stacji docelowej (jak prawa kolumna Trade Overview w TCE) — dane do dolnego paska.

Źródło: Spansh /api/system/<id64> (typ stacji, pady, odległość od gwiazdy, usługi, frakcja i jej
stany, bezpieczeństwo). Wiek danych rynku przychodzi z wyniku trasy Spansh (market_updated_at celu).
Gdy trasa nie podała id64 systemu, bierzemy systemAddress z Ardent /v2/system/name/<system>.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import requests

logger = logging.getLogger(__name__)

SPANSH_SYSTEM_URL = "https://spansh.co.uk/api/system/{id64}"
ARDENT_SYSTEM_URL = "https://api.ardent-insight.com/v2/system/name/{system}"
HEADERS = {"User-Agent": "EdTradeOverlay/0.1", "Accept": "application/json"}

# Usługi warte pokazania w karcie: nazwa w "services" Spansh → etykieta na pasku
SERVICES = (
    ("Refuel", "paliwo"),
    ("Repair", "naprawa"),
    ("Restock", "amunicja"),
    ("Outfitting", "outfitting"),
    ("Shipyard", "stocznia"),
    ("Material Trader", "handlarz mat."),
    ("Technology Broker", "broker tech."),
    ("Black Market", "czarny rynek"),
)

# Lockdown zamyka większość usług stacji; pozostałe stany tylko ostrzegamy
LOCKDOWN_STATES = frozenset({"Lockdown"})
WARNING_STATES = frozenset({"Civil Unrest", "War", "Civil War", "Infrastructure Failure", "Terrorist Attack"})


@dataclass
class DestinationInfo:
    """Wszystko, co dolny pasek pokazuje o stacji docelowej bieżącego hopu."""
    system: str = ""
    station: str = ""
    station_type: str = ""
    pad: str = ""                 # L / M / S / "" (brak danych)
    distance_ls: Optional[float] = None
    distance_ly: Optional[float] = None
    market_updated_ts: float = 0.0
    faction: str = ""
    faction_states: list[str] = field(default_factory=list)
    security: str = ""
    services: list[str] = field(default_factory=list)  # etykiety z SERVICES
    error: str = ""

    @property
    def lockdown(self) -> bool:
        return any(s in LOCKDOWN_STATES for s in self.faction_states)

    @property
    def warnings(self) -> list[str]:
        return [s for s in self.faction_states if s in WARNING_STATES]


def _pad(station: dict) -> str:
    if station.get("has_large_pad") or station.get("large_pads"):
        return "L"
    if station.get("medium_pads"):
        return "M"
    if station.get("small_pads"):
        return "S"
    return ""


def _faction_states(record: dict, faction: str) -> list[str]:
    """Aktywne stany frakcji kontrolującej stację (Spansh: state + active_states w minor_faction_presences)."""
    states: list[str] = []
    for presence in record.get("minor_faction_presences") or []:
        if presence.get("name") != faction:
            continue
        for state in [presence.get("state")] + list(presence.get("active_states") or []):
            if state and state != "None" and state not in states:
                states.append(state)
    return states


def parse_spansh_system(record: dict, station_name: str) -> DestinationInfo:
    """Wyciągnij kartę stacji z rekordu systemu Spansh (bez sieci — testowalne na próbkach)."""
    info = DestinationInfo(system=record.get("name", ""), station=station_name,
                           security=record.get("security") or "")
    wanted = station_name.strip().lower()
    station = next((s for s in record.get("stations") or [] if (s.get("name") or "").lower() == wanted), None)
    if station is None:
        info.error = "station not found"
        return info
    info.station = station.get("name", station_name)
    info.station_type = station.get("type") or ""
    info.pad = _pad(station)
    info.distance_ls = station.get("distance_to_arrival")
    info.faction = station.get("controlling_minor_faction") or ""
    info.faction_states = _faction_states(record, info.faction)
    if not info.faction_states:
        state = station.get("controlling_minor_faction_state")
        if state and state != "None":
            info.faction_states = [state]
    offered = set(station.get("services") or [])
    info.services = [label for name, label in SERVICES if name in offered]
    return info


def _system_id64(system: str) -> str:
    resp = requests.get(ARDENT_SYSTEM_URL.format(system=requests.utils.quote(system)), headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return str(resp.json().get("systemAddress") or "")


def to_timestamp(value) -> float:
    """market_updated_at ze Spansh: liczba (unix) albo tekst ISO 8601 → sekundy unix (0 = brak)."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        from datetime import datetime
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def get_destination_info(system: str, station: str, system_id64: str = "",
                         distance_ly: Optional[float] = None, market_updated_ts: float = 0.0) -> DestinationInfo:
    """Pobierz kartę stacji docelowej (sieć — wołać z wątku roboczego)."""
    try:
        id64 = str(system_id64 or "") or _system_id64(system)
        if not id64:
            raise ValueError(f"no id64 for {system}")
        resp = requests.get(SPANSH_SYSTEM_URL.format(id64=id64), headers=HEADERS, timeout=20)
        resp.raise_for_status()
        info = parse_spansh_system(resp.json().get("record") or {}, station)
    except Exception as e:
        logger.error("Karta stacji %s/%s: %s", system, station, e)
        info = DestinationInfo(error=str(e))
    info.system = info.system or system
    info.station = info.station or station
    info.distance_ly = distance_ly
    info.market_updated_ts = to_timestamp(market_updated_ts)
    return info
