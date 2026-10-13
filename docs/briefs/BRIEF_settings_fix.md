# Zadanie: POPRAWKI do poprzedniej pracy (3 błędy). Zmieniasz TYLKO edtrade/panel.py i edtrade/main.py. Bez researchu. Nie edytuj SPEC.md.
Poprzednia wersja przeszła Twoje testy, ale zawiera 3 błędy, które znalazłem czytając diff:

## Błąd 1 (KRYTYCZNY) — main.py: usunąłeś cudzy kod
Przy przenoszeniu `self.user_config = ...` skasowałeś też blok inicjalizacji cache rynku. `self._market_conn` jest używany niżej (przekazywany do obsługi eventu Market, ok. linii 314), więc app by się wywaliła. PRZYWRÓĆ DOSŁOWNIE te 3 linie w `EDTradeOverlayApp.__init__`, tuż po bloku `if self.overlay is not None and not args.no_panel: ... except Exception: logger.exception(...)` (czyli przed `self.watcher = JournalWatcher(`):
        self._market_conn = init_market_cache(
            Path.home() / ".local" / "share" / "ed-trade-overlay" / "market_cache.db"
        )
Nie usuwaj niczego innego. Linia `self.user_config = user_config_module.load_user_config()` ma zostać TYLKO w nowym miejscu (przed `self.overlay = TradeOverlay() ...`), bez duplikatu.

## Błąd 2 — panel.py: pola Ustawień nie są inicjowane z configu
Brief mówił: "każde pole z tk.StringVar zainicjowanym z self.user_config". Ty dałeś na sztywno '' i '30.0' — więc po starcie zakładka pokazuje puste pola, a kliknięcie 'Zapisz' NADPISAŁOBY istniejący config pustymi wartościami. Popraw: 
  journey_target_var = tk.StringVar(value=str(self.user_config.get('journey_target_system', '')))
  ship_range_var     = tk.StringVar(value=str(self.user_config.get('ship_range_ly', 30.0)))
  material_kind_var  = tk.StringVar(value=str(self.user_config.get('material_kind', '')))
  mining_mineral_var = tk.StringVar(value=str(self.user_config.get('mining_mineral', '')))

## Błąd 3 — panel.py: układ poziomy się nie mieści
Okno ma 700 px, a Ty ułożyłeś 4 etykiety + 4 pola + przycisk + status w JEDNYM rzędzie (`pack(side=tk.LEFT)`), więc część zostanie ucięta. Zrób układ pionowy w zakładce Ustawienia: użyj `ttk.Frame` z `grid` — każdy parametr w osobnym wierszu: kolumna 0 = etykieta (sticky='w'), kolumna 1 = pole (sticky='ew', kolumna 1 z weight=1); wiersz 4 = przycisk 'Zapisz' (kolumna 1, sticky='w'); wiersz 5 = etykieta statusu (kolumna 1). padx=10, pady=4. Nazwy atrybutów (`journey_target_var`, `ship_range_var`, `material_kind_var`, `mining_mineral_var`, `settings_status_var`, `save_settings_btn`) i metoda `save_settings` mają zostać BEZ ZMIAN.

## Test (max 90 s) — powłoka nie ma wyświetlacza, ustaw DOSŁOWNIE:
export DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 XAUTHORITY=$(tr '\0' '\n' < /proc/$(pgrep -x plasmashell | head -1)/environ | grep ^XAUTHORITY= | cut -d= -f2)
a) cd ~/Projekty/ed-trade-overlay && python3 -m py_compile edtrade/panel.py edtrade/main.py
b) grep -n "_market_conn\|init_market_cache\|user_config = " edtrade/main.py  → ma być: import init_market_cache, JEDNO przypisanie _market_conn, JEDNO przypisanie user_config (przed TradeOverlay()), użycie _market_conn ok. linii 314.
c) Test GUI na PLIKU TYMCZASOWYM (NIE rusz ~/.config/ed-trade-overlay/config.json): utwórz cfg = {'journey_target_system': 'Colonia', 'ship_range_ly': 32.5, 'material_kind': 'Raw', 'mining_mineral': 'Platinum'}, panel = TradePanel(root, user_config=cfg, config_path=Path('/tmp/test_settings_config2.json')); wypisz panel.journey_target_var.get(), panel.ship_range_var.get(), panel.material_kind_var.get(), panel.mining_mineral_var.get() → MUSZĄ być 'Colonia','32.5','Raw','Platinum' (czyli z configu). Potem panel.window.update_idletasks() i wypisz panel.save_settings_btn.winfo_rootx() oraz panel.window.winfo_rootx()+panel.window.winfo_width() — przycisk musi mieścić się w szerokości okna (rootx przycisku < prawa krawędź okna).
Na końcu krótko: co zrobione + wyniki a/b/c.
