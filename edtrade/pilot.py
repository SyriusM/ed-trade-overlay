"""Twoje tempo: realny czas kursów (z journala) vs szacunek → mnożnik czasu dla rankingów CR/H.

Kurs = od ostatniego zakupu towaru hopu do zadokowania w celu (timestampy journala). Szacunek
`trade.travel_seconds` jest ogólny (50 s/skok, supercruise, dokowanie) — mediana ilorazów z Twoich
kursów dopasowuje go do statku, stylu lotu i tego, czy robisz przerwy.
"""

import json
import logging
import statistics
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path.home() / ".local" / "share" / "ed-trade-overlay" / "pilot.json"
MAX_SAMPLES = 30
MIN_SAMPLES = 3          # mniej kursów → jeszcze ogólny szacunek (mnożnik 1.0)
RATIO_RANGE = (0.3, 4.0)  # poza tym zakresem to nie kurs, tylko przerwa / objazd / błąd — pomijamy
FACTOR_RANGE = (0.5, 3.0)


class PilotCalibration:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or DEFAULT_PATH
        self._lock = threading.Lock()
        self.samples: list[dict] = []
        try:
            self.samples = json.loads(self.path.read_text()).get("samples", [])[-MAX_SAMPLES:]
        except (OSError, ValueError, AttributeError):
            self.samples = []

    def add(self, actual_s: float, estimate_s: float, label: str = "") -> bool:
        """Zapisz kurs; False gdy odrzucony (nierealny iloraz)."""
        if estimate_s <= 0 or actual_s <= 0:
            return False
        ratio = actual_s / estimate_s
        if not RATIO_RANGE[0] <= ratio <= RATIO_RANGE[1]:
            logger.info("Kurs pominięty w kalibracji (%.0f s vs szacunek %.0f s)", actual_s, estimate_s)
            return False
        with self._lock:
            self.samples.append({"actual": round(actual_s), "estimate": round(estimate_s), "label": label})
            self.samples = self.samples[-MAX_SAMPLES:]
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps({"samples": self.samples}, indent=1))
            except OSError:
                logger.exception("Zapis kalibracji tempa")
        return True

    @property
    def factor(self) -> float:
        with self._lock:
            if len(self.samples) < MIN_SAMPLES:
                return 1.0
            median = statistics.median(s["actual"] / s["estimate"] for s in self.samples)
        return min(FACTOR_RANGE[1], max(FACTOR_RANGE[0], median))

    def describe(self) -> str:
        n = len(self.samples)
        if n < MIN_SAMPLES:
            return f"szacunek ogólny (kalibracja: {n}/{MIN_SAMPLES} kursów)"
        return f"×{self.factor:.2f} szacunku ({courses_word(n)})"


def courses_word(n: int) -> str:
    """1 kurs, 2–4 kursy, 5+ kursów (12–14 kursów)."""
    if n == 1:
        return "1 kurs"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} kursy"
    return f"{n} kursów"
