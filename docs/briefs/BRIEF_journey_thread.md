# Zadanie (JEDEN krok, 4B): obliczanie trasy Journey w wątku roboczym (UI nie zamarza) — TYLKO edtrade/panel.py
Nie ruszaj żadnego innego pliku. NIE twórz żadnych plików (żadnych .bak; kopia jest w /tmp/panel.py.bak-thread). Nie zmieniaj innych zakładek ani metod poza opisanymi. Bez researchu.
**WCIĘCIA: WYŁĄCZNIE SPACJE (4 spacje na poziom), ŻADNYCH TABULATORÓW** — poprzednia sesja wstawiła tabulatory i zepsuła plik (TabError). Nie używaj polskich znaków w komentarzach, jeśli nie jesteś pewien kodowania; kopiuj kod DOSŁOWNIE z tego briefu.
Problem: `refresh_journey_tab` woła `self.trade_engine.plan_journey(...)` w wątku Tk — przy Sol→Colonia to ~15-20 s zamrożenia całego UI (do 120 s przy timeoucie).

## Edycja 1 — import
Pod linią `import logging` (na górze pliku) dopisz linię: `import threading`

## Edycja 2 — nazwany przycisk
Znajdź linię (w zakładce Journey, ok. linii 102):
        ttk.Button(self.journey_entry_frame, text='Oblicz', command=self.refresh_journey_tab).pack(side=tk.LEFT)
i ZASTĄP ją DWIEMA liniami:
        self.journey_calc_btn = ttk.Button(self.journey_entry_frame, text='Oblicz', command=self.refresh_journey_tab)
        self.journey_calc_btn.pack(side=tk.LEFT)

## Edycja 3 — zastąp CAŁĄ metodę `refresh_journey_tab`
Od linii `    def refresh_journey_tab(self) -> None:` do linii tuż PRZED `    def save_settings(self) -> None:` (nie ruszaj `save_settings`) wstaw DOSŁOWNIE:

    def _set_journey_text(self, text: str) -> None:
        self.journey_text.config(state=tk.NORMAL)
        self.journey_text.delete('1.0', tk.END)
        self.journey_text.insert('1.0', text)
        self.journey_text.config(state=tk.DISABLED)

    def refresh_journey_tab(self) -> None:
        """Waliduj dane w watku Tk i uruchom obliczenie trasy Spansh w watku roboczym (UI nie zamarza)."""
        start = self.journey_start_var.get().strip()
        end = self.journey_end_var.get().strip()
        try:
            ship_range = float(self.journey_range_var.get().strip())
        except ValueError:
            self._set_journey_text('Błąd: zasięg musi być liczbą.')
            return
        if not start or not end:
            return
        self.journey_calc_btn.config(state=tk.DISABLED)
        self._set_journey_text(f'{start} -> {end} (zasięg {ship_range} ly)\n\nLiczę trasę... (do 2 min)')
        threading.Thread(target=self._journey_worker, args=(start, end, ship_range), daemon=True).start()

    def _journey_worker(self, start: str, end: str, ship_range: float) -> None:
        """Watek roboczy: NIE dotyka widgetow Tk — liczy i oddaje tekst przez after(0)."""
        lines = [f'{start} -> {end} (zasięg {ship_range} ly)', '']
        try:
            plan = self.trade_engine.plan_journey(start, end, ship_range)
            if plan.error:
                lines.append(f'Błąd: {plan.error}')
            else:
                lines.append(f'Skoki: {plan.total_jumps} | Dystans: {plan.total_distance:.1f} ly')
                lines.append('')
                for hop in plan.hops[:30]:
                    neutron = ' [neutron]' if getattr(hop, 'neutron_star', False) else ''
                    lines.append(f'  - {hop.system} ({hop.jumps} skoki, {hop.distance_jumped:.1f} ly){neutron}')
        except Exception as e:
            lines.append(f'Błąd kalkulacji: {e}')
        try:
            self.window.after(0, self._journey_done, '\n'.join(lines))
        except Exception:
            pass

    def _journey_done(self, text: str) -> None:
        """Wywolywane w watku Tk: pokaz wynik i odblokuj przycisk."""
        self._set_journey_text(text)
        self.journey_calc_btn.config(state=tk.NORMAL)

## Test (max 150 s). Powłoka nie ma wyświetlacza — ustaw DOSŁOWNIE:
export DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 XAUTHORITY=$(tr '\0' '\n' < /proc/$(pgrep -x plasmashell | head -1)/environ | grep ^XAUTHORITY= | cut -d= -f2)
a) cd ~/Projekty/ed-trade-overlay && python3 -m py_compile edtrade/panel.py && grep -c $'\t' edtrade/panel.py   (compile OK; grep ma wypisać 0 — brak tabulatorów)
b) diff /tmp/panel.py.bak-thread edtrade/panel.py  → wypisz CAŁY diff (import, 2 linie przycisku, nowa/zmieniona sekcja journey; nic poza tym).
c) Test GUI z REALNYM Spansh (Sol→Colonia ~15-20 s):
python3 -c "
import tkinter as tk, time
from pathlib import Path
from edtrade.panel import TradePanel
root = tk.Tk(); root.withdraw()
cfg = {'journey_target_system': '', 'ship_range_ly': 30.0, 'material_kind': '', 'mining_mineral': '', 'game_window_class': 'x', 'bar_only_when_game_focused': False}
p = TradePanel(root, user_config=cfg, config_path=Path('/tmp/test_thread_config.json'))
p.window.update()
ticks = [0]
def tick():
    ticks[0] += 1
    root.after(100, tick)
tick()
p.journey_start_var.set('Sol'); p.journey_end_var.set('Colonia'); p.journey_range_var.set('30')
t0 = time.time()
p.refresh_journey_tab()
print('refresh zwrocil po', round(time.time() - t0, 2), 's | przycisk:', p.journey_calc_btn.cget('state'), '| tekst:', p.journey_text.get('1.0', 'end').strip().replace(chr(10), ' / ')[:70])
while str(p.journey_calc_btn.cget('state')) == 'disabled' and time.time() - t0 < 140:
    root.update(); time.sleep(0.02)
print('calosc', round(time.time() - t0, 1), 's | tyniecia:', ticks[0], '| przycisk:', p.journey_calc_btn.cget('state'))
print([l for l in p.journey_text.get('1.0', 'end').split(chr(10)) if l.startswith('Skoki') or l.startswith('Błąd')])
p.journey_range_var.set('abc'); p.refresh_journey_tab()
print('zly zasieg ->', p.journey_text.get('1.0', 'end').strip(), '| przycisk:', p.journey_calc_btn.cget('state'))
"
   Oczekiwane: 'refresh zwrocil po' < 1 s (przycisk disabled, tekst 'Liczę trasę...'); 'calosc' ~10-40 s; tyniecia > 80; przycisk normal; linia 'Skoki: 390 | ...' (liczba > 0); zły zasięg -> 'Błąd: zasięg musi być liczbą.' i przycisk normal.
d) ls edtrade/ | grep -i bak → nic.
Na końcu krótko: wyniki a/b/c/d (wypisz dosłownie; jeśli 'refresh zwrocil po' > 2 s — napisz to wprost, to znaczy że wątek nie działa).
