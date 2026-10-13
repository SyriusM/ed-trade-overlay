"""Filtry rynków wspólne dla trasy, tabel panelu i handlu w okolicy (jak "Market minimum pad size" w TCE)."""

from dataclasses import dataclass
from typing import Optional

PAD_RANK = {"small": 1, "medium": 2, "large": 3}
PLANETARY_STATION_TYPES = frozenset({
    "crateroutpost", "craterport", "onfootsettlement", "surfacestation", "planetaryport", "planetaryoutpost",
})
PAD_MODES = ("auto", "large", "all")
MARKET_TYPES = ("all", "space", "planetary")


@dataclass
class MarketFilter:
    min_pad: str = "medium"         # small / medium / large
    max_star_ls: float = 5000.0     # 0 = bez limitu
    market_type: str = "all"        # all / space / planetary

    @property
    def requires_large_pad(self) -> bool:
        return self.min_pad == "large"

    def pad_ok(self, pad_size: Optional[str]) -> bool:
        # Brak danych o padzie: nie odrzucamy (tabela pokaże "?")
        if not pad_size:
            return True
        return PAD_RANK.get(pad_size.lower(), 0) >= PAD_RANK[self.min_pad]

    def star_ok(self, distance_to_arrival: Optional[float]) -> bool:
        return not self.max_star_ls or (distance_to_arrival or 0) <= self.max_star_ls

    def type_ok(self, station_type: Optional[str]) -> bool:
        if self.market_type == "all" or not station_type:
            return True
        planetary = station_type.lower() in PLANETARY_STATION_TYPES
        return planetary if self.market_type == "planetary" else not planetary

    def accepts(self, pad_size: Optional[str], distance_to_arrival: Optional[float],
                station_type: Optional[str] = None) -> bool:
        return self.pad_ok(pad_size) and self.star_ok(distance_to_arrival) and self.type_ok(station_type)

    def describe(self) -> str:
        parts = [f"pad {self.min_pad[0].upper()}+" if self.min_pad != "small" else "każdy pad"]
        parts.append(f"≤{self.max_star_ls:,.0f} ls" if self.max_star_ls else "bez limitu ls")
        if self.market_type != "all":
            parts.append("kosmos" if self.market_type == "space" else "planetarne")
        return " · ".join(parts)


def filter_from_config(config: dict, ship_large_pad: bool) -> MarketFilter:
    mode = config.get("pad_filter", "auto")
    if mode == "large":
        min_pad = "large"
    elif mode == "all":
        min_pad = "small"
    else:
        min_pad = "large" if ship_large_pad else "medium"
    try:
        max_ls = max(0.0, float(config.get("max_star_distance_ls", 5000)))
    except (TypeError, ValueError):
        max_ls = 5000.0
    market_type = config.get("market_type", "all")
    return MarketFilter(min_pad=min_pad, max_star_ls=max_ls,
                        market_type=market_type if market_type in MARKET_TYPES else "all")
