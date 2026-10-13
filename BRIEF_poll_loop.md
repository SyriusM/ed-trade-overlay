# Zadanie (JEDEN mały krok, 3B): pętla pollingu aktywnego okna w main.py — TYLKO edtrade/main.py
Nie ruszaj innych plików (window_watch.py już istnieje i działa; panel.py, overlay.py, trade.py, config.py, SPEC.md — nie edytuj). Bez researchu. NIE usuwaj ani nie przenoś żadnych istniejących linii w main.py (poprzednia sesja skasowała blok `_market_conn` — to NIE może się powtórzyć); tylko DODAJ kod.

## Co dodać (4 zmiany, wszystkie tylko dopisywane)
1. Import obok pozostałych importów z pakietu (np. pod `from .panel import TradePanel`):
   from .window_watch import get_active_window
2. W `EDTradeOverlayApp.__init__`, na samym KOŃCU metody (po wszystkich istniejących liniach, np. po `self._last_capacity = 0.`; sprawdź jaka jest ostatnia linia __init__ i dopisz ZA nią, z tym samym wcięciem):
        self._last_active_class: Optional[str] = None
   (jeśli `Optional` nie jest zaimportowany w main.py — dodaj `from typing import Optional` do importów.)
3. Nowa metoda w klasie `EDTradeOverlayApp`, umieść ją tuż PRZED `def run(self):`:

    def _poll_active_window(self) -> None:
        """Co sekundę odczytaj klasę aktywnego okna; zaloguj tylko ZMIANĘ (bez tytułów — mogą zawierać prywatne dane)."""
        try:
            active = get_active_window()
            window_class = active[0] if active else None
            if window_class != self._last_active_class:
                logger.info("Aktywne okno: class=%r", window_class)
                self._last_active_class = window_class
        except Exception:
            logger.exception("Błąd pollingu aktywnego okna")
        finally:
            if self.overlay is not None:
                self.overlay.master.after(1000, self._poll_active_window)

4. W metodzie `run`, w gałęzi `if self._show_overlay:` dodaj linię PRZED `self.overlay.show()` (show() startuje mainloop i blokuje, więc po nim kod się nie wykona):
            self.overlay.master.after(1000, self._poll_active_window)
   Czyli blok ma wyglądać tak:
        if self._show_overlay:
            self.overlay.master.after(1000, self._poll_active_window)
            self.overlay.show()
        else:
            logger.info("Uruchomiono w trybie --no-overlay — brak okna")

## Test (max 60 s). Powłoka nie ma zmiennych sesji — ustaw DOSŁOWNIE:
PID=$(pgrep -x plasmashell | head -1); for v in KDE_SESSION_VERSION XDG_CURRENT_DESKTOP DBUS_SESSION_BUS_ADDRESS KDE_FULL_SESSION XAUTHORITY; do export "$v=$(tr '\0' '\n' < /proc/$PID/environ | grep "^$v=" | cut -d= -f2-)"; done; export DISPLAY=:0 WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000
a) cd ~/Projekty/ed-trade-overlay && python3 -m py_compile edtrade/main.py
b) diff /tmp/main.py.bak-poll edtrade/main.py  → wypisz CAŁY diff; mają być wyłącznie linie dodane (>), żadnej usuniętej (<) poza ewentualnie linią importu typing, jeśli ją rozszerzałeś.
c) timeout 12 python3 -m edtrade.main --log-level INFO > /tmp/poll_test.log 2>&1 ; grep -n "Aktywne okno\|TradePanel utworzony\|Traceback\|Error" /tmp/poll_test.log
   Oczekiwane: "TradePanel utworzony", co najmniej jedna linia "Aktywne okno: class='...'" (np. 'org.wezfurlong.wezterm' albo klasa okna Tk), brak Traceback.
Na końcu krótko: wyniki a/b/c (wypisz dosłownie linie z grep c).
