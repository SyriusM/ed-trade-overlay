"""Trade engine — wrapper nad Trade Dangerous CLI + Spansh API.

Paruje dane z journala (system/stacja) w wywołanie `trade run`
i parsuje wynik do struktury Python.
"""

import json
import logging
import math
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import requests
from typing import Any

logger = logging.getLogger(__name__)

SPANSH_SEARCH_URL = "https://spansh.co.uk/search/{query}"
SPANSH_STATION_ID_RE = re.compile(
    r'href="/station/(\d+)">',
)

# --- Ardent API (wyszukiwarka stacji) ---
ARDENT_API_BASE = "https://api.ardent-insight.com/v2/system/name"

# --- Material Trader API (Spansh) ---
MATERIAL_TRADER_URL = "https://spansh.co.uk/api/stations/search"
MATERIAL_BODY_URL = "https://spansh.co.uk/api/bodies/search"


@dataclass
class MaterialTrader:
    """Handlarz materiałów / broker technologii (stacja, Spansh)."""
    name: str = ""
    system_name: str = ""
    distance: float = 0.0
    material_trader: str = ""
    technology_broker: str = ""
    distance_to_arrival: float = 0.0
    large_pads: int = 0
    medium_pads: int = 0


@dataclass
class MaterialBody:
    """Lądowalne ciało z danym materiałem (Spansh)."""
    name: str = ""
    system_name: str = ""
    distance: float = 0.0
    distance_to_arrival: float = 0.0
    gravity: float = 0.0
    is_landable: bool = False
    share: float = 0.0


@dataclass
class MiningHotspot:
    """Górny pierścień z minerałem (Spansh)."""
    system_name: str = ""
    body_name: str = ""
    ring_name: str = ""
    ring_type: str = ""
    count: int = 0
    distance: float = 0.0
    distance_to_arrival: float = 0.0
    updated_at: str = ""


@dataclass
class MineralBuyer:
    """Stacja kupująca minerał (Ardent)."""
    station_name: str = ""
    system_name: str = ""
    demand: int = 0
    sell_price: int = 0
    pad_size: str = ""
    distance: float = 0.0
    distance_to_arrival: float = 0.0
    updated_at: str = ""
    station_type: str = ""


@dataclass
class CommoditySeller:
    """Stacja sprzedająca towar (Ardent)."""
    station_name: str = ""
    system_name: str = ""
    stock: int = 0
    buy_price: int = 0
    pad_size: str = ""
    distance: float = 0.0
    distance_to_arrival: float = 0.0
    updated_at: str = ""
    station_type: str = ""


_ARDENT_COMMODITIES: list[dict] = []


def _ardent_commodity_names() -> list[dict]:
    """Lista towarów z Ardent (pobierana raz; błąd sieci nie jest cache'owany)."""
    if not _ARDENT_COMMODITIES:
        try:
            resp = requests.get(
                "https://api.ardent-insight.com/v2/commodities",
                timeout=30,
                headers={"User-Agent": "EdTradeOverlay/0.1"},
            )
            resp.raise_for_status()
            _ARDENT_COMMODITIES.extend(resp.json())
        except Exception as e:
            logger.error("Ardent commodities request failed: %s", e)
    return _ARDENT_COMMODITIES


def _norm_commodity(name: str) -> str:
    n = "".join(ch for ch in name.lower() if ch.isalnum())
    return n[:-1] if n.endswith("s") else n


def _ardent_commodity_name(mineral: str) -> str:
    """Kanoniczna nazwa towaru w Ardent dla nazwy ze Spansh/gry (fallback: lowercase)."""
    target = _norm_commodity(mineral)
    matches = [
        c.get("commodityName", "")
        for c in _ardent_commodity_names()
        if _norm_commodity(c.get("commodityName", "")) == target
    ]
    # Ardent ma duplikaty ("cmm composite" puste vs "cmmcomposite" z danymi) — wariant bez spacji ma dane
    for name in matches:
        if name == "".join(ch for ch in name if ch.isalnum()):
            return name
    return matches[0] if matches else mineral.lower()


def _spansh_search(url: str, payload: dict) -> list:
    """POST JSON do Spansh search; zwraca results[] albo [] przy błędzie."""
    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"User-Agent": "EdTradeOverlay/0.1", "Accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except Exception as e:
        logger.error("Spansh search %s failed: %s", url, e)
        return []
    return results if isinstance(results, list) else []


def find_material_traders(
    reference_system: str,
    kind: str,
    max_ly: float = 50.0,
    size: int = 10,
) -> list[MaterialTrader]:
    """Handlarze materiałów typu kind (Raw/Encoded/Manufactured) w promieniu max_ly."""
    payload = {
        "filters": {
            "services": [{"name": "Material Trader"}],
            "material_trader": {"value": [kind]},
            "distance": {"min": 0, "max": max_ly},
        },
        "reference_system": reference_system,
        "size": size,
    }
    traders = [
        MaterialTrader(
            name=r.get("name", ""),
            system_name=r.get("system_name", ""),
            distance=r.get("distance") or 0.0,
            material_trader=r.get("material_trader") or "",
            technology_broker=r.get("technology_broker") or "",
            distance_to_arrival=r.get("distance_to_arrival") or 0.0,
            large_pads=r.get("large_pads") or 0,
            medium_pads=r.get("medium_pads") or 0,
        )
        for r in _spansh_search(MATERIAL_TRADER_URL, payload)
    ]
    logger.info("find_material_traders: %d wyników (%s, %s)", len(traders), reference_system, kind)
    return traders


def find_material_bodies(
    reference_system: str,
    material: str,
    max_ly: float = 50.0,
    min_share: float = 0.0,
    max_gravity: float = 0.5,
    size: int = 10,
) -> list[MaterialBody]:
    """Lądowalne ciała z materiałem, malejąco po share (Spansh nie sortuje po share — robimy to lokalnie)."""
    payload = {
        "filters": {
            "is_landable": {"value": True},
            "gravity": {"comparison": "<=>", "value": [0, max_gravity]},
            "materials": [{"name": material, "comparison": "<=>", "value": [1, 100]}],
            "distance": {"min": 0, "max": max_ly},
        },
        "reference_system": reference_system,
        "size": max(size, 100),
    }
    bodies = []
    for r in _spansh_search(MATERIAL_BODY_URL, payload):
        share = next((m.get("share", 0.0) for m in r.get("materials", []) if m.get("name") == material), 0.0)
        if share < min_share:
            continue
        bodies.append(MaterialBody(
            name=r.get("name", ""),
            system_name=r.get("system_name", ""),
            distance=r.get("distance") or 0.0,
            distance_to_arrival=r.get("distance_to_arrival") or 0.0,
            gravity=r.get("gravity") or 0.0,
            is_landable=bool(r.get("is_landable")),
            share=share,
        ))
    bodies.sort(key=lambda b: b.share, reverse=True)
    logger.info("find_material_bodies: %d ciał z %s (%s)", len(bodies), material, reference_system)
    return bodies[:size]


def find_mining_hotspots(
    reference_system: str,
    mineral: str,
    max_ly: float = 50.0,
    min_count: int = 1,
    size: int = 10,
) -> list[MiningHotspot]:
    """Znajdź hotspoty górnicze (pierścienie z minerałem)."""
    payload = {
        "filters": {
            "ring_signals": [{"name": mineral, "comparison": "<=>", "value": [1, 100]}],
            "distance": {"min": 0, "max": max_ly},
        },
        "reference_system": reference_system,
        "size": 100,
    }
    hotspots: list[MiningHotspot] = []
    for r in _spansh_search(MATERIAL_BODY_URL, payload):
        rings = r.get("rings", [])
        for ring in rings:
            signals = ring.get("signals", [])
            for signal in signals:
                if signal.get("name", "").lower() == mineral.lower() and signal.get("count", 0) >= min_count:
                    distance = r.get("distance") or 0.0
                    dist_arrival = r.get("distance_to_arrival") or 0.0
                    hotspots.append(MiningHotspot(
                        system_name=r.get("system_name", ""),
                        body_name=r.get("name", ""),
                        ring_name=ring.get("name", ""),
                        ring_type=ring.get("type", ""),
                        count=signal.get("count", 0),
                        distance=distance,
                        distance_to_arrival=dist_arrival,
                        updated_at=ring.get("signals_updated_at") or "",
                    ))
    # Sortuj: count malejąco, potem distance_to_arrival rosnąco
    hotspots.sort(key=lambda h: (-h.count, h.distance_to_arrival))
    logger.info("find_mining_hotspots: %d hotspotów z %s (%s)", len(hotspots), mineral, reference_system)
    return hotspots[:size]


PAD_SIZE_MAP = {1: "small", 2: "medium", 3: "large"}


BUYER_CACHE_TTL_S = 600  # 10 min — ceny w Ardent i tak zmieniają się wolniej; przełączanie stron bez sieci
_buyer_cache: dict[tuple, tuple[float, list]] = {}
_buyer_cache_lock = threading.Lock()


def clear_buyer_cache() -> None:
    with _buyer_cache_lock:
        _buyer_cache.clear()


def find_mineral_buyers(
    mineral: str,
    reference_system: str,
    max_ly: float = 60.0,
    min_demand: int = 100,
    max_days: int = 7,
    size: int = 10,
) -> list["MineralBuyer"]:
    """Kupcy towaru w okolicy (Ardent /imports) z pamięcią podręczną na 10 min.

    Puste wyniki nie są zapamiętywane (mogą być błędem sieci — następne wywołanie spróbuje znowu).
    """
    key = (mineral.lower(), reference_system.lower(), float(max_ly), int(min_demand), int(max_days), int(size))
    now = time.time()
    with _buyer_cache_lock:
        hit = _buyer_cache.get(key)
        if hit is not None and now - hit[0] < BUYER_CACHE_TTL_S:
            return list(hit[1])
    buyers = _find_mineral_buyers_uncached(mineral, reference_system, max_ly, min_demand, max_days, size)
    if buyers:
        with _buyer_cache_lock:
            _buyer_cache[key] = (now, list(buyers))
    return buyers


def _find_mineral_buyers_uncached(
    mineral: str,
    reference_system: str,
    max_ly: float = 60.0,
    min_demand: int = 100,
    max_days: int = 7,
    size: int = 10,
) -> list[MineralBuyer]:
    """Znajdź kupców minerału (Ardent API /imports)."""
    # a) Znormalizowana nazwa towaru
    commodity_name = _ardent_commodity_name(mineral)

    url = f"https://api.ardent-insight.com/v2/commodity/name/{commodity_name}/imports"
    params = {
        "maxDaysAgo": max_days,
        "fleetCarriers": 0,
        "minVolume": min_demand,
        "systemName": reference_system,
        "maxDistance": max_ly,
    }
    headers = {"User-Agent": "EdTradeOverlay/0.1"}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        buyers = resp.json()
    except Exception as e:
        logger.error("Ardent imports request failed: %s", e)
        return []

    if not isinstance(buyers, list):
        logger.error("Ardent imports: oczekiwano listy, otrzymano %s", type(buyers).__name__)
        return []

    result: list[MineralBuyer] = []
    for b in buyers:
        demand = b.get("demand") or 0
        if demand < min_demand:
            continue

        pad_raw = b.get("maxLandingPadSize", 0)
        pad_size = PAD_SIZE_MAP.get(pad_raw, "")

        distance = b.get("distance") or 0.0
        dist_arrival = b.get("distanceToArrival") or 0.0

        result.append(MineralBuyer(
            station_name=b.get("stationName", ""),
            system_name=b.get("systemName", ""),
            demand=demand,
            sell_price=b.get("sellPrice") or 0,
            pad_size=pad_size,
            distance=distance,
            distance_to_arrival=dist_arrival,
            updated_at=b.get("updatedAt") or "",
            station_type=b.get("stationType") or "",
        ))

    # Sortuj: sell_price malejąco
    result.sort(key=lambda x: x.sell_price, reverse=True)
    logger.info("find_mineral_buyers: %d kupców z %s (%s)", len(result), mineral, reference_system)
    return result[:size]


def find_commodity_sellers(
    commodity: str,
    reference_system: str,
    max_ly: float = 60.0,
    min_stock: int = 500,
    max_days: int = 7,
    size: int = 10,
) -> list[CommoditySeller]:
    """Znajdź sprzedawców towaru (Ardent API /exports)."""
    # a) Znormalizowana nazwa towaru
    commodity_name = _ardent_commodity_name(commodity)

    url = f"https://api.ardent-insight.com/v2/commodity/name/{commodity_name}/exports"
    params = {
        "maxDaysAgo": max_days,
        "fleetCarriers": 0,
        "minVolume": min_stock,
        "systemName": reference_system,
        "maxDistance": max_ly,
    }
    headers = {"User-Agent": "EdTradeOverlay/0.1"}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        sellers = resp.json()
    except Exception as e:
        logger.error("Ardent exports request failed: %s", e)
        return []

    if not isinstance(sellers, list):
        logger.error("Ardent exports: oczekiwano listy, otrzymano %s", type(sellers).__name__)
        return []

    result: list[CommoditySeller] = []
    for b in sellers:
        stock = b.get("stock") or 0
        if stock < min_stock:
            continue

        pad_raw = b.get("maxLandingPadSize", 0)
        pad_size = PAD_SIZE_MAP.get(pad_raw, "")

        distance = b.get("distance") or 0.0
        dist_arrival = b.get("distanceToArrival") or 0.0
        buy_price = b.get("buyPrice") or 0

        result.append(CommoditySeller(
            station_name=b.get("stationName", ""),
            system_name=b.get("systemName", ""),
            stock=stock,
            buy_price=buy_price,
            pad_size=pad_size,
            distance=distance,
            distance_to_arrival=dist_arrival,
            updated_at=b.get("updatedAt") or "",
            station_type=b.get("stationType") or "",
        ))

    # Sortuj: buy_price rosnąco, potem stock malejąco
    result.sort(key=lambda x: (x.buy_price, -x.stock))
    logger.info("find_commodity_sellers: %d sprzedawców z %s (%s)", len(result), commodity, reference_system)
    return result[:size]


@dataclass
class MarketItem:
    """Jeden towar na rynku stacji (Ardent)."""
    name: str = ""
    buy_price: int = 0
    sell_price: int = 0
    stock: int = 0
    demand: int = 0
    mean_price: int = 0
    updated_at: str = ""


@dataclass
class StationMarket:
    """Pełny rynek stacji: co tu kupisz (exports) i co tu sprzedasz (imports)."""
    system_name: str = ""
    station_name: str = ""
    exports: list[MarketItem] = field(default_factory=list)
    imports: list[MarketItem] = field(default_factory=list)
    updated_at: str = ""
    error: str = ""


def market_from_market_json(data: dict, symbol_by_id: dict[int, str]) -> StationMarket:
    """Market.json zapisany przez grę po otwarciu rynku — dokładne ceny TEJ stacji, teraz (lepsze niż API)."""
    from datetime import datetime, timezone
    market = StationMarket(system_name=data.get("StarSystem", ""), station_name=data.get("StationName", ""),
                           updated_at=data.get("timestamp") or datetime.now(timezone.utc).isoformat())
    for raw in data.get("Items") or []:
        name = symbol_by_id.get(int(raw.get("id") or 0))
        if not name:
            continue
        item = MarketItem(name=name, buy_price=raw.get("BuyPrice") or 0, sell_price=raw.get("SellPrice") or 0,
                          stock=raw.get("Stock") or 0, demand=raw.get("Demand") or 0,
                          mean_price=raw.get("MeanPrice") or 0, updated_at=market.updated_at)
        if item.stock > 0 and item.buy_price > 0:
            market.exports.append(item)
        # Eksportowane towary mają w danych popyt 1 (placeholder) — to nie jest realny popyt
        if item.demand > 1 and item.sell_price > 0:
            market.imports.append(item)
    market.exports.sort(key=lambda i: i.buy_price - i.mean_price)
    market.imports.sort(key=lambda i: i.sell_price, reverse=True)
    return market


def get_station_market(system_name: str, station_name: str) -> StationMarket:
    """Rynek stacji z Ardent /v2/system/name/<system>/commodities, przefiltrowany po nazwie stacji.

    Ardent podaje sellPrice także przy demand=0 — "sprzedasz tu" liczy się tylko przy demand>0.
    """
    market = StationMarket(system_name=system_name, station_name=station_name)
    url = f"https://api.ardent-insight.com/v2/system/name/{requests.utils.quote(system_name)}/commodities"
    try:
        resp = requests.get(url, headers={"User-Agent": "EdTradeOverlay/0.1"}, timeout=30)
        if resp.status_code == 404:
            market.error = f"System '{system_name}' nie znaleziony"
            return market
        resp.raise_for_status()
        rows = resp.json()
    except Exception as e:
        logger.error("Ardent system commodities request failed: %s", e)
        market.error = f"Błąd sieci: {e}"
        return market

    if not isinstance(rows, list):
        market.error = "Nieoczekiwana odpowiedź Ardent"
        return market

    wanted = station_name.strip().lower()
    rows = [r for r in rows if (r.get("stationName") or "").lower() == wanted]
    if not rows:
        market.error = f"Brak danych rynku dla stacji '{station_name}' w {system_name}"
        return market

    market.station_name = rows[0].get("stationName", station_name)
    market.updated_at = max(r.get("updatedAt") or "" for r in rows)
    for r in rows:
        item = MarketItem(
            name=r.get("commodityName", ""),
            buy_price=r.get("buyPrice") or 0,
            sell_price=r.get("sellPrice") or 0,
            stock=r.get("stock") or 0,
            demand=r.get("demand") or 0,
            mean_price=r.get("meanPrice") or 0,
            updated_at=r.get("updatedAt") or "",
        )
        if item.stock > 0 and item.buy_price > 0:
            market.exports.append(item)
        # Eksportowane towary mają w danych popyt 1 (placeholder) — to nie jest realny popyt
        if item.demand > 1 and item.sell_price > 0:
            market.imports.append(item)

    market.exports.sort(key=lambda i: i.buy_price - i.mean_price)
    market.imports.sort(key=lambda i: i.sell_price, reverse=True)
    logger.info("get_station_market: %s/%s — %d exports, %d imports",
                system_name, market.station_name, len(market.exports), len(market.imports))
    return market


def age_hours(updated_at) -> Optional[float]:
    """Wiek cen w godzinach: epoch (Spansh) albo ISO 8601 (Ardent); None gdy brak/nieczytelne."""
    from datetime import datetime, timezone
    if not updated_at:
        return None
    if isinstance(updated_at, (int, float)):
        return max(0.0, (time.time() - float(updated_at)) / 3600)
    try:
        ts = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 3600)


def freshness_factor(hours: Optional[float]) -> float:
    """Pewność, że cena jeszcze obowiązuje (przybliżenie): ≤6 h 100%, ≤24 h 90%, ≤3 d 75%, starsze 50%."""
    if hours is None:
        return 0.7
    if hours <= 6:
        return 1.0
    if hours <= 24:
        return 0.9
    if hours <= 72:
        return 0.75
    return 0.5


@dataclass
class NearbyTrade:
    """Jedna okazja: towar kupiony tutaj (albo już w ładowni) → najlepszy kupiec w okolicy."""
    commodity: str = ""
    buy_price: int = 0          # 0 = towar już w ładowni (cena nieznana)
    stock: int = 0
    units: int = 0              # realnie do sprzedania: min(ładownia/ilość, zapas, popyt)
    sell_station: str = ""
    sell_system: str = ""
    sell_price: int = 0
    demand: int = 0
    distance: float = 0.0
    distance_to_arrival: float = 0.0
    pad_size: str = ""
    station_type: str = ""
    updated_at: str = ""
    travel_s: float = 0.0       # szacowany czas dolotu i dokowania

    @property
    def profit_per_unit(self) -> int:
        return self.sell_price - self.buy_price

    @property
    def total_profit(self) -> int:
        return self.profit_per_unit * self.units

    @property
    def profit_per_hour(self) -> float:
        return self.total_profit * 3600 / self.travel_s if self.travel_s else 0.0

    @property
    def age_hours(self) -> Optional[float]:
        return age_hours(self.updated_at)

    @property
    def confidence(self) -> float:
        return freshness_factor(self.age_hours)

    @property
    def expected_total(self) -> float:
        """Zysk ważony pewnością ceny — stare dane mogą już nie obowiązywać na miejscu."""
        return self.total_profit * self.confidence

    @property
    def expected_per_hour(self) -> float:
        return self.profit_per_hour * self.confidence


# Tryby rankingu handlu w okolicy (jak sortowanie zysku w Trade Advisor TCE + "czas to pieniądz")
RANK_MODES = {
    "total": "Największy zysk",
    "per_hour": "Najszybszy zysk (cr/h)",
    "time": "Najkrótsza droga",
}


RISK_PROFILES = {"safe": "SAFE — pewne ceny, mniejsze ryzyko", "optimal": "OPTIMAL — drogie towary, ale świeże ceny",
                 "risky": "RISKY — drogie towary, ryzyko za dużą nagrodę"}
RISK_PROFILE = "optimal"  # ustawiane z configu (Ustawienia → Profil); rankingi czytają je przy każdym wywołaniu


def set_risk_profile(profile: str) -> None:
    global RISK_PROFILE
    RISK_PROFILE = profile if profile in RISK_PROFILES else "optimal"


def trade_risk(t) -> float:
    """Ryzyko okazji 0–1 (wiek cen, płytki popyt, długi lot) — to samo, co w ocenie SAFE/RISKY."""
    from . import assess
    return assess.combine(assess.age_risk(t.age_hours), assess.demand_risk(t.demand, t.units),
                          0.15 if t.travel_s > assess.LONG_TRIP_S else 0.0)


RISKY_REWARD_PER_T = 20_000  # od tylu cr/t ryzyko "się opłaca" w pełni (drogie towary)


def profile_weight(t, profile: Optional[str] = None) -> float:
    """Mnożnik zysku wg profilu: SAFE (1 − ryzyko)²; OPTIMAL pewność ceny + mała premia za drogi towar;
    RISKY — ryzyko tylko za dużą nagrodę.

    RISKY: im droższy towar (zysk/t → RISKY_REWARD_PER_T), tym mniej liczy się niepewność ceny, plus premia
    do +25% — tani towar ze starymi cenami nie jest wart lotu, drogi tak.
    """
    profile = profile or RISK_PROFILE
    reward = max(0.0, min(1.0, t.profit_per_unit / RISKY_REWARD_PER_T))
    if profile == "risky":
        return (t.confidence + (1 - t.confidence) * reward) * (1 + 0.25 * reward)
    if profile == "safe":
        return (1 - trade_risk(t)) ** 2
    # OPTIMAL: też woli droższe towary (premia do +10%), ale pełna kara za wiek cen — świeższe niż RISKY
    return t.confidence * (1 + 0.10 * reward)


def _rank_key(mode: str, profile: Optional[str] = None):
    # Rankingi liczą zysk ważony profilem ryzyka (domyślnie OPTIMAL = ważony świeżością cen)
    w = lambda t: profile_weight(t, profile)
    if mode == "total":
        return lambda t: (t.total_profit * w(t), -t.travel_s)
    if mode == "time":
        return lambda t: (-t.travel_s, t.total_profit * w(t))
    return lambda t: (t.profit_per_hour * w(t), t.total_profit * w(t))


def candidate_trades(commodity: str, reference_system: str, units: int, buy_price: int, market_filter,
                     max_ly: float = 40.0, exclude_market: str = "", jump_range: float = 30.0) -> list[NearbyTrade]:
    """Wszyscy opłacalni kupcy w zasięgu (po filtrze) — wybór najlepszego zależy od trybu rankingu."""
    trades = []
    for b in find_mineral_buyers(commodity, reference_system, max_ly=max_ly, min_demand=1,
                                 max_days=market_filter.max_data_age_days, size=100):
        if not market_filter.accepts(b.pad_size, b.distance_to_arrival, b.station_type):
            continue
        if exclude_market and b.station_name.lower() == exclude_market.lower() and b.system_name.lower() == reference_system.lower():
            continue
        trade = NearbyTrade(commodity=commodity, buy_price=buy_price, units=min(units, b.demand),
                            sell_station=b.station_name, sell_system=b.system_name, sell_price=b.sell_price,
                            demand=b.demand, distance=b.distance, distance_to_arrival=b.distance_to_arrival,
                            pad_size=b.pad_size, station_type=b.station_type, updated_at=b.updated_at,
                            travel_s=travel_seconds(b.distance, b.distance_to_arrival, jump_range))
        # Ładunek w ładowni (buy_price 0) — liczy się każda sprzedaż; zakup tutaj — co najmniej min. zysk/t
        min_profit = market_filter.min_profit_per_t if buy_price else 1
        if trade.profit_per_unit >= max(1, min_profit) and trade.units > 0:
            trades.append(trade)
    return trades


def pick_best(candidates: list[NearbyTrade], mode: str = "per_hour",
              profile: Optional[str] = None) -> Optional[NearbyTrade]:
    return max(candidates, key=_rank_key(mode, profile)) if candidates else None


def rank_trades(candidates_per_commodity: list[list[NearbyTrade]], mode: str = "per_hour",
                profile: Optional[str] = None) -> list[NearbyTrade]:
    """Jeden wiersz na towar (najlepszy kupiec w danym trybie i profilu ryzyka), posortowane."""
    best = [b for b in (pick_best(c, mode, profile) for c in candidates_per_commodity) if b is not None]
    best.sort(key=_rank_key(mode, profile), reverse=True)
    return best


def best_buyer(commodity: str, reference_system: str, units: int, buy_price: int, market_filter,
               max_ly: float = 40.0, exclude_market: str = "", jump_range: float = 30.0,
               mode: str = "per_hour") -> Optional[NearbyTrade]:
    return pick_best(candidate_trades(commodity, reference_system, units, buy_price, market_filter, max_ly,
                                      exclude_market, jump_range), mode)


JUMP_SECONDS = 50.0      # ładowanie FSD + skok + wyjście z hiperprzestrzeni
DOCKING_SECONDS = 60.0   # podejście, pozwolenie, lądowanie


def supercruise_seconds(distance_to_arrival_ls: float) -> float:
    """Supercruise rośnie wolniej niż liniowo (przyspieszanie): ~40 s dla 10 ls, ~75 s dla 1000 ls, ~7 min dla 100k ls."""
    return 35.0 + 13.0 * math.sqrt(max(distance_to_arrival_ls, 0.0) / 100.0)


PILOT_FACTOR = 1.0  # Twoje tempo z realnych kursów (edtrade/pilot.py) — ustawiane przez main


def set_pilot_factor(factor: float) -> None:
    global PILOT_FACTOR
    PILOT_FACTOR = max(0.5, min(3.0, float(factor)))


def travel_seconds(distance_ly: float, distance_to_arrival_ls: float, jump_range: float = 30.0,
                   calibrated: bool = True) -> float:
    """Czas od odlotu do zadokowania u kupca — podstawa rankingu CR/H (czas to pieniądz).

    calibrated=True: ogólny szacunek × Twoje tempo z journala; False: sam szacunek (do kalibracji).
    """
    jumps = 0 if distance_ly < 0.5 else math.ceil(distance_ly / max(jump_range, 5.0))
    base = JUMP_SECONDS * jumps + supercruise_seconds(distance_to_arrival_ls) + DOCKING_SECONDS
    return base * (PILOT_FACTOR if calibrated else 1.0)


def _parallel_candidates(jobs: list[dict], reference_system: str, market_filter, max_ly: float,
                         exclude_market: str = "", workers: int = 6, jump_range: float = 30.0) -> list[list[NearbyTrade]]:
    from concurrent.futures import ThreadPoolExecutor
    _ardent_commodity_names()  # wspólna lista nazw — pobrana raz, zanim ruszą wątki
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda j: candidate_trades(j["name"], reference_system, j["units"], j["buy_price"],
                                                           market_filter, max_ly, exclude_market, jump_range), jobs))
    for job, cands in zip(jobs, results):
        for trade in cands:
            trade.stock = job.get("stock", 0)
    return [c for c in results if c]


def nearby_candidates_from_market(market: "StationMarket", capacity: int, market_filter, max_ly: float = 40.0,
                                  workers: int = 6, jump_range: float = 30.0) -> list[list[NearbyTrade]]:
    """Trade Advisor: dla każdego towaru eksportowanego tutaj — wszyscy opłacalni kupcy w okolicy (pełna ładownia)."""
    jobs = [{"name": i.name, "units": min(capacity, i.stock), "buy_price": i.buy_price, "stock": i.stock}
            for i in market.exports if i.stock > 0 and i.buy_price > 0]
    cands = _parallel_candidates(jobs, market.system_name, market_filter, max_ly, market.station_name, workers, jump_range)
    logger.info("nearby_candidates_from_market: %s/%s — %d towarów z kupcem z %d",
                market.system_name, market.station_name, len(cands), len(jobs))
    return cands


def cargo_candidates(cargo: list[dict], reference_system: str, market_filter, max_ly: float = 40.0,
                     workers: int = 6, jump_range: float = 30.0) -> list[list[NearbyTrade]]:
    """Ładunek z journala (Cargo: Name = symbol, Count) → kupcy w okolicy; pomija limpety i ładunek misyjny."""
    jobs = [{"name": c.get("Name", ""), "units": int(c.get("Count") or 0), "buy_price": 0, "stock": int(c.get("Count") or 0)}
            for c in cargo if c.get("Name") and int(c.get("Count") or 0) > 0 and c.get("Name", "").lower() != "drones"
            and not c.get("MissionID")]
    return _parallel_candidates(jobs, reference_system, market_filter, max_ly, workers=workers, jump_range=jump_range)


def nearby_trades_from_market(market: "StationMarket", capacity: int, market_filter, max_ly: float = 40.0,
                              workers: int = 6, jump_range: float = 30.0, mode: str = "per_hour") -> list[NearbyTrade]:
    return rank_trades(nearby_candidates_from_market(market, capacity, market_filter, max_ly, workers, jump_range), mode)


def best_sales_for_cargo(cargo: list[dict], reference_system: str, market_filter, max_ly: float = 40.0,
                         workers: int = 6, jump_range: float = 30.0, mode: str = "per_hour") -> list[NearbyTrade]:
    return rank_trades(cargo_candidates(cargo, reference_system, market_filter, max_ly, workers, jump_range), mode)


SERVICE_FIELDS = (
    "shipyard", "outfitting", "blackMarket", "refuel", "repair",
    "interstellarFactors", "materialTrader", "technologyBroker",
    "universalCartographics", "contacts", "crewLounge", "missions",
    "restock", "searchAndRescue", "tuning",
)


def get_station_id(station_name: str, system_name: Optional[str] = None) -> Optional[int]:
    """Znajdź numeryczne ID stacji Spansh poprzez wyszukiwarkę HTML.

    Wyszukuje stronę wyszukiwania Spansh, parsuje HTML i zwraca ID
    ze pierwszego trafienia pasującego do station_name (i system_name,
    jeśli podano).

    Zwraca None jeśli nie znaleziono.
    """
    url = SPANSH_SEARCH_URL.format(query=station_name)
    logger.info("Spansh search: %s", url)

    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "EdTradeOverlay/0.1",
        })
        resp.raise_for_status()
    except Exception as e:
        logger.error("Spansh search request failed: %s", e)
        return None

    # Parsujemy HTML — szukamy href="/station/{ID}" w wynikach
    lines = resp.text.splitlines()
    for i, line in enumerate(lines):
        # Szukamy nazwy stacji w linii
        if station_name.lower() in line.lower():
            # Sprawdzamy pobliskie linie pod kątem ID
            context = "\n".join(lines[max(0, i-2):min(len(lines), i+3)])
            id_match = SPANSH_STATION_ID_RE.search(context)
            if id_match:
                station_id = int(id_match.group(1))
                if system_name:
                    logger.info(
                        "Found station '%s' in '%s' → ID %s",
                        station_name, system_name, station_id,
                    )
                else:
                    logger.info("Found station '%s' → ID %s", station_name, station_id)
                return station_id

    logger.warning("Station '%s' not matched in Spansh results", station_name)
    return None


# Domyślna ścieżka do Trade Dangerous
DEFAULT_TD_DIR = Path.home() / "Projekty" / "trade-dangerous"
DEFAULT_TD_VENV = Path(".venv") / "bin" / "python"


@dataclass
class JourneyHop:
    """Jeden hop (skok) w planie podróży (journey planner v1)."""
    system: str = ""
    id64: str = ""
    jumps: int = 0
    distance_jumped: float = 0.0
    distance_left: float = 0.0
    neutron_star: bool = False


@dataclass
class JourneyPlan:
    """Plan trasy skoków (journey planner v1 — bez logiki paliwa)."""
    start_system: str = ""
    start_station: str = ""
    end_system: str = ""
    end_station: str = ""
    total_jumps: int = 0
    total_distance: float = 0.0
    hops: list = field(default_factory=list)  # lista JourneyHop
    error: str = ""


@dataclass
class Hop:
    """Jeden hop (skok) w trasie wieloetapowej."""
    source_system: str = ""
    source_station: str = ""
    destination_system: str = ""
    destination_station: str = ""
    commodity: str = ""
    amount: int = 0
    buy_price: int = 0
    sell_price: int = 0
    profit: int = 0
    distance: float = 0.0
    src_updated_at: float = 0.0   # epoch s — kiedy Spansh ostatnio widział ceny stacji kupna
    dst_updated_at: float = 0.0   # … i stacji sprzedaży
    dst_ls: float = 0.0           # odległość stacji celu od gwiazdy (ls), gdy znana (szybka trasa / Ardent)


@dataclass
class TradeRoute:
    """Jedna trasa handlowawyliczona przez Trade Dangerous."""

    source_system: str = ""
    source_station: str = ""
    destination_system: str = ""
    destination_station: str = ""
    buy_item: str = ""
    buy_quantity: int = 0
    buy_price: int = 0
    sell_price: int = 0
    profit_per_unit: int = 0
    total_profit: int = 0
    cargo_used: int = 0
    jumps: int = 0
    hops: int = 0
    error: str = ""
    hops_list: list = field(default_factory=list)  # Hop objects (multi-hop route)

    @property
    def profit_per_ton(self) -> float:
        if self.cargo_used == 0:
            return 0.0
        return self.total_profit / self.cargo_used

    def summary(self) -> str:
        """Krótkie podsumowanie trasy do wyświetlenia w overlayu."""
        if self.error:
            return f"⚠ {self.error}"

        if self.hops_list:
            # Multi-hop route
            lines = [f"{self.source_system}/{self.source_station} → {self.destination_system} ({self.hops} hop{'y' if self.hops != 1 else ''})"]
            for i, hop in enumerate(self.hops_list):
                lines.append(f"  Hop {i + 1}: {hop.source_station} → {hop.destination_station}")
                if hop.commodity:
                    lines.append(
                        f"    {hop.commodity} x{hop.amount} @ {hop.buy_price:,} → {hop.sell_price:,} (zysk {hop.profit:,})"
                    )
                dist = f" {hop.distance:.1f} ly" if hop.distance else ""
                lines[-1] += dist
            lines.append(f"  Zysk całkowity: {self.total_profit:,}cr")
            if self.cargo_used:
                lines.append(f"  Zysk/tona: {self.total_profit / self.cargo_used:,.0f}cr/t")
        else:
            # Single-hop (legacy)
            lines = [
                f"→ {self.destination_system}",
                f"  {self.destination_station}",
                f"  Kup: {self.buy_item} x{self.buy_quantity} @ {self.buy_price:,}cr",
                f"  Sprzedaj: {self.sell_price:,}cr/szt → zysk {self.total_profit:,}cr",
                f"  Cargo: {self.cargo_used}t | Jumps: {self.jumps} | Hops: {self.hops}",
                f"  Zysk/tona: {self.profit_per_ton:,.0f}cr/t",
            ]
        return "\n".join(lines)


@dataclass
class StationInfo:
    """Informacje o stacji z Ardent API.

    Pad size: small / medium / large (None jeśli brak danych).
    distance_to_arrival: dystans od punktu przybycia (jednostki Ardent).
    services: słownik {nazwa_uslugi: bool} — tylko usługi z flagą 1.
    """
    name: str = ""
    system_name: str = ""
    body_name: str = ""
    distance_to_arrival: float = 0.0
    pad_size: Optional[str] = None
    station_type: str = ""
    allegiance: str = ""
    government: str = ""
    primary_economy: str = ""
    services: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        size_raw = self._pad_size_raw if hasattr(self, '_pad_size_raw') else None
        if size_raw and size_raw in PAD_SIZE_MAP:
            self.pad_size = PAD_SIZE_MAP[size_raw]


@dataclass
class SystemInfo:
    """Informacje o systemie ze Spansh API.

    Zwraca: allegiance, controlling_minor_faction, government, population,
    primary_economy, secondary_economy, security.
    """
    name: str = ""
    id64: str = ""
    allegiance: str = ""
    controlling_minor_faction: str = ""
    government: str = ""
    population: int = 0
    primary_economy: str = ""
    secondary_economy: str = ""
    security: str = ""
    error: str = ""


def get_system_info(system_id64: str) -> SystemInfo:
    """Pobierz informacje o systemie ze Spansh API.

    GET /api/system/<system_id64> → record.system
    Zwraca dane o: frakcja kontrolująca, ekonomia, populacja, bezpieczeństwo.

    Args:
        system_id64: ID systemu w formacie 10477373803 (Sol).

    Returns:
        SystemInfo z danymi o systemie.
    """
    url = f"https://spansh.co.uk/api/system/{system_id64}"
    logger.info("Spansh system info: %s", url)

    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "EdTradeOverlay/0.1",
            "Accept": "application/json",
        })
        resp.raise_for_status()
        sys_data = resp.json()
        record = sys_data.get("record", {})
    except Exception as e:
        logger.error("Spansh system request failed: %s", e)
        return SystemInfo(id64=system_id64, error=str(e))

    return SystemInfo(
        name=record.get("name", ""),
        id64=system_id64,
        allegiance=record.get("allegiance", ""),
        controlling_minor_faction=record.get("controlling_minor_faction", ""),
        government=record.get("government", ""),
        population=record.get("population", 0),
        primary_economy=record.get("primary_economy", ""),
        secondary_economy=record.get("secondary_economy", ""),
        security=record.get("security", ""),
    )


def search_stations(system_name: str) -> list[StationInfo]:
    """Wyszukaj wszystkie stacje w systemie przez Ardent API.

    Zwraca listę StationInfo z pad size, odległością i usługami.
    Zwraca pustą listę przy błędzie sieci lub pustym wyniku.
    """
    url = f"{ARDENT_API_BASE}/{system_name}/stations"
    logger.info("Ardent API: %s", url)

    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "EdTradeOverlay/0.1",
            "Accept": "application/json",
        })
        resp.raise_for_status()
    except Exception as e:
        logger.error("Ardent API request failed: %s", e)
        return []

    raw_list = resp.json()
    if not isinstance(raw_list, list):
        logger.error("Ardent API: oczekiwano listy, otrzymano %s", type(raw_list).__name__)
        return []

    stations: list[StationInfo] = []
    for raw in raw_list:
        services = {
            svc: bool(raw.get(svc))
            for svc in SERVICE_FIELDS
        }
        station = StationInfo(
            name=raw.get("stationName", ""),
            system_name=raw.get("systemName", ""),
            body_name=raw.get("bodyName", ""),
            distance_to_arrival=raw.get("distanceToArrival", 0.0),
            pad_size=PAD_SIZE_MAP.get(raw.get("maxLandingPadSize")),
            station_type=raw.get("stationType", ""),
            allegiance=raw.get("allegiance", ""),
            government=raw.get("government", ""),
            primary_economy=raw.get("primaryEconomy", ""),
            services=services,
        )
        station._pad_size_raw = raw.get("maxLandingPadSize")
        stations.append(station)

    logger.info("Ardent API: %d stacji w systemie '%s'", len(stations), system_name)
    return stations


# Symbole statków z eventu Loadout ("Ship"), które mieszczą się tylko na padzie L
LARGE_PAD_SHIPS = frozenset({
    "anaconda", "belugaliner", "cutter", "federation_corvette", "imperial_clipper", "orca",
    "panthermkii", "type7", "type9", "type9_military",
})


def ship_needs_large_pad(ship: str) -> bool:
    return (ship or "").lower() in LARGE_PAD_SHIPS


class TradeEngine:
    """Wywołuje Trade Dangerous i parsuje wynik."""

    def __init__(
        self,
        td_dir: Optional[Path] = None,
        td_venv: Optional[Path] = None,
        capacity: float = 304.0,
        credits: int = 100_000,
        ly_per: float = 32.0,
    ):
        self.td_dir = td_dir or DEFAULT_TD_DIR
        self.py_path = str((self.td_dir / td_venv).resolve()) if td_venv else "python3"
        self.trade_script = str((self.td_dir / "trade.py").resolve())
        self.capacity = capacity
        self.credits = credits
        self.ly_per = ly_per
        self.requires_large_pad = False
        self.max_star_ls = 5000.0  # 0 = bez limitu
        self._last_result: Optional[TradeRoute] = None
        self._polling_callback: Optional[Callable[[int], None]] = None

    def set_polling_callback(self, callback: Optional[Callable[[int], None]]) -> None:
        """Ustaw funkcję wywoływaną co 30s podczas pollingu Spansh."""
        self._polling_callback = callback

    def calculate_route(
        self,
        system: str,
        station: str,
        capacity_override: Optional[float] = None,
        ly_per_override: Optional[float] = None,
    ) -> TradeRoute:
        """Oblicz najlepszą trasę z danej stacji.

        Używa `trade run --from SYSTEM/STATION --capacity N --credits CR --ly-per X`.
        """
        cap = capacity_override if capacity_override is not None else self.capacity
        ly = ly_per_override if ly_per_override is not None else self.ly_per
        route = TradeRoute()

        cmd = [
            self.py_path,
            self.trade_script,
            "run",
            "--from",
            f"{system}/{station}",
            "--capacity",
            str(cap),
            "--credits",
            str(self.credits),
            "--ly-per",
            str(ly),
            "--routes",
            "1",
            "--quiet",
            "--raw",
        ]

        logger.info("TradeDangerous cmd: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(self.td_dir),
            )

            if result.returncode != 0:
                err_msg = result.stderr.strip() or result.stdout.strip()
                route.error = f"TD exit={result.returncode}: {err_msg[:200]}"
                logger.error("TD error: %s", route.error)
                return route

            output = result.stdout.strip()
            if not output:
                route.error = "Trade Dangerous zwrócił pusty wynik (brak opłacalnych tras?)"
                return route

            route = self._parse_output(output, system, station)

        except subprocess.TimeoutExpired:
            route.error = "Trade Dangerous przekroczył limit 120s"
            logger.error("TD timeout")
        except FileNotFoundError:
            route.error = f"Nie znaleziono: {self.py_path}"
            logger.error("TD binary not found: %s", self.py_path)
        except Exception as e:
            route.error = f"Wyjątek: {e}"
            logger.exception("TD exception")

        self._last_result = route
        return route

    def _parse_output(self, output: str, system: str, station: str) -> TradeRoute:
        """Parsuje surowy output z `trade run --raw`."""
        route = TradeRoute(
            destination_system=system,
            destination_station=station,
        )

        lines = output.splitlines()

        # Szukamy sekcji z instrukcjami zakupu/sprzedaży
        # Format raw:
        # === Route from SYSTEM/Station ===
        # Buy ITEM xN at Station (price)
        # Fly to ...
        # Sell ITEM xN at Station (price), profit
        # ...
        # Summary: total_profit jumps hops

        buy_item = ""
        buy_qty = 0
        buy_price = 0
        sell_price = 0
        profit = 0
        cargo = 0
        jumps = 0
        hops = 0
        dest_sys = system
        dest_stat = station

        for line in lines:
            line_stripped = line.strip()

            # Parse: Buy ITEM xN at Station (price[cr])
            m = re.match(r"Buy\s+(\S.*?)\s+x(\d+)\s+at\s+(.+?)\s+\(([\d,]+)cr?\)", line_stripped)
            if m:
                buy_item = m.group(1).strip()
                buy_qty = int(m.group(2))
                buy_price = int(m.group(4).replace(",", ""))
                cargo = buy_qty
                continue

            # Parse: Sell ITEM xN at Station (price[cr]), profit X[cr] (profit może być ujemny)
            m = re.match(
                r"Sell\s+(\S.*?)\s+x(\d+)\s+at\s+(.+?)\s+\(([\d,]+)cr?\),\s+profit\s+(-?[\d,]+)cr?",
                line_stripped,
            )
            if m:
                sell_price = int(m.group(4).replace(",", ""))
                profit = int(m.group(5).replace(",", ""))
                dest_stat = m.group(3).strip()
                continue

            # Parse: Fly to SYSTEM (X jumps, Y ly)
            m = re.match(r"Fly\s+to\s+(\S.*?)\s+\((\d+)\s+jumps?", line_stripped)
            if m:
                dest_sys = m.group(1).strip()
                jumps += int(m.group(2))
                continue

            # Parse: hop count
            if "hop" in line_stripped.lower():
                m = re.search(r"(\d+)\s+hop", line_stripped)
                if m:
                    hops += int(m.group(1))

            # Parse total profit line (profit może być ujemny)
            m = re.search(r"profit\s+(-?[\d,]+)", line_stripped, re.IGNORECASE)
            if m:
                profit = int(m.group(1).replace(",", ""))

        route.buy_item = buy_item
        route.buy_quantity = buy_qty
        route.buy_price = buy_price
        route.sell_price = sell_price
        route.total_profit = profit
        route.cargo_used = cargo
        route.jumps = jumps
        route.hops = hops
        route.destination_system = dest_sys
        route.destination_station = dest_stat

        if buy_item and profit > 0:
            route.profit_per_unit = sell_price - buy_price

        return route

    def calculate_route_via_spansh(
        self,
        system: str,
        station: str,
        capacity_override: Optional[float] = None,
        ly_per_override: Optional[float] = None,
        max_hops: int = 3,
    ) -> TradeRoute:
        """Oblicz najlepszą trasę przez Spansh API (POST form-encoded + polling).

        POST /api/trade/route  → 202 + job_id
        GET  /api/results/{job_id}  → polling aż state=completed
        """
        cap = capacity_override if capacity_override is not None else self.capacity
        ly = ly_per_override if ly_per_override is not None else self.ly_per
        route = TradeRoute()

        payload = {
            "system": system,
            "station": station,
            "starting_capital": self.credits,
            "max_cargo": int(cap),
            "max_hops": max_hops,
            "max_hop_distance": ly,
            # Odległość stacji od gwiazdy w LS (nie zasięg skoku w ly!) — wcześniej wpisywane ly ≈ 30 odcinało stacje >30 ls
            "max_system_distance": int(self.max_star_ls) if self.max_star_ls else 10_000_000,
        }
        if self.requires_large_pad:
            payload["requires_large_pad"] = "1"

        headers_form = {
            "User-Agent": "EdTradeOverlay/0.1",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        # 1. POST — queue job
        logger.info("Spansh POST /api/trade/route: %s/%s", system, station)
        try:
            resp = requests.post(
                "https://spansh.co.uk/api/trade/route",
                data=payload,
                headers=headers_form,
                timeout=30,
            )
            resp.raise_for_status()
            job_data = resp.json()
            job_id = job_data.get("job")
            if not job_id:
                route.error = f"Brak job_id w odpowiedzi: {job_data}"
                logger.error("Spansh no job_id: %s", job_data)
                self._last_result = route
                return route
            logger.info("Spansh job queued: %s", job_id)
        except Exception as e:
            route.error = f"Spansh POST failed: {e}"
            logger.error("Spansh POST error: %s", e)
            self._last_result = route
            return route

        # 2. Polling GET /api/results/{job_id}
        max_wait = 240
        poll_interval = 5
        start = time.time()
        while True:
            elapsed = time.time() - start
            if elapsed > max_wait:
                route.error = "Spansh polling timeout"
                logger.error("Spansh polling timeout after %ds", max_wait)
                break

            try:
                resp = requests.get(
                    f"https://spansh.co.uk/api/results/{job_id}",
                    headers={"Accept": "application/json", "User-Agent": "EdTradeOverlay/0.1"},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                state = data.get("state", "?")
                status = data.get("status", "?")
                logger.info("Spansh poll [%ds]: state=%s status=%s", int(elapsed), state, status)

                # Callback co 30s — aktualizacja overlaya podczas oczekiwania
                if self._polling_callback and int(elapsed) % 30 == 0:
                    self._polling_callback(int(elapsed))

                if state == "completed":
                    if status == "ok":
                        route = self._parse_spansh_result(data, system, station)
                        # Feature B: sprawdź scoopable asynchronicznie
                        self._check_scoopable(route)
                    else:
                        route.error = f"Spansh error: {status}"
                    break
            except Exception as e:
                logger.warning("Spansh poll error: %s", e)

            time.sleep(poll_interval)

        self._last_result = route
        return route

    def plan_journey(
        self,
        start_system: str,
        end_system: str,
        ship_range: float,
        efficiency: float = 60.0,
        via: Optional[str] = None,
    ) -> JourneyPlan:
        """Oblicz trasę skoków przez Spansh API (POST /api/route + polling).

        V1: BEZ logiki paliwa — tylko trasa + oznaczenie gwiazd neutronowych.
        POST /api/route  → 202 + job_id
        GET  /api/results/{job_id}  → polling aż state=completed
        """
        plan = JourneyPlan()
        plan.start_system = start_system
        plan.end_system = end_system
        plan.total_jumps = 0
        plan.total_distance = 0.0

        # Opcjonalna stacja pośrednia (via)
        via_station = via

        payload = {
            "from": f"{start_system}",  # Nazwa systemu (np. "Sol")
            "to": f"{end_system}",       # Nazwa systemu (np. "Columbus" to błąd — musi to być nazwa systemu)
            "range": ship_range,
            "efficiency": efficiency,
        }
        if via_station:
            payload["via"] = via_station

        headers_form = {
            "User-Agent": "EdTradeOverlay/0.1",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        # 1. POST — queue job
        logger.info("Spansh POST /api/route: %s → %s (range=%.1f ly, eff=%.0f%%)",
                    start_system, end_system, ship_range, efficiency)
        try:
            resp = requests.post(
                "https://spansh.co.uk/api/route",
                data=payload,
                headers=headers_form,
                timeout=30,
            )
            resp.raise_for_status()
            job_data = resp.json()
            job_id = job_data.get("job")
            if not job_id:
                plan.error = f"Brak job_id w odpowiedzi: {job_data}"
                logger.error("Spansh route no job_id: %s", job_data)
                return plan
            logger.info("Spansh route job queued: %s", job_id)
        except Exception as e:
            plan.error = f"Spansh POST failed: {e}"
            logger.error("Spansh route POST error: %s", e)
            return plan

        # 2. Polling GET /api/results/{job_id}
        max_wait = 120  # timeout 120 s jak w TradeEngine
        poll_interval = 5
        start = time.time()
        while True:
            elapsed = time.time() - start
            if elapsed > max_wait:
                plan.error = "Spansh polling timeout"
                logger.error("Spansh route polling timeout after %ds", max_wait)
                break

            try:
                resp = requests.get(
                    f"https://spansh.co.uk/api/results/{job_id}",
                    headers={"Accept": "application/json", "User-Agent": "EdTradeOverlay/0.1"},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                state = data.get("state", "?")
                status = data.get("status", "?")
                logger.info("Spansh route poll [%ds]: state=%s status=%s", int(elapsed), state, status)

                if state == "completed":
                    if status == "ok":
                        plan = self._parse_route_result(data, start_system, end_system)
                    else:
                        plan.error = f"Spansh error: {status}"
                    break
            except Exception as e:
                logger.warning("Spansh route poll error: %s", e)

            time.sleep(poll_interval)

        return plan

    def _parse_route_result(self, data: dict, start_system: str, end_system: str) -> JourneyPlan:
        """Parsuje wynik Spansh API do JourneyPlan (route planner).

        system_jumps[] to lista hopów z polami:
        system, id64, jumps, distance_jumped, distance_left, neutron_star
        """
        plan = JourneyPlan()
        plan.start_system = start_system
        plan.end_system = end_system

        results = (data.get("result") or {}).get("system_jumps", [])

        if not results:
            plan.error = "Spansh zwrócił pusty wynik (brak trasy?)"
            return plan

        # Budujemy listę hopów
        for seg in results:
            hop = JourneyHop()
            hop.system = seg.get("system", "")
            hop.id64 = seg.get("id64", "")
            hop.jumps = seg.get("jumps", 0)
            hop.distance_jumped = seg.get("distance_jumped", 0.0)
            hop.distance_left = seg.get("distance_left", 0.0)
            hop.neutron_star = seg.get("neutron_star", False)

            plan.hops.append(hop)

        # Obliczenia całkowite
        plan.total_jumps = sum(h.jumps for h in plan.hops)
        plan.total_distance = sum(h.distance_jumped for h in plan.hops)

        # Sprawdź czy docel jest na końcu
        if plan.hops and plan.hops[-1].system != end_system:
            plan.error = f"Docelowy system ({end_system}) nie znajduje się na końcu trasy"
            logger.warning("JourneyPlan: last hop system=%s != end_system=%s",
                          plan.hops[-1].system, end_system)

        return plan

    def _parse_spansh_result(self, data: dict, system: str, station: str) -> TradeRoute:
        """Parsuje wynik Spansh API do TradeRoute (multi-hop).

        result[] to łańcuch segmentów — każdy to jeden hop.
        cumulative_profit na ostatnim segmencie = całkowity zysk trasy.
        """
        route = TradeRoute()
        results = data.get("result", [])

        if not results:
            route.error = "Spansh zwrócił pusty wynik (brak opłacalnych tras?)"
            return route

        # result[] to jeden łańcuch — bierzemy wszystkie segmenty
        num_hops = len(results)

        # Pierwszy segment: źródło = stacja startowa
        first = results[0]
        first_dest = first.get("destination", {})

        # Ostatni segment: destination = końcówka trasy
        last = results[-1]
        last_dest = last.get("destination", {})
        route.total_profit = last.get("cumulative_profit", last.get("total_profit", 0))
        route.destination_system = last_dest.get("system", "")
        route.destination_station = last_dest.get("station", "")

        # Budujemy listę hopów
        for seg in results:
            src = seg.get("source", {})
            dst = seg.get("destination", {})
            comms = seg.get("commodities", [])

            hop = Hop()
            hop.source_system = src.get("system", "")
            hop.source_station = src.get("station", "")
            hop.destination_system = dst.get("system", "")
            hop.destination_station = dst.get("station", "")
            hop.distance = seg.get("distance", 0.0)
            hop.src_updated_at = src.get("market_updated_at") or 0.0
            hop.dst_updated_at = dst.get("market_updated_at") or 0.0

            # system_id64 destynacji hopa (dla Feature B — scoopable check)
            hop._destination_id64 = dst.get("system_id64", "")
            logger.debug("Hop %d: dest=%s/%s id64=%s", len(route.hops_list),
                         dst.get("system","?"), dst.get("station","?"), hop._destination_id64)

            if comms:
                c = comms[0]
                hop.commodity = c.get("name", "")
                hop.amount = c.get("amount", 0)
                hop.buy_price = c.get("source_commodity", {}).get("buy_price", 0)
                hop.sell_price = c.get("destination_commodity", {}).get("sell_price", 0)
                hop.profit = c.get("total_profit", 0)

            route.hops_list.append(hop)

        route.hops = num_hops
        route.jumps = num_hops
        route.cargo_used = results[0].get("commodities", [{}])[0].get("amount", 0)

        # Ustawiamy pola legacy (pierwszy hop)
        if route.hops_list:
            f = route.hops_list[0]
            route.buy_item = f.commodity
            route.buy_quantity = f.amount
            route.buy_price = f.buy_price
            route.sell_price = f.sell_price
            route.total_profit = route.hops_list[-1].profit if len(route.hops_list) == 1 else route.total_profit
            if f.buy_price > 0:
                route.profit_per_unit = f.sell_price - f.buy_price

        if route.total_profit <= 0:
            route.error = "Spansh: najlepsza trasa ma zysk <= 0"
            return route

        profit_per_t = route.total_profit / route.cargo_used if route.cargo_used else 0
        logger.info(
            "Spansh route: %s/%s → %s (%d hop%s), total_profit=%d, profit/t=%.0f",
            system, station,
            route.destination_system,
            route.hops, "y" if route.hops != 1 else "",
            route.total_profit, profit_per_t,
        )

        return route

    def _check_scoopable(self, route: TradeRoute) -> None:
        """Sprawdź czy gwiazda następnego systemu jest scoopable (Feature B).

        GET /api/system/<system_id64> → bodies[].subtype zawiera klasę gwiazdy.
        Scoopable: K, G, B, F, O, A, M.
        """
        if not route.hops_list:
            return
        # Następny system = destination pierwszego hopu
        first_dest = route.hops_list[0].destination_system
        dest_id64 = route.hops_list[0]._destination_id64 if hasattr(route.hops_list[0], '_destination_id64') else None
        logger.debug("Scoopable check: first_dest=%s id64=%s", first_dest, dest_id64)
        if not dest_id64:
            return

        try:
            resp = requests.get(
                f"https://spansh.co.uk/api/system/{dest_id64}",
                headers={"Accept": "application/json", "User-Agent": "EdTradeOverlay/0.1"},
                timeout=10,
            )
            resp.raise_for_status()
            sys_data = resp.json()
            bodies = sys_data.get("record", {}).get("bodies", [])
            for body in bodies:
                if body.get("bodyType") == "Star":
                    subtype = body.get("subtype", "")
                    # Klasy: K, G, B, F, O, A, M (na początku stringa)
                    first_letter = subtype[0].upper() if subtype else ""
                    route._scoopable = first_letter in ("K", "G", "B", "F", "O", "A", "M")
                    logger.info("Scoopable check for %s: %s → %s",
                                first_dest, subtype, route._scoopable)
                    break
            else:
                route._scoopable = False
                logger.info("Scoopable check for %s: no star body found", first_dest)
        except Exception as e:
            logger.warning("Scoopable check failed for %s: %s", first_dest, e)
            route._scoopable = False

    def last_result(self) -> Optional[TradeRoute]:
        return self._last_result
