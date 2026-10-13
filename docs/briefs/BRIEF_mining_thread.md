# Zadanie (JEDEN krok, 4E): zakładka Mining w wątku roboczym + naprawa kolizji nazwy zmiennej — TYLKO edtrade/panel.py
Nie ruszaj żadnego innego pliku ani innych zakładek/metod (System, Materiały, Journey, Ustawienia, `save_settings` — nietykalne). NIE twórz żadnych plików (żadnych .bak; kopia jest w /tmp/panel.py.bak-thread-min). Bez researchu.
**WCIĘCIA: WYŁĄCZNIE SPACJE (4 na poziom), ŻADNYCH TABULATORÓW.** Kopiuj kod DOSŁOWNIE. `import threading` JUŻ jest w pliku — nie dodawaj go drugi raz.

## Dlaczego dwie rzeczy naraz
(1) BUG: atrybut `self.mining_mineral_var` jest zdefiniowany DWA razy — w zakładce Mining (ok. linii 75, wartość 'Platinum') i w zakładce Ustawienia (ok. linii 134, wartość z configu). Druga definicja nadpisuje pierwszą, więc pole minerału w zakładce Mining jest puste, a `refresh_mining_tab` czyta pusty tekst i po cichu nic nie robi. Zakładka Ustawienia i `save_settings` MAJĄ ZOSTAĆ przy nazwie `mining_mineral_var` — zmieniasz TYLKO zakładkę Mining.
(2) Wątek roboczy dla Mining (wzorzec jak `refresh_materials_tab` / `_materials_worker` / `_materials_done` — przeczytaj go).

## Edycja 1 — zmienna zakładki Mining (linia ok. 75)
Znajdź (JEDYNE wystąpienie w zakładce Mining, zaraz pod `self.tab_mining`/nad `self.mining_system_var`):
        self.mining_mineral_var = tk.StringVar(value='Platinum')
i ZASTĄP:
        self.mining_tab_mineral_var = tk.StringVar(value='Platinum')

## Edycja 2 — Entry minerału i przycisk w zakładce Mining (linie ok. 82-83)
Znajdź DWIE linie:
        ttk.Entry(self.mining_entry_frame, textvariable=self.mining_mineral_var, width=20).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Button(self.mining_entry_frame, text='Odśwież', command=self.refresh_mining_tab).pack(side=tk.LEFT)
i ZASTĄP je TRZEMA liniami:
        ttk.Entry(self.mining_entry_frame, textvariable=self.mining_tab_mineral_var, width=20).pack(side=tk.LEFT, padx=(4, 10))
        self.mining_btn = ttk.Button(self.mining_entry_frame, text='Odśwież', command=self.refresh_mining_tab)
        self.mining_btn.pack(side=tk.LEFT)

## Edycja 3 — zastąp CAŁĄ metodę `refresh_mining_tab`
Od linii `    def refresh_mining_tab(self) -> None:` do linii tuż PRZED `    def _set_journey_text(self, text: str) -> None:` (nie ruszaj `_set_journey_text`) wstaw DOSŁOWNIE:

    def _set_mining_text(self, text: str) -> None:
        self.mining_text.config(state=tk.NORMAL)
        self.mining_text.delete('1.0', tk.END)
        self.mining_text.insert('1.0', text)
        self.mining_text.config(state=tk.DISABLED)

    def refresh_mining_tab(self) -> None:
        """Waliduj w watku Tk i pobierz hotspoty i kupcow w watku roboczym (UI nie zamarza)."""
        system_name = self.mining_system_var.get().strip()
        mineral = self.mining_tab_mineral_var.get().strip()
        if not system_name or not mineral:
            return
        self.mining_btn.config(state=tk.DISABLED)
        self._set_mining_text(f'System: {system_name} | Minerał: {mineral}\n\nSzukam...')
        threading.Thread(target=self._mining_worker, args=(system_name, mineral), daemon=True).start()

    def _mining_worker(self, system_name: str, mineral: str) -> None:
        """Watek roboczy: NIE dotyka widgetow Tk — liczy i oddaje tekst przez after(0)."""
        lines = [f'System: {system_name} | Minerał: {mineral}', '']
        try:
            hotspots = find_mining_hotspots(system_name, mineral, max_ly=50, size=5)
            if hotspots:
                lines.append(f'Hotspoty ({len(hotspots)}):')
                for h in hotspots:
                    lines.append(f'  - {h.body_name} ({h.ring_name}, {h.ring_type}) {h.count}x, {h.distance:.1f} ly')
            else:
                lines.append('Brak hotspotów w zasięgu.')
        except Exception as e:
            lines.append(f'Błąd wyszukiwania hotspotów: {e}')

        lines.append('')
        try:
            buyers = find_mineral_buyers(mineral, system_name, max_ly=60, size=5)
            if buyers:
                lines.append(f'Kupcy ({len(buyers)}):')
                for b in buyers:
                    lines.append(f'  - {b.station_name} ({b.system_name}) {b.sell_price:,}cr, {b.distance:.1f} ly')
            else:
                lines.append('Brak kupców w zasięgu.')
        except Exception as e:
            lines.append(f'Błąd wyszukiwania kupców: {e}')
        try:
            self.window.after(0, self._mining_done, '\n'.join(lines))
        except Exception:
            pass

    def _mining_done(self, text: str) -> None:
        """Wywolywane w watku Tk: pokaz wynik i odblokuj przycisk."""
        self._set_mining_text(text)
        self.mining_btn.config(state=tk.NORMAL)

## Test (max 90 s). Powłoka nie ma wyświetlacza — ustaw DOSŁOWNIE:
export DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 XAUTHORITY=$(tr '\0' '\n' < /proc/$(pgrep -x plasmashell | head -1)/environ | grep ^XAUTHORITY= | cut -d= -f2)
a) cd ~/Projekty/ed-trade-overlay && python3 -m py_compile edtrade/panel.py && grep -c $'\t' edtrade/panel.py   (compile OK; grep ma wypisać 0)
b) diff /tmp/panel.py.bak-thread-min edtrade/panel.py  → wypisz CAŁY diff (3 zmiany w zakładce Mining + sekcja mining; zakładka Ustawienia i save_settings NIE mogą się zmienić). Sprawdź też: grep -n "mining_mineral_var" edtrade/panel.py → ma zostać TYLKO w zakładce Ustawienia (def + Entry) i w save_settings, NIE w zakładce Mining.
c) Test w PRAWDZIWYM mainloop (after() z wątku działa tylko gdy główny wątek jest w root.mainloop()). Uruchom DOSŁOWNIE (python3 -c "..."):
import tkinter as tk, time
from pathlib import Path
from edtrade.panel import TradePanel
root = tk.Tk(); root.withdraw()
cfg = {'journey_target_system': '', 'ship_range_ly': 30.0, 'material_kind': '', 'mining_mineral': '', 'game_window_class': 'x', 'bar_only_when_game_focused': False}
p = TradePanel(root, user_config=cfg, config_path=Path('/tmp/test_min_thread.json'))
ticks = [0]; t0 = [0.0]
def tick():
    ticks[0] += 1
    root.after(100, tick)
def start():
    print('pole minerału w zakładce Mining:', repr(p.mining_tab_mineral_var.get()), '| pole minerału w Ustawieniach:', repr(p.mining_mineral_var.get()), flush=True)
    p.mining_system_var.set('Sol'); p.mining_tab_mineral_var.set('Platinum')
    t0[0] = time.time(); p.refresh_mining_tab()
    print('refresh zwrocil po', round(time.time() - t0[0], 2), 's | przycisk:', p.mining_btn.cget('state'), '| tekst:', p.mining_text.get('1.0', 'end').strip().replace(chr(10), ' / ')[:60], flush=True)
    poll()
def poll():
    if str(p.mining_btn.cget('state')) == 'disabled' and time.time() - t0[0] < 60:
        root.after(100, poll); return
    print('calosc', round(time.time() - t0[0], 1), 's | tyniecia:', ticks[0], '| przycisk:', p.mining_btn.cget('state'), flush=True)
    print([l for l in p.mining_text.get('1.0', 'end').split(chr(10)) if l.startswith('Hotspoty') or l.startswith('Kupcy') or l.startswith('Błąd') or l.startswith('Brak')], flush=True)
    root.quit()
root.after(100, tick); root.after(500, start); root.mainloop()
   Oczekiwane: pole w zakładce Mining 'Platinum', pole w Ustawieniach '' (to dwie RÓŻNE zmienne); refresh < 0.5 s (przycisk disabled, 'Szukam...'); przycisk normal na końcu; linie 'Hotspoty (N):' i 'Kupcy (N):' z N > 0.
d) ls edtrade/ | grep -i bak → nic.
Na końcu krótko: wyniki a/b/c/d (wypisz dosłownie; jeśli przycisk został 'disabled' albo brak 'Hotspoty'/'Kupcy' — napisz to wprost, NIE twierdź że przeszło; jeśli nie możesz uruchomić testu c — podaj dosłowny błąd).
