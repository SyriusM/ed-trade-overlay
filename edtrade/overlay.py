"""Overlay — semi-transparent, always-on-top, borderless X11 window.

Displays the best trade route from the current station as a compact
top bar spanning the full screen width. Uses Tkinter with overrideredirect,
-alpha for transparency, and -type splash to avoid stealing focus from the game.
"""

import logging
import threading
import tkinter as tk
from tkinter import font as tkfont
from typing import Optional, Callable

from .trade import TradeRoute

logger = logging.getLogger(__name__)

# Konfiguracja okna — górny pasek pełnej szerokości
WINDOW_HEIGHT = 90
MARGIN = 8
BG_COLOR = "#1a1a2e"
TEXT_COLOR = "#e0e0e0"
ACCENT_COLOR = "#00d4ff"
HIGHLIGHT_COLOR = "#ffd700"
DIM_COLOR = "#888899"
FONT_FAMILY = "monospace"


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

        self.master.configure(bg="#1a1a2e")
        self.master.attributes("-alpha", 0.75)

        # Rozmiar i pozycja — górny pasek pełnej szerokości
        self._apply_geometry()

        # Zablokuj zmianę rozmiaru
        self.master.resizable(False, False)

    def _apply_geometry(self):
        """Ustaw geometrię: pełna szerokość ekranu, mała wysokość u góry."""
        width = self.master.winfo_screenwidth()
        self.master.geometry(f"{width}x{WINDOW_HEIGHT}+0+0")

    def _setup_fonts(self):
        """Czcionki — monospace, kompaktowe dla górnego paska (50px)."""
        self.font_title = tkfont.Font(family=FONT_FAMILY, size=11, weight="bold")
        self.font_info = tkfont.Font(family="monospace", size=10, weight="normal")
        self.font_highlight = tkfont.Font(family="monospace", size=11, weight="bold")
        self.font_small = tkfont.Font(family="monospace", size=9)

    def _build_ui(self):
        """Buduje interfejs overlaya — górny wiersz (nagłówek + info + status) + dolny wiersz (trasa)."""
        self.frame = tk.Frame(
            self.master,
            bg=BG_COLOR,
            highlightthickness=0,
            bd=0,
        )
        self.frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # Górny wiersz: nagłówek + system/stacje (lewo) + status (prawo)
        self.top_row = tk.Frame(self.frame, bg=BG_COLOR, highlightthickness=0, bd=0)
        self.top_row.pack(side=tk.TOP, fill=tk.X, expand=False, padx=0, pady=0)

        self.header = tk.Label(
            self.top_row,
            text='ED TRADE',
            font=self.font_title,
            fg=ACCENT_COLOR,
            bg=BG_COLOR,
            anchor='w',
        )
        self.header.pack(side=tk.LEFT, fill=tk.NONE, expand=False,
                         padx=(MARGIN, MARGIN), pady=0)

        self.system_info_label = tk.Label(
            self.top_row,
            text='',
            font=self.font_small,
            fg=DIM_COLOR,
            bg=BG_COLOR,
            anchor='w',
        )
        self.system_info_label.pack(side=tk.LEFT, fill=tk.X, expand=True,
                                    padx=(0, MARGIN), pady=0)

        self.status_label = tk.Label(
            self.top_row,
            text='Oczekiwanie na Docked...',
            font=self.font_small,
            fg=DIM_COLOR,
            bg=BG_COLOR,
            anchor='e',
        )
        self.status_label.pack(side=tk.RIGHT, fill=tk.NONE, expand=False,
                               padx=(0, MARGIN), pady=0)

        # Separator poziomy między wierszami
        self.hsep = tk.Frame(self.frame, height=1, bg='#333355', highlightthickness=0)
        self.hsep.pack(side=tk.TOP, fill=tk.X, expand=False, padx=0, pady=0)

        # Dolny wiersz: trasa, pełna szerokość
        self.bottom_row = tk.Frame(self.frame, bg=BG_COLOR, highlightthickness=0, bd=0)
        self.bottom_row.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=0, pady=0)

        self.route_label = tk.Label(
            self.bottom_row,
            text='',
            font=self.font_highlight,
            fg=TEXT_COLOR,
            bg=BG_COLOR,
            anchor='center',
        )
        self.route_label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                              padx=MARGIN, pady=0)

        # Ukryj zawartość na start
        self._hide_content()

    def _hide_content(self):
        """Ukryj wszystkie elementy treści."""
        self.route_label.config(text="", fg=TEXT_COLOR)

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
            self.status_label.config(text="Oczekiwanie na Docked...", fg=DIM_COLOR)
            return

        route = self.current_route
        # Ustaw current_hop jeśli brak
        if not hasattr(route, "_current_hop"):
            route._current_hop = 1

        if route.error:
            self._hide_content()
            self.route_label.config(text="Błąd kalkulacji", fg="#ff6b6b")
            self.status_label.config(text="Błąd", fg="#ff6b6b")
            return

        # Pojedynczy wiersz trasy — wyśrodkowany
        # Dodajemy: licznik hopów, skoki FSD, świeżość danych, cargo awareness
        hop_num = getattr(route, '_current_hop', 1)
        hop_info = ""
        if route.hops_list and route.hops > 1:
            # Multi-hop route
            hop_info = f" Hop {hop_num}/{route.hops}"

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

        fsd_jumps_info = ""
        if route.jumps > 0:
            fsd_jumps_info = f" · {route.jumps} skoki"
        
        freshness_info = ""
        if hasattr(route, '_market_freshness_ts') and route._market_freshness_ts:
            import time
            elapsed = int(time.time() - route._market_freshness_ts)
            if elapsed < 60:
                freshness_info = f" ({elapsed}s temu)"
            elif elapsed < 3600:
                freshness_info = f" ({elapsed//60}m temu)"
            else:
                freshness_info = f" ({elapsed//3600}h temu)"
        
        # Cargo awareness — ostrzeżenie jeśli cargo się nie zgadza
        cargo_warning = ""
        if self._player_cargo and display_item and display_qty:
            # Sprawdź czy gracz ma towar inny niż sugerowana trasa
            has_other_cargo = any(
                item.get('Name', '').lower() != display_item.lower()
                and item.get('Count', 0) > 0
                for item in self._player_cargo
            )
            if has_other_cargo:
                other_items = [f"{i['Name']} x{i['Count']}" for i in self._player_cargo if i.get('Count', 0) > 0]
                cargo_warning = f" [Masz: {', '.join(other_items)}]"
        
        route_text = (
            f"-> {display_dest_system} "
            f"[{display_dest_station}]{hop_info}{fsd_jumps_info} "
            f"{display_item} x{display_qty} "
            f"@ {display_buy:,}cr "
            f"--> {display_sell:,}cr "
            f"| Zysk: {route.total_profit:,}cr{cargo_warning}"
        )
        if freshness_info:
            route_text += f" {freshness_info}"
        if getattr(route, '_scoopable', False):
            route_text += " ⛽"
        profit_color = "#00ff88" if route.total_profit > 0 else "#ff6b6b"
        self.route_label.config(text=route_text, fg=profit_color)
        self.status_label.config(text="Trasa obliczona", fg="#00ff88")
        logger.debug("refresh(): status_label set to 'Trasa obliczona'")

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
        self.status_label.config(
            text=f"Liczenie trasy... ({elapsed}s)",
            fg=ACCENT_COLOR,
        )

    def set_system_info(self, text: str) -> None:
        """Ustaw info o systemie/stacjach — thread-safe. Rejestruje też jako strona rotacji."""
        self.master.after(0, self._set_system_info_inner, text)

    def _set_system_info_inner(self, text: str) -> None:
        """Wywoływane z mainloop — aktualizuje system_info_text i rejestruje stronę 'system'."""
        self._system_info_text = text
        self.register_page('system', lambda: self._system_info_text)
        self.system_info_label.config(text=text)

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
                self.system_info_label.config(text=getter())
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
