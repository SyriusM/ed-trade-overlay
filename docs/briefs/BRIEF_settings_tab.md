# Zadanie: IMPLEMENTACJA ONLY — zakładka "Ustawienia" w panelu (UI krok 2)
Bez researchu, bez przeglądarki. Zmieniasz TYLKO edtrade/panel.py i edtrade/main.py (nie ruszaj trade.py, overlay.py, config.py). Nie edytuj SPEC.md.
Kontekst: `edtrade/config.py` ma `load_user_config(path=None)`, `save_user_config(config, path=None)`, `CONFIG_PATH`; klucze: `journey_target_system` (str), `ship_range_ly` (float), `material_kind` (str: ""/Raw/Encoded/Manufactured), `mining_mineral` (str). Pusty string = automat wyłączony. `main.py` czyta `self.user_config` JEDEN RAZ w `__init__` i potem używa tego słownika w `_on_docked` — dlatego panel MUSI modyfikować TEN SAM obiekt słownika (in-place), a nie jego kopię.

## 1. panel.py
- Import: `from pathlib import Path`, `from .config import load_user_config, save_user_config`.
- Zmień sygnaturę: `def __init__(self, master: tk.Tk, user_config: Optional[dict] = None, config_path: Optional[Path] = None):`. Zapisz `self.config_path = config_path`; `self.user_config = user_config if user_config is not None else load_user_config(config_path)`.
- Dodaj ostatnią zakładkę `ttk.Frame` o tytule 'Ustawienia' (po Journey), w stylu istniejących zakładek (ttk.Label + ttk.Entry/Combobox w ramkach `pack`). Pola (każde z `tk.StringVar` zainicjowanym z `self.user_config`):
  1. 'Cel journey (system):' Entry ← `journey_target_system`
  2. 'Zasięg statku (ly):' Entry ← `ship_range_ly` (jako str)
  3. 'Materiały (kind):' Combobox readonly, values ('', 'Raw', 'Encoded', 'Manufactured') ← `material_kind`
  4. 'Mining (minerał):' Entry ← `mining_mineral`
  Przycisk 'Zapisz' (`command=self.save_settings`) i `ttk.Label` ze statusem (`self.settings_status_var`).
- Metoda `save_settings(self) -> None`: wczytaj wartości (strip); zasięg `float(...)` — przy ValueError ustaw status 'Błąd: zasięg musi być liczbą.' i `return` BEZ zapisu. Potem `self.user_config.update({...4 klucze...})` (in-place!), `save_user_config(self.user_config, self.config_path)`, status 'Zapisano.' (przy wyjątku z zapisu: status 'Błąd zapisu: <e>').

## 2. main.py
W `EDTradeOverlayApp.__init__` panel jest tworzony PRZED `self.user_config = user_config_module.load_user_config()`. Przenieś linię `self.user_config = user_config_module.load_user_config()` tak, by była WYŻEJ — tuż przed linią `self.overlay = TradeOverlay() if self._show_overlay else None` (usuń ją z dotychczasowego miejsca, nie duplikuj). Następnie zmień `TradePanel(self.overlay.master)` na `TradePanel(self.overlay.master, user_config=self.user_config)`.

## Test (max 90 s). Powłoka nie ma wyświetlacza — ustaw go DOSŁOWNIE tak:
export DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 XAUTHORITY=$(tr '\0' '\n' < /proc/$(pgrep -x plasmashell | head -1)/environ | grep ^XAUTHORITY= | cut -d= -f2)
a) cd ~/Projekty/ed-trade-overlay && python3 -m py_compile edtrade/panel.py edtrade/main.py
b) Test GUI na PLIKU TYMCZASOWYM (NIE rusz prawdziwego configu użytkownika!):
python3 -c "
import tkinter as tk, json
from pathlib import Path
from edtrade.panel import TradePanel
root = tk.Tk(); root.withdraw()
p = Path('/tmp/test_settings_config.json')
cfg = {'journey_target_system': '', 'ship_range_ly': 30.0, 'material_kind': '', 'mining_mineral': ''}
panel = TradePanel(root, user_config=cfg, config_path=p)
print('tabs:', [panel.notebook.tab(i, 'text') for i in range(panel.notebook.index('end'))])
print('same dict:', panel.user_config is cfg)
"
(dopisz do skryptu: ustaw odpowiednie StringVar-y na 'Colonia', '32.5', 'Raw', 'Platinum', wywołaj panel.save_settings(), wypisz cfg i json.load(open(p)); potem ustaw zasięg na 'abc', wywołaj save_settings() i wypisz status oraz że cfg['ship_range_ly'] nadal 32.5)
Oczekiwane: 5+ zakładek z 'Ustawienia' na końcu, cfg zaktualizowany in-place, plik JSON zgodny, błędny zasięg nie zmienia configu.
Na końcu krótko: co zrobione + wyniki a/b.
