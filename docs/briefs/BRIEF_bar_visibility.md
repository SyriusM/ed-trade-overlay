# Zadanie (JEDEN mały krok, 3D): pokazywanie/ukrywanie paska wg fokusu gry — TYLKO edtrade/main.py
Nie ruszaj żadnego innego pliku. NIE twórz żadnych plików poza zmianą main.py (żadnych .bak; kopia jest w /tmp/main.py.bak-3d). NIE usuwaj i NIE przenoś żadnych istniejących linii (zwłaszcza `_market_conn`, `init_market_cache`, `user_config`, `TradePanel`) — tylko dopisujesz i modyfikujesz jedno wskazane wywołanie. Bez researchu.
Kontekst: `_poll_active_window` (co 1 s) już istnieje i ustala `window_class` aktywnego okna. Config ma `bar_only_when_game_focused` (bool, domyślnie False) i `game_window_class` (str). Pasek = `self.overlay.master` (root Tk, `overrideredirect`); `withdraw()` chowa TYLKO pasek, panel (osobny Toplevel) zostaje — to zmierzone.

## Edycja 1 — `__init__`
Zaraz POD linią `self._last_active_class: Optional[str] = None` dopisz:
        self._bar_visible: bool = True

## Edycja 2 — nowa metoda, umieść ją tuż PRZED `def _poll_active_window`:

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

## Edycja 3 — w `_poll_active_window`
W bloku `try:` DOPISZ jedną linię na samym końcu bloku (po `self._last_active_class = window_class` wewnątrz `if`, ale NA POZIOMIE `if`, czyli z wcięciem 12 spacji, pod całym blokiem `if window_class != self._last_active_class:`):
            self._apply_bar_visibility(window_class)
Reszty metody (log zmiany klasy, `except`, `finally` z `after(1000, ...)`) NIE zmieniaj.

## Test BEZ GUI (max 30 s), z katalogu ~/Projekty/ed-trade-overlay:
a) python3 -m py_compile edtrade/main.py
b) diff /tmp/main.py.bak-3d edtrade/main.py  → wypisz CAŁY diff; mają być wyłącznie linie dodane (>), zero usuniętych (<).
c) python3 -c "
from unittest.mock import MagicMock
from edtrade.main import EDTradeOverlayApp
app = EDTradeOverlayApp.__new__(EDTradeOverlayApp)
app.overlay = MagicMock()
app._bar_visible = True
m = app.overlay.master
def calls(): 
    c = [x[0] for x in m.method_calls]; m.reset_mock(); return c
app.user_config = {'bar_only_when_game_focused': False, 'game_window_class': 'game'}
app._apply_bar_visibility('inne'); print('1 flaga off, inne:', calls(), app._bar_visible)
app.user_config['bar_only_when_game_focused'] = True
app._apply_bar_visibility(None); print('2 kdotool None:', calls(), app._bar_visible)
app._apply_bar_visibility('inne'); print('3 inne okno:', calls(), app._bar_visible)
app._apply_bar_visibility('inne'); print('4 inne okno ponownie:', calls(), app._bar_visible)
app._apply_bar_visibility('game'); print('5 gra aktywna:', calls(), app._bar_visible)
app._apply_bar_visibility('game'); print('6 gra ponownie:', calls(), app._bar_visible)
app._apply_bar_visibility('inne'); print('7 znów inne:', calls(), app._bar_visible)
app.user_config['bar_only_when_game_focused'] = False
app._apply_bar_visibility('inne'); print('8 flaga wyłączona w trakcie:', calls(), app._bar_visible)
app.user_config.update({'bar_only_when_game_focused': True, 'game_window_class': ''})
app._apply_bar_visibility('cokolwiek'); print('9 pusta klasa gry:', calls(), app._bar_visible)
"
   Oczekiwane: 1 [] True | 2 [] True | 3 ['withdraw'] False | 4 [] False | 5 ['deiconify'] True | 6 [] True | 7 ['withdraw'] False | 8 ['deiconify'] True | 9 ['withdraw'] False
d) ls edtrade/ | grep -i bak → nic.
Na końcu krótko: wyniki a/b/c/d (wypisz dosłownie wiersze 1-9; jeśli któryś nie zgadza się z oczekiwanym — napisz to wprost).
