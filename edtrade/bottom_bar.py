"""Dolny pasek: karta stacji docelowej bieżącego hopu (jak prawa kolumna Trade Overview w TCE).

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
        tk.Label(body, text="STACJA DOCELOWA", font=self.fonts.tab, fg=tce.TEXT_ON_ORANGE, bg=tce.ORANGE,
                 padx=12).pack(side=tk.LEFT, fill=tk.Y)
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

    # --- treść (wątek Tk) ---
    def show_waiting(self) -> None:
        self.name_label.config(text="BRAK CELU — CZEKAM NA TRASĘ")
        self.fields_label.config(text="")
        self.warning_label.config(text="")

    def show_loading(self, system: str, station: str) -> None:
        self.name_label.config(text=f"{station} · {system} — POBIERAM DANE…".upper())
        self.fields_label.config(text="")
        self.warning_label.config(text="")

    def show_destination(self, info: DestinationInfo) -> None:
        name = f"{info.station} · {info.system}".upper()
        self.name_label.config(text=name)
        if info.error:
            self.fields_label.config(text=f"BRAK DANYCH O STACJI: {info.error}".upper(), fg=tce.ORANGE_DIM)
            self.warning_label.config(text="")
            return
        # Dwa wiersze, żeby zmieściło się na 1920 px: stacja + liczby, potem frakcja/bezpieczeństwo/usługi
        fields = [f"{label}: {value}" for label, value in card_fields(info)]
        self.name_label.config(text=f"{name}      " + "   ".join(fields[:5]).upper())
        self.fields_label.config(text="   ".join(fields[5:]).upper(), fg=tce.ORANGE)
        text, color = card_warning(info)
        self.warning_label.config(text=text, fg=color)
