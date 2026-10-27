"""Dolny pasek: rotacja stron co kilka sekund — karta stacji docelowej (bez nazwy, która jest na górnym
pasku), najlepsze okazje w okolicy i rada HOLD / SELL dla każdego towaru w ładowni.

Pokazuje typ stacji, pad, odległość od gwiazdy, odległość hopu, wiek danych rynku, frakcję i jej stan
(lockdown na czerwono), bezpieczeństwo systemu i ważne usługi. Okno jak górny pasek: overrideredirect,
-type splash (nie zabiera fokusu grze), przezroczystość z CONTROL, wysuwane od dolnej krawędzi.
"""

import time
import tkinter as tk
from typing import Optional

from . import tce_theme as tce
from .destination import DestinationInfo
from .slide import SlidingBar

WINDOW_HEIGHT = 52
ROTATE_MS = 8000
PAGE_ORDER = ("cel", "okolica", "ladunek")
TRADES_ON_BAR = 3


def nearby_lines(items: list[tuple[str, str, str, str, int, float]]) -> tuple[str, str]:
    """Okazje w okolicy: (ocena, towar, stacja, system, zysk/t, cr/h) → dwie linie paska (2 + reszta)."""
    texts = [f"{badge} {name} → {station} ({system})  +{per_t:,}/T · {per_h / 1e6:.1f}M/H".strip()
             for badge, name, station, system, per_t, per_h in items[:TRADES_ON_BAR]]
    return "     ".join(texts[:2]), "     ".join(texts[2:])


def cargo_lines(items: list[tuple[str, str, int, str]]) -> tuple[str, str]:
    """Ładunek: (rada, towar, ilość, gdzie) → dwie linie (połowa towarów w każdej)."""
    texts = [f"{badge} {name} ×{count}" + (f" → {where}" if where else "") for badge, name, count, where in items]
    half = (len(texts) + 1) // 2
    return "     ".join(texts[:half]), "     ".join(texts[half:])


def format_age(updated_ts: float, now: Optional[float] = None) -> str:
    if not updated_ts:
        return "?"
    elapsed = max(0, int((now or time.time()) - updated_ts))
    if elapsed < 60:
        return f"{elapsed}s temu"
    if elapsed < 3600:
        return f"{elapsed // 60}m temu"
    if elapsed < 86400 * 2:
        return f"{elapsed // 3600}h temu"
    return f"{elapsed // 86400}d temu"


def card_fields(info: DestinationInfo, now: Optional[float] = None) -> list[tuple[str, str]]:
    """(etykieta, wartość) w kolejności wyświetlania — bez Tk, do testów."""
    unknown = "?"
    faction = info.faction or unknown
    if info.faction_states:
        faction += f" ({', '.join(info.faction_states)})"
    return [
        ("TYP", info.station_type or unknown),
        ("PAD", info.pad or unknown),
        ("OD GWIAZDY", f"{info.distance_ls:,.0f} ls" if info.distance_ls is not None else unknown),
        ("ODL.", f"{info.distance_ly:,.1f} ly" if info.distance_ly is not None else unknown),
        ("DANE RYNKU", format_age(info.market_updated_ts, now)),
        ("FRAKCJA", faction),
        ("BEZPIECZ.", info.security or unknown),
        ("USŁUGI", ", ".join(info.services) or unknown),
    ]


def card_warning(info: DestinationInfo) -> tuple[str, str]:
    """(tekst, kolor) ostrzeżenia: lockdown na czerwono, inne trudne stany na pomarańczowo."""
    if info.lockdown:
        return "⚠ LOCKDOWN — USŁUGI STACJI MOGĄ BYĆ ZAMKNIĘTE", tce.RED
    if info.warnings:
        return "⚠ " + ", ".join(info.warnings).upper(), tce.ORANGE
    return "", tce.ORANGE


class BottomBar:
    """Okno dolnego paska (Toplevel nad tym samym Tk co górny pasek)."""

    def __init__(self, master: tk.Misc, fonts: tce.Fonts):
        self.window = tk.Toplevel(master)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        try:
            self.window.wm_attributes("-type", "splash")
        except tk.TclError:
            pass
        self.window.configure(bg=tce.BG)
        self.window.attributes("-alpha", 0.75)
        self.fonts = fonts
        self._scale = 1.0
        self._build()
        self.slider = SlidingBar(self.window, edge="bottom", height_fn=self.height)
        self._apply_geometry()
        self.show_waiting()

    def _build(self) -> None:
        frame = tk.Frame(self.window, bg=tce.BG)
        frame.pack(fill=tk.BOTH, expand=True)
        tk.Frame(frame, bg=tce.ORANGE, height=2).pack(side=tk.TOP, fill=tk.X)
        body = tk.Frame(frame, bg=tce.BG)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self.tab_label = tk.Label(body, text="STACJA DOCELOWA", font=self.fonts.tab, fg=tce.TEXT_ON_ORANGE,
                                  bg=tce.ORANGE, padx=12, width=16)
        self.tab_label.pack(side=tk.LEFT, fill=tk.Y)
        content = tk.Frame(body, bg=tce.ROW_BG, highlightthickness=1, highlightbackground=tce.ORANGE_DIM)
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.name_label = tk.Label(content, text="", font=self.fonts.section, fg=tce.TEXT_WHITE, bg=tce.ROW_BG,
                                   anchor="w", padx=8)
        self.name_label.pack(side=tk.TOP, fill=tk.X)
        self.fields_label = tk.Label(content, text="", font=self.fonts.body_bold, fg=tce.ORANGE, bg=tce.ROW_BG,
                                     anchor="w", padx=8)
        self.fields_label.pack(side=tk.TOP, fill=tk.X)
        self.warning_label = tk.Label(body, text="", font=self.fonts.body_bold, fg=tce.RED, bg=tce.BG, padx=10)
        self.warning_label.pack(side=tk.RIGHT, fill=tk.Y)
        # Strony rotacji: klucz → (zakładka, linia 1, linia 2, kolor linii 2)
        self.pages: dict[str, tuple[str, str, str, str]] = {}
        self._current = ""
        self._rotate_job = None

    def height(self) -> int:
        return round(WINDOW_HEIGHT * self._scale)

    def _apply_geometry(self) -> None:
        width = self.window.winfo_screenwidth()
        height = self.height()
        self.window.geometry(f"{width}x{height}+0+{self.window.winfo_screenheight() - height}")
        self.slider.place()

    def apply_appearance(self, alpha: float, font_scale: float) -> None:
        """CONTROL — ta sama przezroczystość i skala co górny pasek (czcionki są wspólne)."""
        self.window.attributes("-alpha", min(1.0, max(0.2, alpha)))
        self._scale = font_scale
        self._apply_geometry()

    # --- strony i rotacja (wątek Tk) ---
    def set_page(self, key: str, tab: str, line1: str, line2: str = "", color: str = tce.ORANGE) -> None:
        if not line1 and not line2:
            self.clear_page(key)
            return
        self.pages[key] = (tab, line1, line2, color)
        if not self._current or self._current == key or self._current not in self.pages:
            self._show(key)
        self._schedule()

    def clear_page(self, key: str) -> None:
        self.pages.pop(key, None)
        if self._current == key:
            self._advance()

    def _schedule(self) -> None:
        if self._rotate_job is None and len(self.pages) > 1:
            self._rotate_job = self.window.after(ROTATE_MS, self._tick)

    def _tick(self) -> None:
        self._rotate_job = None
        self._advance()
        self._schedule()

    def _advance(self) -> None:
        keys = [k for k in PAGE_ORDER if k in self.pages] + [k for k in self.pages if k not in PAGE_ORDER]
        if not keys:
            self._current = ""
            self.tab_label.config(text="STACJA DOCELOWA")
            self.name_label.config(text="BRAK CELU — CZEKAM NA TRASĘ")
            self.fields_label.config(text="")
            return
        index = keys.index(self._current) + 1 if self._current in keys else 0
        self._show(keys[index % len(keys)])

    def _show(self, key: str) -> None:
        self._current = key
        tab, line1, line2, color = self.pages[key]
        self.tab_label.config(text=tab)
        self.name_label.config(text=line1.upper())
        self.fields_label.config(text=line2.upper(), fg=color)

    # --- karta celu ---
    def show_waiting(self) -> None:
        self.warning_label.config(text="")
        self.clear_page("cel")
        if not self.pages:
            self._advance()

    def show_loading(self, system: str, station: str) -> None:
        self.warning_label.config(text="")
        self.set_page("cel", "STACJA DOCELOWA", "POBIERAM DANE STACJI…", "", tce.ORANGE_DIM)

    def show_destination(self, info: DestinationInfo) -> None:
        if info.error:
            self.warning_label.config(text="")
            self.set_page("cel", "STACJA DOCELOWA", f"BRAK DANYCH O STACJI: {info.error}", "", tce.ORANGE_DIM)
            return
        # Nazwa stacji jest na górnym pasku (CEL) — tu tylko szczegóły, w dwóch wierszach
        fields = [f"{label}: {value}" for label, value in card_fields(info)]
        self.set_page("cel", "STACJA DOCELOWA", "   ".join(fields[:5]), "   ".join(fields[5:]))
        text, color = card_warning(info)
        self.warning_label.config(text=text, fg=color)
