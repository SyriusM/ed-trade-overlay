# Zadanie (JEDEN mały krok, 4A): zamknięcie panelu minimalizuje okno zamiast je niszczyć — TYLKO edtrade/panel.py
Nie ruszaj żadnego innego pliku. NIE twórz żadnych plików (żadnych .bak; kopia jest w /tmp/panel.py.bak-close). Nie usuwaj ani nie zmieniaj istniejących linii — tylko DODAJ wskazane. Bez researchu.
Problem: kliknięcie X na oknie panelu niszczy `Toplevel` i nie da się go otworzyć bez restartu aplikacji. Okno ma zostać przy życiu i tylko się zminimalizować (wraca z paska zadań/Alt-Tab).

## Zmiana (jedna linia + jeden komentarz)
W `TradePanel.__init__`, zaraz POD linią `self.window.geometry('700x450')` dopisz DOSŁOWNIE (z wcięciem 8 spacji):
        # X minimalizuje okno zamiast je niszczyć — panel wraca z paska zadań / Alt-Tab
        self.window.protocol('WM_DELETE_WINDOW', self.window.iconify)
Nic więcej nie zmieniaj (nie ruszaj `show()`/`hide()`).

## Test (max 60 s). Powłoka nie ma wyświetlacza — ustaw DOSŁOWNIE:
export DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 XAUTHORITY=$(tr '\0' '\n' < /proc/$(pgrep -x plasmashell | head -1)/environ | grep ^XAUTHORITY= | cut -d= -f2)
a) cd ~/Projekty/ed-trade-overlay && python3 -m py_compile edtrade/panel.py
b) diff /tmp/panel.py.bak-close edtrade/panel.py  → wypisz CAŁY diff (tylko 2 dodane linie: komentarz + protocol).
c) python3 -c "
import tkinter as tk
from pathlib import Path
from edtrade.panel import TradePanel
root = tk.Tk(); root.withdraw()
cfg = {'journey_target_system': '', 'ship_range_ly': 30.0, 'material_kind': '', 'mining_mineral': '', 'game_window_class': 'x', 'bar_only_when_game_focused': False}
p = TradePanel(root, user_config=cfg, config_path=Path('/tmp/test_close_config.json'))
p.window.update()
print('przed X: state=', p.window.state(), 'exists=', p.window.winfo_exists())
p.window.tk.eval(p.window.protocol('WM_DELETE_WINDOW'))
p.window.update()
print('po X:    state=', p.window.state(), 'exists=', p.window.winfo_exists())
p.window.deiconify(); p.window.update()
print('po deiconify: state=', p.window.state(), 'exists=', p.window.winfo_exists())
"
   Oczekiwane: przed X normal/1 | po X iconic/1 (okno NIE zniszczone) | po deiconify normal/1
d) ls edtrade/ | grep -i bak → nic.
Na końcu krótko: wyniki a/b/c/d (wypisz dosłownie wiersze z c).
