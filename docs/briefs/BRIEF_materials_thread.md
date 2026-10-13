# Zadanie (JEDEN krok, 4C): zakładka Materiały w wątku roboczym — TYLKO edtrade/panel.py
Nie ruszaj żadnego innego pliku ani innych zakładek/metod (Journey, System, Mining, Ustawienia — nietykalne). NIE twórz żadnych plików (żadnych .bak; kopia jest w /tmp/panel.py.bak-thread-mat). Bez researchu.
**WCIĘCIA: WYŁĄCZNIE SPACJE (4 na poziom), ŻADNYCH TABULATORÓW.** Kopiuj kod DOSŁOWNIE. `import threading` JUŻ jest w pliku — nie dodawaj go drugi raz.
Problem: `refresh_materials_tab` woła `find_material_traders(...)` (sieć) w wątku Tk, więc UI zamarza na czas zapytania. Wzorzec jest już zrobiony dla Journey (`refresh_journey_tab` / `_journey_worker` / `_journey_done`) — przeczytaj go i zrób to samo dla Materiałów.

## Edycja 1 — nazwany przycisk
Znajdź linię (zakładka Materiały):
        ttk.Button(self.materials_entry_frame, text='Odśwież', command=self.refresh_materials_tab).pack(side=tk.LEFT)
i ZASTĄP ją DWIEMA liniami:
        self.materials_btn = ttk.Button(self.materials_entry_frame, text='Odśwież', command=self.refresh_materials_tab)
        self.materials_btn.pack(side=tk.LEFT)

## Edycja 2 — zastąp CAŁĄ metodę `refresh_materials_tab`
Od linii `    def refresh_materials_tab(self) -> None:` do linii tuż PRZED `    def refresh_mining_tab(self) -> None:` (nie ruszaj `refresh_mining_tab`) wstaw DOSŁOWNIE:

    def _set_materials_text(self, text: str) -> None:
        self.materials_text.config(state=tk.NORMAL)
        self.materials_text.delete('1.0', tk.END)
        self.materials_text.insert('1.0', text)
        self.materials_text.config(state=tk.DISABLED)

    def refresh_materials_tab(self) -> None:
        """Waliduj w watku Tk i pobierz handlarzy materialow w watku roboczym (UI nie zamarza)."""
        system_name = self.materials_system_var.get().strip()
        kind = self.materials_kind_var.get().strip()
        if not system_name or not kind:
            return
        self.materials_btn.config(state=tk.DISABLED)
        self._set_materials_text(f'System: {system_name} | Rodzaj: {kind}\n\nSzukam...')
        threading.Thread(target=self._materials_worker, args=(system_name, kind), daemon=True).start()

    def _materials_worker(self, system_name: str, kind: str) -> None:
        """Watek roboczy: NIE dotyka widgetow Tk — liczy i oddaje tekst przez after(0)."""
        lines = [f'System: {system_name} | Rodzaj: {kind}', '']
        try:
            traders = find_material_traders(system_name, kind, max_ly=50, size=10)
            if traders:
                lines.append(f'Handlarze ({len(traders)}):')
                for t in traders:
                    lines.append(f'  - {t.name} ({t.system_name}) {t.distance:.1f} ly')
            else:
                lines.append('Brak handlarzy w zasięgu.')
        except Exception as e:
            lines.append(f'Błąd wyszukiwania: {e}')
        try:
            self.window.after(0, self._materials_done, '\n'.join(lines))
        except Exception:
            pass

    def _materials_done(self, text: str) -> None:
        """Wywolywane w watku Tk: pokaz wynik i odblokuj przycisk."""
        self._set_materials_text(text)
        self.materials_btn.config(state=tk.NORMAL)

## Test (max 90 s). Powłoka nie ma wyświetlacza — ustaw DOSŁOWNIE:
export DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 XAUTHORITY=$(tr '\0' '\n' < /proc/$(pgrep -x plasmashell | head -1)/environ | grep ^XAUTHORITY= | cut -d= -f2)
a) cd ~/Projekty/ed-trade-overlay && python3 -m py_compile edtrade/panel.py && grep -c $'\t' edtrade/panel.py   (compile OK; grep ma wypisać 0)
b) diff /tmp/panel.py.bak-thread-mat edtrade/panel.py  → wypisz CAŁY diff (2 linie przycisku + sekcja materials; nic poza tym).
c) Test w PRAWDZIWYM mainloop (ważne: wywołanie after() z wątku działa tylko gdy główny wątek jest w root.mainloop(), NIE w pętli root.update()):
python3 -c "
import tkinter as tk, time
from pathlib import Path
from edtrade.panel import TradePanel
root = tk.Tk(); root.withdraw()
cfg = {'journey_target_system': '', 'ship_range_ly': 30.0, 'material_kind': '', 'mining_mineral': '', 'game_window_class': 'x', 'bar_only_when_game_focused': False}
p = TradePanel(root, user_config=cfg, config_path=Path('/tmp/test_mat_thread.json'))
ticks = [0]; t0 = [0.0]
def tick():
    ticks[0] += 1
    root.after(100, tick)
def start():
    p.materials_system_var.set('Sol'); p.materials_kind_var.set('Manufactured')
    t0[0] = time.time(); p.refresh_materials_tab()
    print('refresh zwrocil po', round(time.time() - t0[0], 2), 's | przycisk:', p.materials_btn.cget('state'), '| tekst:', p.materials_text.get('1.0', 'end').strip().replace(chr(10), ' / ')[:60], flush=True)
    poll()
def poll():
    if str(p.materials_btn.cget('state')) == 'disabled' and time.time() - t0[0] < 60:
        root.after(100, poll); return
    print('calosc', round(time.time() - t0[0], 1), 's | tyniecia:', ticks[0], '| przycisk:', p.materials_btn.cget('state'), flush=True)
    print([l for l in p.materials_text.get('1.0', 'end').split(chr(10)) if l.startswith('Handlarze') or l.startswith('Błąd') or l.startswith('Brak')], flush=True)
    root.quit()
root.after(100, tick); root.after(500, start); root.mainloop()
"
   Oczekiwane: 'refresh zwrocil po' < 0.5 s (przycisk disabled, tekst 'Szukam...'); przycisk normal na końcu; linia 'Handlarze (10):' (albo inna liczba > 0).
d) ls edtrade/ | grep -i bak → nic.
Na końcu krótko: wyniki a/b/c/d (wypisz dosłownie; jeśli przycisk został 'disabled' po teście — napisz to wprost, NIE twierdź że przeszło).
