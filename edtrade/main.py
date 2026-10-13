"""ED Trade Overlay — main entry point.

Łączy:
  1. JournalWatcher  → wykrywa Docked/Loadout z pliku journala ED
  2. TradeEngine     → wywołuje Trade Dangerous do kalkulacji trasy
  3. TradeOverlay    → wyświetla wynik w przezroczystym oknie X11
"""

import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path

from .watcher import JournalWatcher
from .filters import filter_from_config
from .trade import (TradeEngine, ship_needs_large_pad, get_system_info, search_stations, find_material_traders,
                    find_mining_hotspots, find_mineral_buyers)
from .overlay import TradeOverlay
from .bottom_bar import BottomBar
from .destination import get_destination_info
from .hotkeys import PANEL_PAGES, HotkeyManager
from .panel import PANEL_WINDOW_CLASS, TradePanel
from .window_watch import get_active_window
from . import market_cache
from .market_cache import init_market_cache
from . import config as user_config_module
from .checklist import RouteChecklist, load_commodity_names
from typing import Optional

logger = logging.getLogger("edto")

# Domyślna konfiguracja
DEFAULT_TD_DIR = Path.home() / "Projekty" / "trade-dangerous"
DEFAULT_JOURNAL_DIR = (
    Path.home()
    / ".local"
    / "share"
    / "Steam"
    / "steamapps"
    / "compatdata"
    / "359320"
    / "pfx"
    / "drive_c"
    / "users"
    / "steamuser"
    / "Saved Games"
    / "Frontier Developments"
    / "Elite Dangerous"
)


def parse_args():
    parser = argparse.ArgumentParser(description="ED Trade Overlay MVP")
    parser.add_argument(
        "--td-dir",
        type=Path,
        default=DEFAULT_TD_DIR,
        help="Ścieżka do katalogu Trade Dangerous",
    )
    parser.add_argument(
        "--journal-dir",
        type=Path,
        default=DEFAULT_JOURNAL_DIR,
        help="Ścieżka do katalogu z journalami ED",
    )
    parser.add_argument(
        "--capacity",
        type=float,
        default=304.0,
        help="Pojemność ładunkowa statku (t)",
    )
    parser.add_argument(
        "--credits",
        type=int,
        default=100_000,
        help="Dostępne kredyty (cr)",
    )
    parser.add_argument(
        "--ly-per",
        type=float,
        default=32.0,
        help="Maks. zasięg skoku FSD (ly), nadpisze Loadout",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Interwał sprawdzania journala (s)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Poziom logowania",
    )
    parser.add_argument(
        "--no-overlay",
        action="store_true",
        help="Uruchom bez overlaya — tylko kalkulacja trasy i log",
    )
    parser.add_argument(
        "--no-panel",
        action="store_true",
        help="Nie otwieraj panelu TCE (osobne okno z zakładkami)",
    )
    return parser.parse_args()


class EDTradeOverlayApp:
    """Główna aplikacja — integruje watcher, engine i overlay."""

    def __init__(self, args):
        self.args = args
        self.trade_engine = TradeEngine(
            td_dir=args.td_dir,
            capacity=args.capacity,
            credits=args.credits,
            ly_per=args.ly_per,
        )
        self._show_overlay = not args.no_overlay
        self.user_config = user_config_module.load_user_config()
        self.overlay = TradeOverlay() if self._show_overlay else None
        self.bottom_bar = BottomBar(self.overlay.master, self.overlay.fonts) if self.overlay is not None else None
        if self.overlay is not None:
            self._apply_appearance(float(self.user_config.get('bar_alpha', 0.75)),
                                   float(self.user_config.get('bar_font_scale', 1.0)))
        self.panel = None
        if self.overlay is not None and not args.no_panel:
            try:
                self.panel = TradePanel(self.overlay.master, user_config=self.user_config,
                                        on_appearance_change=self._apply_appearance,
                                        bar_margins=self._bar_margins)
                logger.info("TradePanel utworzony (zakładki: System/Materiały/Mining/Journey)")
            except Exception:
                logger.exception("Nie udało się utworzyć TradePanel")
        self._market_conn = init_market_cache(
            Path.home() / ".local" / "share" / "ed-trade-overlay" / "market_cache.db"
        )
        self.watcher = JournalWatcher(
            journal_dir=args.journal_dir,
            on_docked=self._on_docked,
            on_loadout=self._on_loadout,
            on_cargo=self._on_cargo,
            on_market=self._on_market,
            on_materials=self._on_materials,
            on_trade=self._on_trade,
        )
        self._dock_count = 0
        self._last_system = ""
        self._last_station = ""
        self._last_capacity = 0.
        self._last_active_class: Optional[str] = None
        self._bar_visible: bool = True
        self.checklist: Optional[RouteChecklist] = None
        self._commodity_names: dict[str, str] = {}
        self._cargo: list[dict] = []
        self._ship_large_pad = False
        self._destination_key: Optional[tuple] = None
        self.hotkeys: Optional[HotkeyManager] = None
        if self.overlay is not None:
            self.hotkeys = HotkeyManager(self.overlay.master, self.user_config, self._hotkey_actions())
            if self.panel is not None:
                self.hotkeys.bind_tk(self.panel.window)

        # Podłącz callback pollingu do overlaya
        if self.overlay:
            self.trade_engine.set_polling_callback(
                lambda elapsed: self.overlay.set_polling_status(elapsed)
            )

    def _apply_appearance(self, alpha: float, font_scale: float) -> None:
        """CONTROL: przezroczystość i skala — wspólne dla górnego i dolnego paska."""
        self.overlay.apply_appearance(alpha, font_scale)
        if self.bottom_bar is not None:
            self.bottom_bar.apply_appearance(alpha, font_scale)

    def _bar_margins(self) -> tuple[int, int]:
        """Wysokość widocznych pasków (góra, dół) — panel otwierany skrótem ich nie zasłania."""
        top = self.overlay._height if self.overlay and self.overlay.slider.visible else 0
        bottom = self.bottom_bar.height() if self.bottom_bar and self.bottom_bar.slider.visible else 0
        return top, bottom

    def _hotkey_actions(self) -> dict:
        actions = {'top_bar': lambda _slot: self.overlay.slider.toggle_user()}
        if self.bottom_bar is not None:
            actions['bottom_bar'] = lambda _slot: self.bottom_bar.slider.toggle_user()
        if self.panel is not None:
            for page in PANEL_PAGES:
                actions[page] = lambda slot, page=page: self.panel.toggle_page(page, slot)
        return actions

    def _update_destination(self) -> None:
        """Karta stacji docelowej bieżącego hopu na dolnym pasku (sieć w wątku roboczym)."""
        if self.bottom_bar is None:
            return
        hop = None
        if self.checklist is not None and not self.checklist.finished and self.checklist.hops:
            hop = self.checklist.hops[min(self.checklist.hop_index, len(self.checklist.hops) - 1)]
        key = (hop.destination_system, hop.destination_station) if hop else None
        if key == self._destination_key:
            return
        self._destination_key = key
        if hop is None:
            self.overlay.master.after(0, self.bottom_bar.show_waiting)
            return
        self.overlay.master.after(0, self.bottom_bar.show_loading, *key)

        def work():
            info = get_destination_info(hop.destination_system, hop.destination_station,
                                        system_id64=getattr(hop, '_destination_id64', ''),
                                        distance_ly=hop.distance or None,
                                        market_updated_ts=getattr(hop, '_destination_market_ts', 0))
            if self._destination_key == key:
                self.overlay.master.after(0, self.bottom_bar.show_destination, info)

        threading.Thread(target=work, daemon=True, name='destination').start()

    def _on_loadout(self, event: dict):
        """Reaguje na event Loadout — aktualizuje pojemność i MaxJumpRange.

        Jeśli capacity się zmieniła i użytkownik jest nadal zadokowany
        w tej samej stacji co ostatnia obliczona trasa — przelicza trasę
        z nową pojemnością.
        """
        capacity = event.get("CargoCapacity", event.get("Capacity", 0))
        ship = event.get("Ship", "unknown")
        max_jump_range = event.get("MaxJumpRange", 0.0)
        logger.info("Loadout: statek=%s, capacity=%.1f, max_jump=%.1f", ship, capacity, max_jump_range)

        # Aktualizuj parametry statku
        if capacity > 0:
            self.trade_engine.capacity = capacity
        if max_jump_range > 0:
            self.trade_engine.ly_per = max_jump_range
        self._ship_large_pad = ship_needs_large_pad(ship)
        was_large = self.trade_engine.requires_large_pad
        self._apply_market_filter()
        pad_changed = was_large != self.trade_engine.requires_large_pad
        logger.info("Loadout: %s — trasy tylko przez stacje z padem L: %s", ship, self.trade_engine.requires_large_pad)
        if self.panel is not None:
            self.panel.update_context(ship=ship, capacity=capacity, jump_range=max_jump_range,
                                      ship_large_pad=self._ship_large_pad)

        # Przelicz, gdy zmieniła się pojemność albo wymagany pad (zmiana statku)
        if capacity <= 0 or (capacity == self._last_capacity and not pad_changed):
            return

        # Sprawdź, czy użytkownik jest nadal w tej samej stacji
        if not self._last_system:
            logger.debug("Loadout: brak aktywnej trasy — pomijam przeliczenie")
            return

        # Przelicz trasę z nową pojemnością
        key = self._last_system
        system, station = key.split("/", 1)
        logger.info(
            "Loadout: capacity %.1f → %.1f, przeliczam trasę dla %s",
            self._last_capacity, capacity, key,
        )
        route = self.trade_engine.calculate_route_via_spansh(system, station)

        if route.error:
            logger.error("Błąd przeliczenia trasy po Loadout: %s", route.error)

        self._publish_route(route, system, station)
        logger.info("Trasa po Loadout: %s", route.summary())
        self._last_capacity = capacity

    def _on_cargo(self, event: dict):
        """Reaguje na event Cargo — przesyła listę towarów do overlaya."""
        self._cargo = event.get("Inventory") or []
        if self.overlay:
            self.overlay.set_player_cargo(self._cargo)
        if self.panel is not None:
            self.panel.update_context(cargo=self._cargo)
        logger.debug("Cargo: %d pozycji", len(self._cargo))

    def _apply_market_filter(self):
        """Filtry z configu (Ustawienia mogą je zmienić w trakcie) + rozmiar statku → parametry trasy."""
        market_filter = filter_from_config(self.user_config, self._ship_large_pad)
        self.trade_engine.requires_large_pad = market_filter.requires_large_pad
        self.trade_engine.max_star_ls = market_filter.max_star_ls
        return market_filter

    def _publish_route(self, route, system: str, station: str) -> None:
        """Nowa trasa → nowa checklista (kup → leć → sprzedaj) i wysłanie do overlaya."""
        self.checklist = None
        if not route.error and route.hops_list:
            if not self._commodity_names:
                self._commodity_names = load_commodity_names()
            self.checklist = RouteChecklist(
                route, self._commodity_names,
                cargo=self._cargo or self.watcher._player_cargo,
                docked=(system, station),
            )
            logger.info("Checklista: %s", self.checklist.status_text())
        if self.overlay:
            self.overlay.update_route(route)
        if self.panel is not None:
            self.panel.show_route(route)
        self._update_destination()

    def _feed_checklist(self, event: dict) -> None:
        if self.checklist is None or not self.checklist.on_event(event):
            return
        logger.info("Checklista: hop %d/%d %s", self.checklist.hop_index + 1,
                    len(self.checklist.hops), self.checklist.status_text())
        if self.overlay:
            self.overlay._refresh_now()
        if self.panel is not None:
            self.panel.show_route(self.checklist.route)
        self._update_destination()

    def _on_trade(self, event: dict):
        """MarketBuy/MarketSell — odhaczanie kroków; po ukończeniu trasy od razu następna z bieżącej stacji."""
        was_finished = self.checklist is None or self.checklist.finished
        self._feed_checklist(event)
        if not was_finished and self.checklist.finished and "/" in self._last_system:
            system, station = self._last_system.split("/", 1)
            logger.info("Trasa ukończona — liczę następną z %s/%s", system, station)
            self._last_system = ""
            self._on_docked({"StarSystem": system, "StationName": station})

    def _on_docked(self, event: dict):
        """Reaguje na event Docked — wylicza najlepszą trasę."""
        system = event.get("StarSystem", "")
        station = event.get("StationName", "")

        if not system or not station:
            logger.warning("Docked bez system/stacja: %s", event)
            return

        self._feed_checklist(event)
        following = self.checklist is not None and self.checklist.follows_plan(system, station)
        if self.panel is not None:
            self.panel.update_context(system=system, station=station)

        # Unikaj redundancyjnych wyliczeń — ten sam system/stacja
        key = f"{system}/{station}"
        if key == self._last_system:
            return
        self._last_system = key

        self._dock_count += 1
        logger.info("Docked #%d: %s/%s", self._dock_count, system, station)

        # Panel: rynek bieżącej stacji od razu, przed długim liczeniem trasy w Spansh
        if self.panel is not None:
            try:
                self.panel.show_docked_station(system, station)
            except Exception:
                logger.exception("Błąd przekazania stacji do panelu")

        # Dokowanie w celu bieżącego hopu = gracz realizuje plan — nie nadpisujemy trasy
        route = None
        if following:
            logger.info("Docked w celu hopu %d — trasa w toku, bez przeliczania", self.checklist.hop_index + 1)
        else:
            self._apply_market_filter()
            route = self.trade_engine.calculate_route_via_spansh(system, station)

        # Pobierz info o systemie i stacjach
        try:
            system_id64 = str(event.get('SystemAddress', ''))
            info_parts = []
            if system_id64:
                sys_info = get_system_info(system_id64)
                if sys_info.name:
                    info_parts.append(f'{sys_info.allegiance} | sec:{sys_info.security}')
            stations = search_stations(system)
            if stations:
                info_parts.append(f'{len(stations)} stacji')
            if self.overlay:
                self.overlay.set_system_info(f'{system} · {station}\n' + ' | '.join(info_parts))
        except Exception:
            logger.exception('Błąd automatu stacje/system przy Docked')

        # Automat journey (pkt 3) — tylko jeśli skonfigurowany cel
        try:
            target = self.user_config.get('journey_target_system', '')
            if target and self.overlay:
                ship_range = self.user_config.get('ship_range_ly', 30.0)
                plan = self.trade_engine.plan_journey(system, target, ship_range)
                if not plan.error:
                    text = f'-> {plan.end_system}: {plan.total_jumps} skokow, {plan.total_distance:.0f} ly'
                    self.overlay.register_page('journey', lambda t=text: t)
        except Exception:
            logger.exception('Błąd automatu journey przy Docked')

        # Automat materiały (pkt 4) — tylko jeśli skonfigurowany kind
        try:
            material_kind = self.user_config.get('material_kind', '')
            if material_kind and self.overlay:
                traders = find_material_traders(system, material_kind, max_ly=50, size=5)
                if traders:
                    names = ', '.join(t.name for t in traders[:3])
                    text = f'Materialy({material_kind}): {names}'
                    self.overlay.register_page('materials', lambda t=text: t)
        except Exception:
            logger.exception('Błąd automatu materiały przy Docked')

        # Automat mining (pkt 5) — tylko jeśli skonfigurowany mineral
        try:
            mineral = self.user_config.get('mining_mineral', '')
            if mineral and self.overlay:
                hotspots = find_mining_hotspots(system, mineral, max_ly=50, size=3)
                buyers = find_mineral_buyers(mineral, system, max_ly=60, size=3)
                parts = []
                if hotspots:
                    h = hotspots[0]
                    parts.append(f'{mineral}: {h.body_name} ({h.count}x)')
                if buyers:
                    b = buyers[0]
                    parts.append(f'sprzedaj: {b.station_name} {b.sell_price:,}cr')
                if parts:
                    text = ' | '.join(parts)
                    self.overlay.register_page('mining', lambda t=text: t)
        except Exception:
            logger.exception('Błąd automatu mining przy Docked')

        if route is None:
            return
        if route.error:
            logger.error("Błąd kalkulacji: %s", route.error)

        self._publish_route(route, system, station)
        logger.info("Trasa: %s", route.summary())

        # Zapisz capacity użyte do obliczenia trasy
        self._last_capacity = self.trade_engine.capacity

    def _on_market(self, event: dict):
        """Reaguje na event Market — aktualizuje cache z cenami rynkowymi."""
        try:
            market_cache.update_market_cache_from_journal(
                self._market_conn,
                self.watcher.journal_dir,
                event.get("MarketID"),
                timestamp=time.time(),
                star_system=event.get("StarSystem", ""),
                station_name=event.get("StationName", ""),
            )
        except Exception:
            logger.exception("Błąd w _on_market")

    def _on_materials(self, event: dict):
        """Reaguje na event Materials (start gry) — stan materiałów do zakładki Inżynieria."""
        if self.panel is not None:
            self.panel.set_materials(event)

    def _apply_bar_visibility(self, window_class: Optional[str]) -> None:
        """Gdy włączone bar_only_when_game_focused: paski widoczne tylko, gdy fokus ma gra (albo panel aplikacji).

        To drugi, niezależny od skrótów powód widoczności (SlidingBar.auto_visible) — pasek schowany
        skrótem zostaje schowany, gdy gra wraca na wierzch."""
        if self.overlay is None:
            return
        if not self.user_config.get('bar_only_when_game_focused', False):
            want_visible = True
        elif window_class is None:
            return
        else:
            game_class = self.user_config.get('game_window_class', '')
            ours = window_class.lower() == PANEL_WINDOW_CLASS.lower()
            want_visible = ours or (bool(game_class) and window_class == game_class)
        if want_visible == self._bar_visible:
            return
        self._bar_visible = want_visible
        for bar in (self.overlay, self.bottom_bar):
            if bar is not None:
                bar.slider.set_auto(want_visible)
        logger.info("Paski: %s (aktywne okno: %r)", "pokazane" if want_visible else "ukryte", window_class)

    def _poll_active_window(self) -> None:
        """Co sekundę odczytaj klasę aktywnego okna; zaloguj tylko ZMIANĘ (bez tytułów — mogą zawierać prywatne dane)."""
        try:
            active = get_active_window()
            window_class = active[0] if active else None
            if window_class != self._last_active_class:
                logger.info("Aktywne okno: class=%r", window_class)
                self._last_active_class = window_class
            self._apply_bar_visibility(window_class)
        except Exception:
            logger.exception("Błąd pollingu aktywnego okna")
        finally:
            if self.overlay is not None:
                self.overlay.master.after(1000, self._poll_active_window)

    def run(self):
        """Uruchom aplikację."""
        logger.info("ED Trade Overlay startuje")
        logger.info("  TD dir: %s", self.args.td_dir)
        logger.info("  Journal dir: %s", self.args.journal_dir)
        logger.info("  Capacity: %.1f t | Ly-per: %.1f", self.args.capacity, self.args.ly_per)

        # Obsługa sygnałów — czyste zamknięcie
        def _signal_handler(sig, frame):
            logger.info("Sygnał %s — zamykanie", sig)
            self.watcher.stop()
            if self.hotkeys is not None:
                self.hotkeys.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        # Uruchom watchera w osobnym wątku, overlay w głównym
        watcher_thread = threading.Thread(
            target=self.watcher.run,
            args=(self.args.poll_interval,),
            daemon=True,
        )
        watcher_thread.start()

        logger.info("Watcher uruchomiony w wątku, overlay w mainloop")
        if self._show_overlay:
            self.overlay.master.after(1000, self._poll_active_window)
            self.hotkeys.start_socket()
            self.hotkeys.start_global_listener()
            self.bottom_bar.slider.apply(animate=True)
            self.overlay.show()
        else:
            logger.info("Uruchomiono w trybie --no-overlay — brak okna")

        # Pętla główna — trzyma proces żywy, aż sygnał
        import time

        while True:
            time.sleep(1)


def main():
    args = parse_args()

    # Konfiguracja logowania
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    app = EDTradeOverlayApp(args)
    app.run()


if __name__ == "__main__":
    main()
