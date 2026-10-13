# Zadanie (JEDEN krok, 4D): zakładka System w wątku roboczym — TYLKO edtrade/panel.py
Nie ruszaj żadnego innego pliku ani innych zakładek/metod (Journey, Materiały, Mining, Ustawienia — nietykalne). NIE twórz żadnych plików (żadnych .bak; kopia jest w /tmp/panel.py.bak-thread-sys). Bez researchu.
**WCIĘCIA: WYŁĄCZNIE SPACJE (4 na poziom), ŻADNYCH TABULATORÓW.** Kopiuj kod DOSŁOWNIE. `import threading` JUŻ jest w pliku — nie dodawaj go drugi raz. Przycisk `self.system_refresh_btn` JUŻ istnieje — NIE zmieniaj jego definicji (Edycji przycisku nie ma).
Problem: `refresh_system_tab` woła `search_stations(...)` (sieć) w wątku Tk, więc UI zamarza na czas zapytania. Wzorzec jest zrobiony dla Journey i Materiałów (`refresh_materials_tab` / `_materials_worker` / `_materials_done`) — zrób to samo dla System.

## Jedyna edycja — zastąp CAŁĄ metodę `refresh_system_tab`
Od linii `    def refresh_system_tab(self) -> None:` do linii tuż PRZED `    def _set_materials_text(self, text: str) -> None:` (nie ruszaj `_set_materials_text`) wstaw DOSŁOWNIE:

    def _set_system_text(self, text: str) -> None:
        self.system_info_text.config(state=tk.NORMAL)
        self.system_info_text.delete('1.0', tk.END)
        self.system_info_text.insert('1.0', text)
        self.system_info_text.config(state=tk.DISABLED)

    def refresh_system_tab(self) -> None:
        """Waliduj w watku Tk i pobierz stacje systemu w watku roboczym (UI nie zamarza)."""
        system_name = self.system_entry_var.get().strip()
        if not system_name:
            return
        self.system_refresh_btn.config(state=tk.DISABLED)
        self._set_system_text(f'System: {system_name}\n\nSzukam...')
        threading.Thread(target=self._system_worker, args=(system_name,), daemon=True).start()

    def _system_worker(self, system_name: str) -> None:
        """Watek roboczy: NIE dotyka widgetow Tk — liczy i oddaje tekst przez after(0)."""
        lines = [f'System: {system_name}', '']
        try:
            stations = search_stations(system_name)
            if stations:
                lines.append(f'Stacje ({len(stations)}):')
                for s in stations[:20]:
                    lines.append(f'  - {s.name} ({s.pad_size or "?"}) {s.distance_to_arrival:.0f} ls')
            else:
                lines.append('Brak danych o stacjach.')
        except Exception as e:
            lines.append(f'Błąd wyszukiwania stacji: {e}')
        try:
            self.window.after(0, self._system_done, '\n'.join(lines))
        except Exception:
            pass

    def _system_done(self, text: str) -> None:
        """Wywolywane w watku Tk: pokaz wynik i odblokuj przycisk."""
        self._set_system_text(text)
        self.system_refresh_btn.config(state=tk.NORMAL)

## Test (max 90 s). Powłoka nie ma wyświetlacza — ustaw DOSŁOWNIE:
export DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 XAUTHORITY=$(tr '\0' '\n' < /proc/$(pgrep -x plasmashell | head -1)/environ | grep ^XAUTHORITY= | cut -d= -f2)
a) cd ~/Projekty/ed-trade-overlay && python3 -m py_compile edtrade/panel.py && grep -c $'\t' edtrade/panel.py   (compile OK; grep ma wypisać 0)
b) diff /tmp/panel.py.bak-thread-sys edtrade/panel.py  → wypisz CAŁY diff (tylko sekcja system; żadnej zmiany przycisku).
c) Test w PRAWDZIWYM mainloop (wywołanie after() z wątku działa tylko gdy główny wątek jest w root.mainloop(), NIE w pętli root.update()). Uruchom DOSŁOWNIE ten skrypt (python3 -c "..."):
import tkinter as tk, time
from pathlib import Path
from edtrade.panel import TradePanel
root = tk.Tk(); root.withdraw()
cfg = {'journey_target_system': '', 'ship_range_ly': 30.0, 'material_kind': '', 'mining_mineral': '', 'game_window_class': 'x', 'bar_only_when_game_focused': False}
p = TradePanel(root, user_config=cfg, config_path=Path('/tmp/test_sys_thread.json'))
ticks = [0]; t0 = [0.0]
def tick():
    ticks[0] += 1
    root.after(100, tick)
def start():
    p.system_entry_var.set('Sol')
    t0[0] = time.time(); p.refresh_system_tab()
    print('refresh zwrocil po', round(time.time() - t0[0], 2), 's | przycisk:', p.system_refresh_btn.cget('state'), '| tekst:', p.system_info_text.get('1.0', 'end').strip().replace(chr(10), ' / ')[:60], flush=True)
    poll()
def poll():
    if str(p.system_refresh_btn.cget('state')) == 'disabled' and time.time() - t0[0] < 60:
        root.after(100, poll); return
    print('calosc', round(time.time() - t0[0], 1), 's | tyniecia:', ticks[0], '| przycisk:', p.system_refresh_btn.cget('state'), flush=True)
    print([l for l in p.system_info_text.get('1.0', 'end').split(chr(10)) if l.startswith('Stacje') or l.startswith('Błąd') or l.startswith('Brak')], flush=True)
    root.quit()
root.after(100, tick); root.after(500, start); root.mainloop()
   Oczekiwane: 'refresh zwrocil po' < 0.5 s (przycisk disabled, tekst 'Szukam...'); przycisk normal na końcu; linia 'Stacje (N):' z N > 0 (dla Sol ok. 62).
d) ls edtrade/ | grep -i bak → nic.
Na końcu krótko: wyniki a/b/c/d (wypisz dosłownie; jeśli przycisk został 'disabled' po teście — napisz to wprost, NIE twierdź że przeszło; jeśli nie możesz uruchomić testu c — napisz dlaczego i podaj dosłowny błąd).
