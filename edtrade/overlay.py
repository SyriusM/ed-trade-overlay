"""Overlay — semi-transparent, always-on-top, borderless X11 window.

Displays the best trade route from the current station as a compact
top bar spanning the full screen width. Uses Tkinter with overrideredirect,
-alpha for transparency, and -type splash to avoid stealing focus from the game.
"""

import logging
import threading
import tkinter as tk
import tkinter.font as tkfont
from typing import Optional, Callable

from . import tce_theme as tce
from . import assess
from .trade import TradeRoute, age_hours

logger = logging.getLogger(__name__)

# Górny pasek pełnej szerokości w układzie MAIN UI z TCE: POZYCJA | status trasy | CEL
WINDOW_HEIGHT = 84
MARGIN = 8


def compact_cr(value: int) -> str:
    """Kwoty na pasku: 7920877 → 7.92M, 84500 → 84.5K (pełna wartość jest w panelu)."""
    v = abs(value)
    sign = "-" if value < 0 else ""
    if v >= 1_000_000:
        return f"{sign}{v / 1_000_000:.2f}M"
    if v >= 10_000:
        return f"{sign}{v / 1_000:.1f}K"
    return f"{value:,}"


def fit_line(text: str, width: int, measure: Callable[[str], int]) -> str:
    """Przytnij linię z wielokropkiem, żeby zmieściła się w `width` px (pasek ma stałą szerokość)."""
    if width <= 1 or measure(text) <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if measure(text[:mid].rstrip() + "…") <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + "…"


class TradeOverlay:
    """Okno overlay z informacjami o najlepszej trasie handlowej."""

    def __init__(self, master: Optional[tk.Tk] = None):
        self.master = master or tk.Tk()
        self.master.withdraw()  # ukryj na czas konfiguracji

        self._setup_window()
        self._setup_fonts()
        self._build_ui()

        self.current_route: Optional[TradeRoute] = None
        self._update_pending = False
        self._route_queue: Optional[TradeRoute] = None
        self._queue_lock = threading.Lock()
        self._player_cargo: list = []  # Lista towarów z Cargo.json
        self._pages: list[tuple[str, 'Callable[[], str]']] = []
        self._page_index: int = 0
        self._system_info_text: str = ''
        self._copied_system: str = ''  # system w schowku (auto-kopiowanie celu trasy)

    def _setup_window(self):
        """Configure X11 window: semi-transparent, always-on-top, no decorations.

        -alpha used for partial transparency (transparentcolor not supported by this
        Tk build). overrideredirect + -type splash prevents focus stealing.
        """
        self.master.attributes("-fullscreen", False)
        self.master.attributes("-topmost", True)
        self.master.overrideredirect(True)
        self.master.wm_attributes("-type", "splash")

        self.master.configure(bg=tce.BG)
        self.master.attributes("-alpha", 0.75)

        # Rozmiar i pozycja — górny pasek pełnej szerokości
        self._apply_geometry()

        # Zablokuj zmianę rozmiaru
        self.master.resizable(False, False)

    def _apply_geometry(self, scale: float = 1.0):
        """Ustaw geometrię: pełna szerokość ekranu, mała wysokość u góry (rośnie ze skalą czcionki)."""
        width = self.master.winfo_screenwidth()
        self.master.geometry(f"{width}x{round(WINDOW_HEIGHT * scale)}+0+0")

    def apply_appearance(self, alpha: float, font_scale: float) -> None:
        """CONTROL jak w TCE: przezroczystość i skala czcionki paska (wołane w wątku Tk)."""
        self.master.attributes("-alpha", min(1.0, max(0.2, alpha)))
        self.fonts.set_scale(font_scale)
        self._apply_geometry(font_scale)

    def _setup_fonts(self):
        fonts = tce.Fonts(self.master)
        self.fonts = fonts
        self.font_tab = fonts.tab
        self.font_title = fonts.big
        self.font_highlight = fonts.section
        self.font_info = fonts.body_bold
        self.font_small = fonts.body

    def _display(self, parent: tk.Misc, title: str) -> tk.Frame:
        """Wyświetlacz jak w TCE: pomarańczowa zakładka z nazwą + brązowe pole treści."""
        box = tk.Frame(parent, bg=tce.BG, highlightthickness=1, highlightbackground=tce.ORANGE_DIM)
        tk.Label(box, text=title, font=self.font_tab, fg=tce.TEXT_ON_ORANGE, bg=tce.ORANGE,
                 padx=12).pack(side=tk.TOP, anchor="w")
        box.content = tk.Frame(box, bg=tce.ROW_BG)
        box.content.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        return box

    def _build_ui(self):
        self.frame = tk.Frame(self.master, bg=tce.BG, highlightthickness=0, bd=0)
        self.frame.pack(fill=tk.BOTH, expand=True)
        tk.Frame(self.frame, bg=tce.ORANGE, height=2).pack(side=tk.BOTTOM, fill=tk.X)
        body = tk.Frame(self.frame, bg=tce.BG)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(0, weight=3, uniform="ui")
        body.columnconfigure(1, weight=2, uniform="ui")
        body.columnconfigure(2, weight=3, uniform="ui")
        body.rowconfigure(0, weight=1)

        left = self._display(body, "POZYCJA")
        left.grid(row=0, column=0, sticky="nsew", padx=(MARGIN, 6), pady=(4, 4))
        self.system_info_label = tk.Label(left.content, width=1, text="", font=self.font_info, fg=tce.ORANGE,
                                          bg=tce.ROW_BG, anchor="w", justify=tk.LEFT)
        self.system_info_label.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        center = tk.Frame(body, bg=tce.BG)
        center.grid(row=0, column=1, sticky="nsew")
        self.header = tk.Label(center, text="ED TRADE", font=self.font_tab, fg=tce.TEXT_ON_ORANGE,
                               bg=tce.ORANGE, padx=30)
        self.header.pack(side=tk.TOP)
        self.status_label = tk.Label(center, text="OCZEKIWANIE NA DOKOWANIE", font=self.font_title,
                                     fg=tce.ORANGE_DIM, bg=tce.BG, width=1)
        self.status_label.pack(side=tk.TOP, pady=(2, 0), fill=tk.X)
        self.steps_label = tk.Label(center, width=1, text="", font=self.font_info, fg=tce.ORANGE, bg=tce.BG)
        self.steps_label.pack(side=tk.TOP, fill=tk.X)

        right = self._display(body, "CEL")
        right.grid(row=0, column=2, sticky="nsew", padx=(6, MARGIN), pady=(4, 4))
        # Linia 1: cel (lewo) + skoki/wiek cen/paliwo (prawo); linia 2: towar, ceny, zysk
        top = tk.Frame(right.content, bg=tce.ROW_BG)
        top.pack(fill=tk.X, padx=8, pady=(3, 0))
        self.meta_label = tk.Label(top, text="", font=self.font_info, fg=tce.ORANGE, bg=tce.ROW_BG, anchor="e")
        self.meta_label.pack(side=tk.RIGHT)
        self.dest_label = tk.Label(top, width=1, text="", font=self.font_highlight, fg=tce.TEXT_WHITE,
                                   bg=tce.ROW_BG, anchor="w")
        self.dest_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.route_label = tk.Label(right.content, width=1, text="", font=self.font_info, fg=tce.ORANGE,
                                    bg=tce.ROW_BG, anchor="w")
        self.route_label.pack(fill=tk.X, padx=8, pady=(0, 3))

        self._hide_content()

    def _set_fit(self, label: tk.Label, text: str, **kw) -> None:
        """Ustaw tekst przycięty do szerokości etykiety; po zmianie rozmiaru/skali przycina ponownie."""
        label._full_text = text
        if not getattr(label, "_fit_bound", False):
            label.bind("<Configure>", lambda _e, lb=label: self._refit(lb), add="+")
            label._fit_bound = True
        if kw:
            label.config(**kw)
        self._refit(label)

    def _refit(self, label: tk.Label) -> None:
        text = getattr(label, "_full_text", None)
        if text is None:
            return
        measure = tkfont.nametofont(str(label.cget("font")), root=label).measure
        width = label.winfo_width() - 2 * int(label.cget("padx") or 0) - 4
        fitted = "\n".join(fit_line(line, width, measure) for line in text.split("\n"))
        if label.cget("text") != fitted:
            label.config(text=fitted)

    def _hide_content(self):
        """Wyczyść wyświetlacz celu i checklistę."""
        for label in (self.dest_label, self.route_label, self.steps_label):
            self._set_fit(label, "")
        self.meta_label.config(text="")
        self.route_label.config(fg=tce.ORANGE)

    def update_route(self, route: TradeRoute):
        """Aktualizuj overlay z nową trasą — thread-safe (wołane z wątku watchera)."""
        logger.debug("update_route() CALL: system=%s/%s, profit=%s",
                       getattr(route, 'source_system', '?'),
                       getattr(route, 'destination_system', '?'),
                       getattr(route, 'total_profit', '?'))
        logger.debug("update_route(): setting _update_pending=True, route=%s", route)
        
        # Zapisz timestamp obliczenia trasy (już ustawiany w refresh())
        with self._queue_lock:
            self._route_queue = route
        self._update_pending = True
        # Zaplanuj natychmiastowe odświeżenie w głównym wątku Tkinter
        self.master.after(0, self._on_route_ready)

    def _on_route_ready(self):
        """Wywoływane z mainloop — przenosi trasę z kolejki i odświeża."""
        with self._queue_lock:
            route = self._route_queue
            self._route_queue = None
        if route is not None:
            self.current_route = route
            logger.debug("_on_route_ready(): route moved to current_route, triggering refresh")
        self.refresh()

    def refresh(self):
        """Rzeczywiste odświeżenie widoku (wywoływane z pętli mainloop)."""
        logger.debug("refresh() called, _update_pending=%s, current_route=%s",
                      self._update_pending, self.current_route)
        if not self._update_pending:
            logger.debug("refresh(): no update pending, returning")
            return
        self._update_pending = False
        logger.info("REFRESH: current_route=%s", self.current_route)

        if self.current_route is None:
            self._hide_content()
            self._set_fit(self.status_label, "OCZEKIWANIE NA DOKOWANIE", fg=tce.ORANGE_DIM)
            return

        route = self.current_route
        # Ustaw current_hop jeśli brak
        if not hasattr(route, "_current_hop"):
            route._current_hop = 1

        if route.error:
            self._hide_content()
            self._set_fit(self.route_label, f"BŁĄD: {route.error}".upper(), fg=tce.RED)
            self._set_fit(self.status_label, "BŁĄD TRASY", fg=tce.RED)
            return

        # Pojedynczy wiersz trasy — wyśrodkowany
        # Dodajemy: licznik hopów, skoki FSD, świeżość danych, cargo awareness
        hop_num = getattr(route, '_current_hop', 1)
        hop_info = f"HOP {hop_num}/{route.hops}" if route.hops_list and route.hops > 1 else ""
        steps = getattr(route, '_checklist_text', '')

        # Dane do wyświetlenia — AKTUALNY hop, nie zawsze hop 1 (bug: route.buy_item
        # itp. to zawsze pierwszy hop, a route.destination_system to KONIEC całej
        # trasy — te dwa pola nie są ze sobą powiązane przy hops > 1).
        if route.hops_list and 1 <= hop_num <= len(route.hops_list):
            current_hop = route.hops_list[hop_num - 1]
            display_dest_system = current_hop.destination_system
            display_dest_station = current_hop.destination_station
            display_item = current_hop.commodity
            display_qty = current_hop.amount
            display_buy = current_hop.buy_price
            display_sell = current_hop.sell_price
        else:
            display_dest_system = route.destination_system
            display_dest_station = route.destination_station
            display_item = route.buy_item
            display_qty = route.buy_quantity
            display_buy = route.buy_price
            display_sell = route.sell_price

        meta = []
        meta_color = tce.ORANGE
        if route.jumps > 0:
            meta.append(f"{route.jumps} SKOKI")
        current = route.hops_list[hop_num - 1] if route.hops_list and 1 <= hop_num <= len(route.hops_list) else None
        sell_age = age_hours(current.dst_updated_at) if current is not None else None
        if sell_age is not None:
            meta.append("CENY " + (f"{sell_age:.0f}H" if sell_age < 48 else f"{sell_age / 24:.0f}D"))
        if sell_age is not None:
            # Werdykt etapu (tylko gdy znamy wiek cen celu — bez niego nie zgadujemy): trasa ze Spansh jest zyskowo najlepsza — o OPTIMAL/RISKY decyduje pewność cen celu
            verdict, shade = assess.assess_route_hop(sell_age)
            meta.insert(0, assess.badge_for(verdict, shade))
            meta_color = tce.verdict_color(verdict, shade)
        security = getattr(current, '_security', '') if current is not None else ''
        if security.lower() in ("low", "anarchy"):
            meta.append(f"⚠ {security.upper()} SEC" if security.lower() == "low" else "⚠ ANARCHY")
            meta_color = tce.RED
        if getattr(route, '_scoopable', False):
            meta.append("⛽")
        if self._copied_system and self._copied_system.lower() in ((display_dest_system or "").lower(),
                                                                   (display_dest_station or "").lower()):
            meta.append("✓ W SCHOWKU")

        # Cargo awareness — ostrzeżenie jeśli w ładowni jest coś innego niż towar hopu
        cargo_warning = ""
        if self._player_cargo and display_item and display_qty:
            def norm(name: str) -> str:
                return "".join(ch for ch in name.lower() if ch.isalnum())
            other_items = [f"{i.get('Name_Localised') or i['Name']} x{i['Count']}" for i in self._player_cargo
                           if norm(display_item) not in (norm(i.get('Name', '')), norm(i.get('Name_Localised', '')))
                           and i.get('Count', 0) > 0 and i.get('Name', '').lower() != 'drones'
                           and not i.get('MissionID')]
            if other_items:
                cargo_warning = f"MASZ: {', '.join(other_items)}"

        self._set_fit(self.dest_label, f"{display_dest_system} · {display_dest_station}".upper())
        self.meta_label.config(text="  ·  ".join(meta), fg=meta_color)  # krótkie — bez przycinania
        route_text = (f"{display_item} ×{display_qty}  {display_buy:,} → {display_sell:,}"
                      f"  ·  ZYSK {compact_cr(route.total_profit)} CR")
        if cargo_warning:
            route_text += f"  ·  {cargo_warning}"
        self._set_fit(self.route_label, route_text.upper(), fg=tce.GREEN if route.total_profit > 0 else tce.RED)
        self._set_fit(self.steps_label, "  ".join(t for t in (hop_info, steps.upper()) if t))
        finished = "ukończona" in steps
        check = getattr(route, '_live_check', None)
        if finished:
            self._set_fit(self.status_label, "TRASA UKOŃCZONA", fg=tce.GREEN)
        elif check is not None and check.hop_index == hop_num - 1:
            # Weryfikacja cenami z gry (Market.json po otwarciu rynku): ✓ / ⚠ / ✗
            color = {"ok": tce.GREEN, "warn": tce.VERDICT_COLORS["hold"], "gone": tce.RED}[check.level]
            self._set_fit(self.status_label, check.text, fg=color)
        else:
            self._set_fit(self.status_label, "TRASA AKTYWNA", fg=tce.GREEN)

    def set_polling_status(self, elapsed: int) -> None:
        """Aktualizuj status w czasie pollingu Spansh — thread-safe."""
        self.master.after(0, self._set_polling_status_inner, elapsed)

    def set_player_cargo(self, cargo: list) -> None:
        """Ustaw listę towarów z Cargo.json — thread-safe."""
        self.master.after(0, self._set_player_cargo_inner, cargo)

    def _set_player_cargo_inner(self, cargo: list) -> None:
        """Wywoływane z mainloop — aktualizuje _player_cargo."""
        self._player_cargo = cargo

    def _set_polling_status_inner(self, elapsed: int) -> None:
        """Wywoływane z mainloop — aktualizuje status bez zmiany current_route."""
        if getattr(self.current_route, '_quick', False):
            # Szybka trasa z rynku stacji już jest na pasku — Spansh liczy pełną (wieloetapową)
            self._set_fit(self.status_label, f"SZYBKA TRASA · PEŁNA ZA CHWILĘ… {elapsed}s", fg=tce.GREEN)
        else:
            self._set_fit(self.status_label, f"LICZĘ TRASĘ… {elapsed}s", fg=tce.ORANGE)

    def set_system_info(self, text: str) -> None:
        """Ustaw info o systemie/stacjach — thread-safe. Rejestruje też jako strona rotacji."""
        self.master.after(0, self._set_system_info_inner, text)

    def _set_system_info_inner(self, text: str) -> None:
        """Wywoływane z mainloop — aktualizuje system_info_text i rejestruje stronę 'system'."""
        self._system_info_text = text
        self.register_page('system', lambda: self._system_info_text)
        self._set_fit(self.system_info_label, text.upper())

    def register_page(self, name: str, getter) -> None:
        """Zarejestruj/zaktualizuj stronę rotacji paska (name unikalny, getter: () -> str)."""
        for i, (existing_name, _) in enumerate(self._pages):
            if existing_name == name:
                self._pages[i] = (name, getter)
                return
        self._pages.append((name, getter))

    def _rotate_pages(self) -> None:
        """Pokaż kolejną zarejestrowaną stronę, zaplanuj następną rotację."""
        if self._pages:
            self._page_index = (self._page_index + 1) % len(self._pages)
            name, getter = self._pages[self._page_index]
            try:
                self._set_fit(self.system_info_label, getter().upper())
            except Exception:
                logger.exception('Błąd rotacji strony %s', name)
        self.master.after(8000, self._rotate_pages)

    def mark_copied(self, system: str) -> None:
        """Wołane w wątku Tk: cel trasy jest w schowku — pasek pokaże "✓ W SCHOWKU" przy celu."""
        self._copied_system = system
        self._refresh_now()

    def _refresh_now(self):
        """Wymuś natychmiastowe odświeżenie (inkrementacja hopa itp.)."""
        self._update_pending = True
        self.master.after(0, self.refresh)

    def show(self):
        """Pokaż overlay i uruchom pętlę odświeżania."""
        logger.info("show(): deiconify + start mainloop")
        self.master.deiconify()
        self._schedule_refresh()
        self.master.after(8000, self._rotate_pages)
        self.master.mainloop()

    def _schedule_refresh(self):
        """Zaplanuj odświeżenie w pętli mainloop."""
        self.master.after(50, self.refresh)
