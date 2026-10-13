"""Overlay — semi-transparent, always-on-top, borderless X11 window.

Displays the best trade route from the current station as a compact
top bar spanning the full screen width. Uses Tkinter with overrideredirect,
-alpha for transparency, and -type splash to avoid stealing focus from the game.
"""

import logging
import threading
import tkinter as tk
from typing import Optional, Callable

from . import tce_theme as tce
from .trade import TradeRoute

logger = logging.getLogger(__name__)

# Górny pasek pełnej szerokości w układzie MAIN UI z TCE: POZYCJA | status trasy | CEL
WINDOW_HEIGHT = 84
MARGIN = 8


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
        self.system_info_label = tk.Label(left.content, text="", font=self.font_info, fg=tce.ORANGE,
                                          bg=tce.ROW_BG, anchor="w", justify=tk.LEFT)
        self.system_info_label.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        center = tk.Frame(body, bg=tce.BG)
        center.grid(row=0, column=1, sticky="nsew")
        self.header = tk.Label(center, text="ED TRADE", font=self.font_tab, fg=tce.TEXT_ON_ORANGE,
                               bg=tce.ORANGE, padx=30)
        self.header.pack(side=tk.TOP)
        self.status_label = tk.Label(center, text="OCZEKIWANIE NA DOKOWANIE", font=self.font_title,
                                     fg=tce.ORANGE_DIM, bg=tce.BG)
        self.status_label.pack(side=tk.TOP, pady=(2, 0))
        self.steps_label = tk.Label(center, text="", font=self.font_info, fg=tce.ORANGE, bg=tce.BG)
        self.steps_label.pack(side=tk.TOP)

        right = self._display(body, "CEL")
        right.grid(row=0, column=2, sticky="nsew", padx=(6, MARGIN), pady=(4, 4))
        self.dest_label = tk.Label(right.content, text="", font=self.font_highlight, fg=tce.TEXT_WHITE,
                                   bg=tce.ROW_BG, anchor="w")
        self.dest_label.pack(fill=tk.X, padx=8, pady=(3, 0))
        self.route_label = tk.Label(right.content, text="", font=self.font_info, fg=tce.ORANGE,
                                    bg=tce.ROW_BG, anchor="w")
        self.route_label.pack(fill=tk.X, padx=8, pady=(0, 3))

        self._hide_content()

    def _hide_content(self):
        """Wyczyść wyświetlacz celu i checklistę."""
        self.dest_label.config(text="")
        self.route_label.config(text="", fg=tce.ORANGE)
        self.steps_label.config(text="")

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
            self.status_label.config(text="OCZEKIWANIE NA DOKOWANIE", fg=tce.ORANGE_DIM)
            return

        route = self.current_route
        # Ustaw current_hop jeśli brak
        if not hasattr(route, "_current_hop"):
            route._current_hop = 1

        if route.error:
            self._hide_content()
            self.route_label.config(text=f"BŁĄD: {route.error}".upper(), fg=tce.RED)
            self.status_label.config(text="BŁĄD TRASY", fg=tce.RED)
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

        extras = []
        if route.jumps > 0:
            extras.append(f"{route.jumps} SKOKI")
        if getattr(route, '_market_freshness_ts', None):
            import time
            elapsed = int(time.time() - route._market_freshness_ts)
            extras.append(f"{elapsed}s temu" if elapsed < 60 else
                          f"{elapsed // 60}m temu" if elapsed < 3600 else f"{elapsed // 3600}h temu")
        if getattr(route, '_scoopable', False):
            extras.append("⛽")

        # Cargo awareness — ostrzeżenie jeśli w ładowni jest coś innego niż towar hopu
        if self._player_cargo and display_item and display_qty:
            other_items = [f"{i['Name']} x{i['Count']}" for i in self._player_cargo
                           if i.get('Name', '').lower() != display_item.lower() and i.get('Count', 0) > 0]
            if other_items:
                extras.append(f"[MASZ: {', '.join(other_items)}]")

        self.dest_label.config(text=f"{display_dest_system} · {display_dest_station}".upper())
        route_text = (f"{display_item} ×{display_qty}  {display_buy:,} → {display_sell:,} CR"
                      f"  ·  ZYSK {route.total_profit:,} CR")
        if extras:
            route_text += "  ·  " + "  ".join(extras)
        self.route_label.config(text=route_text.upper(), fg=tce.GREEN if route.total_profit > 0 else tce.RED)
        self.steps_label.config(text="  ".join(t for t in (hop_info, steps.upper()) if t))
        finished = "ukończona" in steps
        self.status_label.config(text="TRASA UKOŃCZONA" if finished else "TRASA AKTYWNA", fg=tce.GREEN)

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
        self.status_label.config(text=f"LICZĘ TRASĘ… {elapsed}s", fg=tce.ORANGE)

    def set_system_info(self, text: str) -> None:
        """Ustaw info o systemie/stacjach — thread-safe. Rejestruje też jako strona rotacji."""
        self.master.after(0, self._set_system_info_inner, text)

    def _set_system_info_inner(self, text: str) -> None:
        """Wywoływane z mainloop — aktualizuje system_info_text i rejestruje stronę 'system'."""
        self._system_info_text = text
        self.register_page('system', lambda: self._system_info_text)
        self.system_info_label.config(text=text.upper())

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
                self.system_info_label.config(text=getter().upper())
            except Exception:
                logger.exception('Błąd rotacji strony %s', name)
        self.master.after(8000, self._rotate_pages)

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
