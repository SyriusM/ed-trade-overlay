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
import time
from pathlib import Path

from .watcher import JournalWatcher
from .trade import TradeEngine
from .overlay import TradeOverlay
from .panel import TradePanel
from .window_watch import get_active_window
from . import market_cache
from .market_cache import init_market_cache
from . import config as user_config_module
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
        self.panel = None
        if self.overlay is not None and not args.no_panel:
            try:
                self.panel = TradePanel(self.overlay.master, user_config=self.user_config)
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
            on_location=self._on_location,
            on_market=self._on_market,
        )
        self._dock_count = 0
        self._last_system = ""
        self._last_station = ""
        self._last_capacity = 0.
        self._last_active_class: Optional[str] = None
        self._bar_visible: bool = True

        # Podłącz callback pollingu do overlaya
        if self.overlay:
            self.trade_engine.set_polling_callback(
                lambda elapsed: self.overlay.set_polling_status(elapsed)
            )

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

        # Sprawdź, czy capacity faktycznie się zmieniła
        if capacity <= 0 or capacity == self._last_capacity:
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

        if self.overlay:
            self.overlay.update_route(route)
        logger.info("Trasa po Loadout: %s", route.summary())
        self._last_capacity = capacity

    def _on_cargo(self, event: dict):
        """Reaguje na event Cargo — przesyła listę towarów do overlaya."""
        if self.overlay:
            cargo_list = event.get("Cargo", [])
            self.overlay.set_player_cargo(cargo_list)
            logger.debug("Cargo event: %d pozycji", len(cargo_list))

    def _on_location(self, event: dict):
        """Reaguje na event Location — inkrementuje _current_hop gdy gracz
        dotrze do kolejnego hopu trasy."""
        system = event.get("StarSystem", "")
        if not system or not self.overlay or not self.overlay.current_route:
            return

        route = self.overlay.current_route
        # Sprawdź czy system to kolejny hop
        if route.hops_list:
            next_hop_num = getattr(route, '_current_hop', 1)
            if next_hop_num < len(route.hops_list):
                next_hop = route.hops_list[next_hop_num]
                if next_hop.destination_system == system:
                    route._current_hop = next_hop_num + 1
                    logger.info(
                        "Hop advanced: %d → %d (system=%s)",
                        next_hop_num, next_hop_num + 1, system,
                    )
                    # wymuś natychmiastowe odświeżenie overlaya
                    self.overlay._refresh_now()

    def _on_docked(self, event: dict):
        """Reaguje na event Docked — wylicza najlepszą trasę."""
        system = event.get("StarSystem", "")
        station = event.get("StationName", "")

        if not system or not station:
            logger.warning("Docked bez system/stacja: %s", event)
            return

        # Unikaj redundancyjnych wyliczeń — ten sam system/stacja
        key = f"{system}/{station}"
        if key == self._last_system:
            return
        self._last_system = key

        self._dock_count += 1
        logger.info("Docked #%d: %s/%s", self._dock_count, system, station)

        # Wylicz trasę przez Spansh API (nie blokuje overlaya)
        route = self.trade_engine.calculate_route_via_spansh(system, station)

        # Pobierz info o systemie i stacjach
        try:
            system_id64 = str(event.get('SystemAddress', ''))
            info_parts = []
            if system_id64:
                from .trade import get_system_info, search_stations
                sys_info = get_system_info(system_id64)
                if sys_info.name:
                    info_parts.append(f'{sys_info.name} | {sys_info.allegiance} | sec:{sys_info.security}')
            stations = search_stations(system)
            if stations:
                info_parts.append(f'{len(stations)} stacji')
            if info_parts and self.overlay:
                self.overlay.set_system_info(' | '.join(info_parts))
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
                from .trade import find_material_traders
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
                from .trade import find_mining_hotspots, find_mineral_buyers
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

        if route.error:
            logger.error("Błąd kalkulacji: %s", route.error)

        # Aktualizuj overlay
        if self.overlay:
            self.overlay.update_route(route)
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

    def _apply_bar_visibility(self, window_class: Optional[str]) -> None:
        """Gdy włączone bar_only_when_game_focused: pasek widoczny tylko, gdy aktywne okno ma klasę game_window_class."""
        if self.overlay is None:
            return
        if not self.user_config.get('bar_only_when_game_focused', False):
            if not self._bar_visible:
                self.overlay.master.deiconify()
                self._bar_visible = True
                logger.info("Pasek: przywrócony (tryb 'tylko przy grze' wyłączony)")
            return
        if window_class is None:
            return
        game_class = self.user_config.get('game_window_class', '')
        want_visible = bool(game_class) and window_class == game_class
        if want_visible == self._bar_visible:
            return
        self._bar_visible = want_visible
        if want_visible:
            self.overlay.master.deiconify()
        else:
            self.overlay.master.withdraw()
        logger.info("Pasek: %s (aktywne okno: %r)", "pokazany" if want_visible else "ukryty", window_class)

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
            sys.exit(0)

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        # Uruchom watchera w osobnym wątku, overlay w głównym
        import threading

        watcher_thread = threading.Thread(
            target=self.watcher.run,
            args=(self.args.poll_interval,),
            daemon=True,
        )
        watcher_thread.start()

        logger.info("Watcher uruchomiony w wątku, overlay w mainloop")
        if self._show_overlay:
            self.overlay.master.after(1000, self._poll_active_window)
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
