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
from .filters import filter_from_config
from .trade import market_from_market_json, nearby_candidates_from_market, rank_trades, Hop, TradeRoute
from .trade import (TradeEngine, ship_needs_large_pad, get_system_info, search_stations, find_material_traders,
                    get_station_market, age_hours, travel_seconds,
                    find_mining_hotspots, find_mineral_buyers)
from .overlay import TradeOverlay, compact_cr
from .session import SessionLedger
from .pilot import PilotCalibration
from .price_db import PriceDB
from .eddn import EDDNListener
from . import assess, verify
from . import trade as trade_module
from datetime import datetime, timezone
import threading
from .panel import TradePanel
from .window_watch import get_active_window
from . import market_cache
from .market_cache import init_market_cache
from . import config as user_config_module
from .checklist import RouteChecklist, load_commodity_names, load_commodity_ids
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


def _epoch(updated_at) -> float:
    """ISO z Ardent / Market.json → epoch s (0 = nieznane)."""
    try:
        ts = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).timestamp()


def stations_word(n: int) -> str:
    """Polska odmiana: 1 stacja, 2–4 stacje, 5+ stacji (12–14 stacji)."""
    if n == 1:
        return "1 stacja"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} stacje"
    return f"{n} stacji"


def copy_text(system: str, station: str, mode: str) -> str:
    """Tekst do schowka: 'station' → stacja, 'system' → system, 'both' → "Stacja (System)". Bez stacji → system."""
    if not station or mode == 'system':
        return system
    if mode == 'both' and system:
        return f"{station} ({system})"
    return station


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
        assess.set_display(self.user_config.get('verdict_icons', True), self.user_config.get('verdict_labels', True))
        trade_module.set_risk_profile(str(self.user_config.get('risk_profile', 'auto')))
        trade_module.set_security_prefs(float(self.user_config.get('security_weight', 0.5)),
                                        bool(self.user_config.get('avoid_low_security', False)))
        self.overlay = TradeOverlay() if self._show_overlay else None
        if self.overlay is not None:
            self.overlay.apply_appearance(float(self.user_config.get('bar_alpha', 0.75)),
                                          float(self.user_config.get('bar_font_scale', 1.0)))
        self.panel = None
        if self.overlay is not None and not args.no_panel:
            try:
                self.panel = TradePanel(self.overlay.master, user_config=self.user_config,
                                        on_appearance_change=self.overlay.apply_appearance,
                                        on_verdict_display_change=self.overlay._refresh_now)
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
            on_session=self._on_session,
        )
        self._dock_count = 0
        self._last_system = ""
        self._last_station = ""
        self._last_capacity = 0.
        self._last_active_class: Optional[str] = None
        self._bar_visible: bool = True
        self._focus_warned = False
        self._hidden_bars: list = []
        self.checklist: Optional[RouteChecklist] = None
        self._commodity_names: dict[str, str] = {}
        self._commodity_ids: dict[int, str] = {}
        self._cargo: list[dict] = []
        self._ship_large_pad = False
        self.session = SessionLedger()
        self.eddn = None
        if self.user_config.get('eddn_enabled', True) and EDDNListener.available():
            try:
                trade_module.PRICE_DB = PriceDB()
                self.eddn = EDDNListener(trade_module.PRICE_DB)
                self.eddn.start()
            except Exception:
                logger.exception("EDDN: start nasłuchu")
        self.pilot = PilotCalibration()
        trade_module.set_pilot_factor(self.pilot.factor)
        if self.panel is not None:
            self.panel.show_pilot(self.pilot.describe())
        self._copied_system = ""
        self._live_market = None
        self._dock_generation = 0
        self._full_route_generation = 0
        self._quick_route_of = None  # (generation, TradeRoute) — szybka trasa z ostatniego dokowania

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
        if trade_module.PRICE_DB is not None and not route.error and route.hops_list:
            if not self._commodity_names:
                self._commodity_names = load_commodity_names()
            symbol_of = {v.lower(): k for k, v in self._commodity_names.items()}
            n = verify.refresh_route_from_db(route, trade_module.PRICE_DB, symbol_of)
            if n:
                logger.info("EDDN: %d cen na trasie zastąpionych świeższymi", n)
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
        self._copied_system = ""  # nowa trasa → skopiuj cel nawet, jeśli to ten sam system
        self._copy_target(route)
        if not getattr(route, '_live_check', None):
            self._verify_live()  # rynek na żywo mógł przyjść przed końcem liczenia Spansh
        threading.Thread(target=self._tag_security, args=(route,), daemon=True).start()

    def _tag_security(self, route) -> None:
        """Bezpieczeństwo systemu celu każdego hopu (Spansh, pamięć 6 h) → ostrzeżenie LOW SEC / ANARCHY na pasku."""
        if route is None or route.error or not route.hops_list:
            return
        for hop in route.hops_list:
            radius = max(20.0, hop.distance + 1.0)
            hop._security = trade_module.security_near(hop.source_system, radius).get(
                hop.destination_system.lower(), "")
        if self.overlay:
            self.overlay._refresh_now()

    def _calibrate(self, trip) -> None:
        """Realny czas lotu hopu vs ogólny szacunek → Twoje tempo (mnożnik czasu w rankingach CR/H)."""
        if not trip:
            return
        hop, bought_at, docked_at = trip
        actual = (docked_at - bought_at).total_seconds()
        estimate = travel_seconds(hop.distance, hop.dst_ls, float(self.trade_engine.ly_per or 30.0), calibrated=False)
        if self.pilot.add(actual, estimate, f"{hop.source_system} → {hop.destination_system}"):
            trade_module.set_pilot_factor(self.pilot.factor)
            logger.info("Kurs %s: %.0f s (szacunek %.0f s) — tempo %s", hop.destination_system, actual, estimate,
                        self.pilot.describe())
        if self.panel is not None:
            self.panel.show_pilot(self.pilot.describe())

    def _current_target(self, route) -> tuple[str, str]:
        """(system, stacja), do których trzeba teraz lecieć: cel bieżącego hopu (checklista), inaczej cel trasy."""
        if route is None or route.error:
            return "", ""
        if self.checklist is not None and self.checklist.route is route:
            if self.checklist.finished:
                return "", ""
            return self.checklist.hop.destination_system, self.checklist.hop.destination_station
        return route.destination_system, route.destination_station

    def _copy_target(self, route) -> None:
        """Trasa zaktualizowana → cel do schowka (w grze: mapa galaktyki → wyszukiwanie → Ctrl+V).

        Co kopiować (stacja / system / oba) wybiera się w Ustawieniach — domyślnie stacja.
        """
        if self.overlay is None or not self.user_config.get('auto_copy_system', True):
            return
        system, station = self._current_target(route)
        target = copy_text(system, station, self.user_config.get('copy_target', 'station'))
        if not target or target == self._copied_system:
            return
        self._copied_system = target
        self.overlay.master.after(0, self._copy_now, target)

    def _copy_now(self, target: str) -> None:
        if self.panel is not None:
            self.panel.copy_system(target)  # + komunikat w panelu (system albo stacja)
        else:
            self.overlay.master.clipboard_clear()
            self.overlay.master.clipboard_append(target)
        self.overlay.mark_copied(target)
        logger.info("Schowek: %s", target)

    def _feed_checklist(self, event: dict) -> None:
        if self.checklist is None or not self.checklist.on_event(event):
            return
        self._calibrate(self.checklist.pop_trip())
        logger.info("Checklista: hop %d/%d %s", self.checklist.hop_index + 1,
                    len(self.checklist.hops), self.checklist.status_text())
        if self.overlay:
            self.overlay._refresh_now()
        if self.panel is not None:
            self.panel.show_route(self.checklist.route)
        self._copy_target(self.checklist.route)  # następny hop → nowy cel w schowku

    def _publish_session(self) -> None:
        """Podsumowanie sesji → panel (strona SESJA) i strona rotacji paska."""
        summary = self.session.summary()
        if self.panel is not None:
            self.panel.show_session(summary)
        if self.overlay and summary.sells:
            self.overlay.register_page('session', lambda: self._session_bar_text())

    def _session_bar_text(self) -> str:
        s = self.session.summary()
        per_hour = s.profit_per_hour()
        return (f"SESJA: ZYSK {compact_cr(s.profit)} CR" + (f" · {compact_cr(per_hour)} CR/H" if per_hour else "")
                + f"\n{len(s.sells)} SPRZEDAŻY · {s.tons_sold:,} T")

    def _on_session(self, event: dict):
        """LoadGame — nowa sesja gry, liczniki od zera."""
        if self.session.on_event(event):
            self._publish_session()

    def _on_trade(self, event: dict):
        """MarketBuy/MarketSell — odhaczanie kroków; po ukończeniu trasy od razu następna z bieżącej stacji."""
        if self.session.on_event(event):
            self._publish_session()
        was_finished = self.checklist is None or self.checklist.finished
        self._feed_checklist(event)
        if not was_finished and self.checklist.finished and "/" in self._last_system:
            system, station = self._last_system.split("/", 1)
            logger.info("Trasa ukończona — liczę następną z %s/%s", system, station)
            self._last_system = ""
            self._on_docked({"StarSystem": system, "StationName": station})

    def _on_docked(self, event: dict):
        """Reaguje na event Docked — wylicza najlepszą trasę."""
        self.session.on_event(event)  # stacja dla kolejnych transakcji w podsumowaniu
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

        # Pobierz info o systemie i stacjach — przed liczeniem trasy (Spansh trwa do kilku minut)
        try:
            system_id64 = str(event.get('SystemAddress', ''))
            info_parts = []
            if system_id64:
                sys_info = get_system_info(system_id64)
                if sys_info.name:
                    info_parts.append(f'{sys_info.allegiance} | sec:{sys_info.security}')
            stations = search_stations(system)
            if stations:
                info_parts.append(stations_word(len(stations)))
            if self.overlay:
                self.overlay.set_system_info(f'{system} · {station}\n' + ' | '.join(info_parts))
        except Exception:
            logger.exception('Błąd automatu stacje/system przy Docked')


        # Dokowanie w celu bieżącego hopu = gracz realizuje plan — nie nadpisujemy trasy
        route = None
        if following:
            logger.info("Docked w celu hopu %d — trasa w toku, bez przeliczania", self.checklist.hop_index + 1)
        else:
            self._apply_market_filter()
            self._dock_generation += 1
            generation = self._dock_generation
            threading.Thread(target=self._quick_route, args=(system, station, generation), daemon=True).start()
            route = self.trade_engine.calculate_route_via_spansh(system, station)
            self._full_route_generation = generation
            quick = self._quick_route_of[1] if self._quick_route_of and self._quick_route_of[0] == generation else None
            if quick is not None and (route.error or (self.checklist is not None and self.checklist.route is quick
                                                      and self.checklist.bought > 0)
                                      or self._safer_quick(route, quick)):
                # Spansh nie dał trasy albo gracz już kupuje wg szybkiej — zostaje szybka
                buying = self.checklist is not None and self.checklist.route is quick and self.checklist.bought > 0
                logger.info("Zostaje szybka trasa (%s)", route.error or ("zakup w toku" if buying
                                                                        else "profil SAFE: pełna trasa ma stare ceny"))
                quick._quick = False  # pełnej nie będzie — pasek przestaje czekać
                if self.overlay:
                    self.overlay._refresh_now()
                route = None

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
        # Ceny na żywo z gry dla bieżącej stacji: weryfikacja trasy + panel (zamiast API, wiek 0)
        try:
            data = market_cache._load_market_json(self.watcher.journal_dir / "Market.json")
            if data and data.get("MarketID") == event.get("MarketID"):
                if not self._commodity_ids:
                    self._commodity_ids = load_commodity_ids()
                live = market_from_market_json(data, self._commodity_ids)
                logger.info("Rynek na żywo: %s/%s — %d eksport, %d import", live.system_name, live.station_name,
                            len(live.exports), len(live.imports))
                self._live_market = live
                if self.panel is not None:
                    self.panel.update_context(live_market=live)
                self._verify_live()
        except Exception:
            logger.exception("Błąd odczytu Market.json (rynek na żywo)")

    def _verify_live(self) -> None:
        """Bieżący hop vs ceny z gry: na stacji kupna (przed zakupem) i w celu (przed sprzedażą).

        Towaru nie ma / nieopłacalny → od razu nowa trasa z cen na żywo (Spansh i tak ma stare dane).
        """
        live, checklist = self._live_market, self.checklist
        if live is None or checklist is None or checklist.finished:
            return
        hop = checklist.hop
        here = (live.system_name.lower(), live.station_name.lower())
        if not self._commodity_names:
            self._commodity_names = load_commodity_names()
        old_profit = hop.profit
        if here == (hop.source_system.lower(), hop.source_station.lower()) and checklist.bought < (hop.amount or 1):
            check = verify.check_buy(hop, live, self._commodity_names, checklist.hop_index)
        elif here == (hop.destination_system.lower(), hop.destination_station.lower()) and checklist.bought:
            check = verify.check_sell(hop, live, self._commodity_names, checklist.hop_index)
        else:
            return
        route = checklist.route
        route.total_profit += hop.profit - old_profit  # tylko różnica na tym hopie (inne hopy bez zmian)
        route._live_check = check
        checklist._sync_route()
        logger.info("Weryfikacja na żywo (hop %d, %s): %s", checklist.hop_index + 1, check.phase, check.text)
        if self.overlay:
            self.overlay._refresh_now()
        if self.panel is not None:
            self.panel.show_route(route)
        if check.level == verify.GONE:
            threading.Thread(target=self._replan_from_live, args=(live, check), daemon=True).start()

    def _best_single_route(self, market) -> Optional[TradeRoute]:
        """Najlepszy pojedynczy kurs (cr/h, wg filtrów) z rynku stacji → trasa 1-hop z checklistą.

        Szybkie (jedno zapytanie Ardent na towar, równolegle) — nie czeka na Spansh (40–180 s).
        """
        capacity = int(self._last_capacity or self.trade_engine.capacity or 0)
        cands = nearby_candidates_from_market(market, capacity, self._apply_market_filter(),
                                              jump_range=float(self.trade_engine.ly_per or 30.0))
        best = rank_trades(cands, "per_hour")
        if not best:
            return None
        if not self._commodity_names:
            self._commodity_names = load_commodity_names()
        t = best[0]
        name = self._commodity_names.get(t.commodity.lower(), t.commodity)
        hop = Hop(market.system_name, market.station_name, t.sell_system, t.sell_station, name, t.units, t.buy_price,
                  t.sell_price, t.total_profit, t.distance, _epoch(market.updated_at), _epoch(t.updated_at),
                  t.distance_to_arrival)
        return TradeRoute(source_system=market.system_name, source_station=market.station_name,
                          destination_system=t.sell_system, destination_station=t.sell_station, buy_item=name,
                          buy_quantity=t.units, buy_price=t.buy_price, sell_price=t.sell_price,
                          profit_per_unit=t.profit_per_unit, total_profit=t.total_profit, cargo_used=t.units,
                          hops=1, hops_list=[hop])

    def _replan_from_live(self, live, check) -> None:
        """Towaru z trasy już nie ma → nowa trasa 1-hop z rynku na żywo (Spansh ma te same stare dane)."""
        try:
            route = self._best_single_route(live)
        except Exception:
            logger.exception("Nowa trasa z rynku na żywo")
            return
        if route is None:
            logger.info("Brak alternatywy z rynku na żywo — zostaje komunikat: %s", check.text)
            return
        logger.info("Nowa trasa z rynku na żywo: %s", route.summary())
        self._publish_route(route, live.system_name, live.station_name)
        route._live_check = verify.LiveCheck(verify.OK, f"↻ ZAMIAST: {route.buy_item.upper()} (CENY NA ŻYWO)",
                                             verify.BUY, 0)
        if self.overlay:
            self.overlay._refresh_now()

    def _safer_quick(self, full, quick) -> bool:
        """Profil SAFE: pierwszy hop Spansh z ryzykownymi (starymi) cenami celu, a szybka trasa jest pewna → szybka."""
        if trade_module.RISK_PROFILE != "safe" or not full.hops_list or not quick.hops_list:
            return False
        risk = lambda hop: assess.age_risk(age_hours(hop.dst_updated_at))
        return risk(full.hops_list[0]) >= assess.RISKY_FROM and risk(quick.hops_list[0]) < assess.RISKY_FROM

    def _quick_route(self, system: str, station: str, generation: int) -> None:
        """Od razu po dokowaniu: najlepszy pojedynczy kurs, zanim Spansh policzy pełną trasę."""
        try:
            market = self._live_market if self._live_market is not None and (
                self._live_market.system_name.lower(), self._live_market.station_name.lower()) == (
                system.lower(), station.lower()) else get_station_market(system, station)
            route = None if market.error else self._best_single_route(market)
        except Exception:
            logger.exception("Szybka trasa po dokowaniu")
            return
        if route is None or generation != self._dock_generation or self._full_route_generation == generation:
            return  # w międzyczasie nowe dokowanie albo Spansh już skończył
        route._quick = True
        self._quick_route_of = (generation, route)
        logger.info("Szybka trasa (czekam na Spansh): %s", route.summary())
        self._publish_route(route, system, station)

    def _on_materials(self, event: dict):
        """Reaguje na event Materials (start gry) — stan materiałów do zakładki Inżynieria."""
        if self.panel is not None:
            self.panel.set_materials(event)

    def _apply_bar_visibility(self, window_class: Optional[str]) -> None:
        """Gdy włączone bar_only_when_game_focused: pasek widoczny tylko, gdy aktywne okno ma klasę game_window_class."""
        if self.overlay is None:
            return
        if not self.user_config.get('bar_only_when_game_focused', False):
            if not self._bar_visible:
                self._set_bars_visible(True)
                self._bar_visible = True
                logger.info("Pasek: przywrócony (tryb 'tylko przy grze' wyłączony)")
            return
        if window_class is None:
            if not self._focus_warned:
                logger.warning("Pasek tylko przy grze: nie da się odczytać aktywnego okna (kdotool) — pasek zostaje widoczny")
                self._focus_warned = True
            return
        game_class = self.user_config.get('game_window_class', '')
        want_visible = bool(game_class) and window_class == game_class
        if want_visible == self._bar_visible:
            return
        self._bar_visible = want_visible
        self._set_bars_visible(want_visible)
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

    def _set_bars_visible(self, visible: bool) -> None:
        """Pokaż/ukryj pasek i każde inne okno-nakładkę (Toplevel z overrideredirect, np. dolny pasek); panel zostaje.

        Przy chowaniu zapamiętuje, co było widoczne, i tylko to przywraca — zamknięte wysuwane okna nie wyskoczą."""
        if visible:
            for bar in self._hidden_bars:
                if bar.winfo_exists():
                    bar.deiconify()
            self._hidden_bars = []
            return
        root = self.overlay.master
        bars = [root] + [w for w in root.winfo_children() if hasattr(w, 'overrideredirect') and w.overrideredirect()]
        self._hidden_bars = [bar for bar in bars if bar.state() == 'normal']
        for bar in self._hidden_bars:
            bar.withdraw()

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
