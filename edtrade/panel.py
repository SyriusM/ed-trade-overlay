"""TCE-style panel — osobne, zwykłe okno (Alt-Tab działa), z zakładkami.

W odróżnieniu od overlay.py (cienki pasek, overrideredirect, bez fokusu),
to jest zwykły tk.Toplevel — widoczny w Alt-Tab, przeciągalny, z dekoracją.
"""

import logging
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Optional
from .config import load_user_config, save_user_config
from . import materials as mats
from datetime import datetime, timezone
from .trade import get_system_info, search_stations, find_material_traders, find_mining_hotspots, find_mineral_buyers, find_commodity_sellers, get_station_market, TradeEngine

COMMODITY_MODES = ('Kup', 'Sprzedaj')


def _data_age(updated_at: str, now: Optional[datetime] = None) -> str:
    """Wiek danych rynkowych jako krótki tekst ('3h', '2d'); '?' gdy brak/nieczytelne."""
    try:
        ts = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return '?'
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    hours = ((now or datetime.now(timezone.utc)) - ts).total_seconds() / 3600
    if hours < 1:
        return '<1h'
    return f'{hours:.0f}h' if hours < 48 else f'{hours / 24:.0f}d'

logger = logging.getLogger(__name__)


def _vs_mean(price: int, mean: int) -> str:
    """Cena wzgledem sredniej galaktycznej, np. '+12%'."""
    return f'{(price - mean) / mean * 100:+.0f}%' if mean else '?'


def _format_market(market, limit: int = 25) -> list[str]:
    """Tekst zakladki Market: naglowek z wiekiem danych, potem 'kupisz tu' i 'sprzedasz tu'."""
    lines = [f'{market.station_name} ({market.system_name})']
    if market.error:
        return lines + ['', f'Błąd: {market.error}']
    lines[0] += f' | dane {_data_age(market.updated_at)}'
    lines += ['', f'KUPISZ TU ({len(market.exports)}), najtaniej względem średniej:']
    for i in market.exports[:limit]:
        lines.append(f'  - {i.name}: {i.buy_price:,}cr ({_vs_mean(i.buy_price, i.mean_price)} vs śr.), zapas {i.stock:,}')
    if not market.exports:
        lines.append('  (nic)')
    lines += ['', f'SPRZEDASZ TU ({len(market.imports)}), najdrożej najpierw:']
    for i in market.imports[:limit]:
        lines.append(f'  - {i.name}: {i.sell_price:,}cr ({_vs_mean(i.sell_price, i.mean_price)} vs śr.), popyt {i.demand:,}')
    if not market.imports:
        lines.append('  (nic)')
    return lines


MATERIAL_HINTS = {
    'Raw': 'trader Raw / planety (zakładka Materiały)',
    'Manufactured': 'trader Manufactured / sygnały, wraki',
    'Encoded': 'trader Encoded / skanowanie',
}


def _format_engineering(bp, g_from: int, g_to: int, rolls: int, needs: list, status_line: str) -> list[str]:
    """Tekst zakladki Inzynieria: braki (z podpowiedzia gdzie zdobyc), potem to co juz masz."""
    lines = [f'{bp.label} — grade {g_from}→{g_to}, {rolls} roll(e) na grade', status_line, '']
    missing = [n for n in needs if n.missing]
    have = [n for n in needs if not n.missing]
    lines.append(f'BRAKUJE ({len(missing)}):' if missing else 'Masz wszystko potrzebne.')
    for n in missing:
        grade = f' G{n.rarity}' if n.rarity else ''
        lines.append(f'  ✗ {n.name} ({n.type}{grade}): potrzeba {n.need}, masz {n.have}, brakuje {n.missing}'
                     f' — {MATERIAL_HINTS.get(n.type, "?")}')
    if have:
        lines += ['', f'MASZ ({len(have)}):']
        for n in have:
            lines.append(f'  ✓ {n.name}: {n.have}/{n.need}')
    return lines


class TradePanel:
    """Osobne okno z zakładkami (System/Materiały/Mining/Towary/Market/Journey/Inżynieria/Ustawienia)."""

    def __init__(self, master: tk.Tk, user_config: Optional[dict] = None, config_path: Optional[Path] = None):
        self.master = master
        self.config_path = config_path
        self.user_config = user_config if user_config is not None else load_user_config(config_path)
        self.trade_engine = TradeEngine()
        self.window = tk.Toplevel(master)
        self.window.title('ED Trade Panel')
        self.window.geometry('700x450')
        # X minimalizuje okno zamiast je niszczyć — panel wraca z paska zadań / Alt-Tab
        self.window.protocol('WM_DELETE_WINDOW', self.window.iconify)

        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.tab_system = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_system, text='System')

        self.system_entry_var = tk.StringVar(value='Sol')
        self.system_entry_frame = ttk.Frame(self.tab_system)
        self.system_entry_frame.pack(fill=tk.X, padx=10, pady=(10, 4))
        ttk.Label(self.system_entry_frame, text='System:').pack(side=tk.LEFT)
        self.system_entry = ttk.Entry(self.system_entry_frame, textvariable=self.system_entry_var, width=30)
        self.system_entry.pack(side=tk.LEFT, padx=(4, 4))
        self.system_refresh_btn = ttk.Button(self.system_entry_frame, text='Odśwież', command=self.refresh_system_tab)
        self.system_refresh_btn.pack(side=tk.LEFT)

        self.system_info_text = tk.Text(self.tab_system, height=20, width=80, wrap=tk.WORD)
        self.system_info_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 10))
        self.system_info_text.insert('1.0', '(wpisz system i kliknij Odśwież)')
        self.system_info_text.config(state=tk.DISABLED)

        self.tab_materials = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_materials, text='Materiały')

        self.materials_kind_var = tk.StringVar(value='Manufactured')
        self.materials_system_var = tk.StringVar(value='Sol')
        self.materials_entry_frame = ttk.Frame(self.tab_materials)
        self.materials_entry_frame.pack(fill=tk.X, padx=10, pady=(10, 4))
        ttk.Label(self.materials_entry_frame, text='System:').pack(side=tk.LEFT)
        ttk.Entry(self.materials_entry_frame, textvariable=self.materials_system_var, width=20).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(self.materials_entry_frame, text='Rodzaj:').pack(side=tk.LEFT)
        ttk.Combobox(self.materials_entry_frame, textvariable=self.materials_kind_var, values=['Raw', 'Encoded', 'Manufactured'], width=15, state='readonly').pack(side=tk.LEFT, padx=(4, 10))
        self.materials_btn = ttk.Button(self.materials_entry_frame, text='Odśwież', command=self.refresh_materials_tab)
        self.materials_btn.pack(side=tk.LEFT)

        self.materials_text = tk.Text(self.tab_materials, height=20, width=80, wrap=tk.WORD)
        self.materials_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 10))
        self.materials_text.insert('1.0', '(wybierz system i rodzaj, kliknij Odśwież)')
        self.materials_text.config(state=tk.DISABLED)

        self.tab_mining = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_mining, text='Mining')

        self.mining_tab_mineral_var = tk.StringVar(value='Platinum')
        self.mining_system_var = tk.StringVar(value='Sol')
        self.mining_entry_frame = ttk.Frame(self.tab_mining)
        self.mining_entry_frame.pack(fill=tk.X, padx=10, pady=(10, 4))
        ttk.Label(self.mining_entry_frame, text='System:').pack(side=tk.LEFT)
        ttk.Entry(self.mining_entry_frame, textvariable=self.mining_system_var, width=20).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(self.mining_entry_frame, text='Minerał:').pack(side=tk.LEFT)
        ttk.Entry(self.mining_entry_frame, textvariable=self.mining_tab_mineral_var, width=20).pack(side=tk.LEFT, padx=(4, 10))
        self.mining_btn = ttk.Button(self.mining_entry_frame, text='Odśwież', command=self.refresh_mining_tab)
        self.mining_btn.pack(side=tk.LEFT)

        self.mining_text = tk.Text(self.tab_mining, height=20, width=80, wrap=tk.WORD)
        self.mining_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 10))
        self.mining_text.insert('1.0', '(wybierz system i minerał, kliknij Odśwież)')
        self.mining_text.config(state=tk.DISABLED)

        self.tab_commodity = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_commodity, text='Towary')

        self.commodity_system_var = tk.StringVar(value='Sol')
        self.commodity_name_var = tk.StringVar(value='Gold')
        self.commodity_mode_var = tk.StringVar(value=COMMODITY_MODES[0])
        self.commodity_entry_frame = ttk.Frame(self.tab_commodity)
        self.commodity_entry_frame.pack(fill=tk.X, padx=10, pady=(10, 4))
        ttk.Label(self.commodity_entry_frame, text='System:').pack(side=tk.LEFT)
        ttk.Entry(self.commodity_entry_frame, textvariable=self.commodity_system_var, width=18).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(self.commodity_entry_frame, text='Towar:').pack(side=tk.LEFT)
        ttk.Entry(self.commodity_entry_frame, textvariable=self.commodity_name_var, width=18).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Combobox(self.commodity_entry_frame, textvariable=self.commodity_mode_var, values=COMMODITY_MODES, width=9, state='readonly').pack(side=tk.LEFT, padx=(0, 10))
        self.commodity_btn = ttk.Button(self.commodity_entry_frame, text='Szukaj', command=self.refresh_commodity_tab)
        self.commodity_btn.pack(side=tk.LEFT)

        self.commodity_text = tk.Text(self.tab_commodity, height=20, width=80, wrap=tk.WORD)
        self.commodity_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 10))
        self.commodity_text.insert('1.0', '(wpisz system i towar, wybierz Kup/Sprzedaj, kliknij Szukaj)')
        self.commodity_text.config(state=tk.DISABLED)

        self.tab_market = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_market, text='Market')

        self.market_system_var = tk.StringVar(value='Sol')
        self.market_station_var = tk.StringVar(value='Abraham Lincoln')
        self.market_entry_frame = ttk.Frame(self.tab_market)
        self.market_entry_frame.pack(fill=tk.X, padx=10, pady=(10, 4))
        ttk.Label(self.market_entry_frame, text='System:').pack(side=tk.LEFT)
        ttk.Entry(self.market_entry_frame, textvariable=self.market_system_var, width=18).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(self.market_entry_frame, text='Stacja:').pack(side=tk.LEFT)
        ttk.Entry(self.market_entry_frame, textvariable=self.market_station_var, width=22).pack(side=tk.LEFT, padx=(4, 10))
        self.market_btn = ttk.Button(self.market_entry_frame, text='Pokaż', command=self.refresh_market_tab)
        self.market_btn.pack(side=tk.LEFT)

        self.market_text = tk.Text(self.tab_market, height=20, width=80, wrap=tk.WORD)
        self.market_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 10))
        self.market_text.insert('1.0', '(wpisz system i stację, kliknij Pokaż)')
        self.market_text.config(state=tk.DISABLED)

        self.tab_journey = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_journey, text='Journey')

        self.journey_start_var = tk.StringVar(value='Sol')
        self.journey_end_var = tk.StringVar(value='Colonia')
        self.journey_range_var = tk.StringVar(value='30.0')
        self.journey_entry_frame = ttk.Frame(self.tab_journey)
        self.journey_entry_frame.pack(fill=tk.X, padx=10, pady=(10, 4))
        ttk.Label(self.journey_entry_frame, text='Start:').pack(side=tk.LEFT)
        ttk.Entry(self.journey_entry_frame, textvariable=self.journey_start_var, width=15).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(self.journey_entry_frame, text='Cel:').pack(side=tk.LEFT)
        ttk.Entry(self.journey_entry_frame, textvariable=self.journey_end_var, width=15).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(self.journey_entry_frame, text='Zasięg (ly):').pack(side=tk.LEFT)
        ttk.Entry(self.journey_entry_frame, textvariable=self.journey_range_var, width=8).pack(side=tk.LEFT, padx=(4, 10))
        self.journey_calc_btn = ttk.Button(self.journey_entry_frame, text='Oblicz', command=self.refresh_journey_tab)
        self.journey_calc_btn.pack(side=tk.LEFT)

        self.journey_text = tk.Text(self.tab_journey, height=20, width=80, wrap=tk.WORD)
        self.journey_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 10))
        self.journey_text.insert('1.0', '(wpisz start/cel/zasięg, kliknij Oblicz — może potrwać do 2 min)')
        self.journey_text.config(state=tk.DISABLED)

        self.tab_engineering = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_engineering, text='Inżynieria')

        self._materials_lock = threading.Lock()
        self._materials_inventory: dict[str, int] = {}
        self._materials_timestamp = ''
        self._blueprints: dict[str, 'mats.Blueprint'] = {}
        self._material_table: dict[str, 'mats.MaterialInfo'] = {}

        self.eng_blueprint_var = tk.StringVar(value='')
        self.eng_grade_from_var = tk.StringVar(value='1')
        self.eng_grade_to_var = tk.StringVar(value='5')
        self.eng_rolls_var = tk.StringVar(value='1')
        self.eng_entry_frame = ttk.Frame(self.tab_engineering)
        self.eng_entry_frame.pack(fill=tk.X, padx=10, pady=(10, 4))
        self.eng_entry_frame.columnconfigure(1, weight=1)
        ttk.Label(self.eng_entry_frame, text='Blueprint:').grid(row=0, column=0, sticky='w')
        self.eng_blueprint_combo = ttk.Combobox(self.eng_entry_frame, textvariable=self.eng_blueprint_var, state='readonly')
        self.eng_blueprint_combo.grid(row=0, column=1, columnspan=6, sticky='ew', padx=(4, 0), pady=2)
        ttk.Label(self.eng_entry_frame, text='Grade od:').grid(row=1, column=0, sticky='w')
        ttk.Combobox(self.eng_entry_frame, textvariable=self.eng_grade_from_var, values=['1', '2', '3', '4', '5'],
                     width=3, state='readonly').grid(row=1, column=1, sticky='w', padx=(4, 10), pady=2)
        ttk.Label(self.eng_entry_frame, text='do:').grid(row=1, column=2, sticky='w')
        ttk.Combobox(self.eng_entry_frame, textvariable=self.eng_grade_to_var, values=['1', '2', '3', '4', '5'],
                     width=3, state='readonly').grid(row=1, column=3, sticky='w', padx=(4, 10))
        ttk.Label(self.eng_entry_frame, text='Rolle/grade:').grid(row=1, column=4, sticky='w')
        ttk.Entry(self.eng_entry_frame, textvariable=self.eng_rolls_var, width=4).grid(row=1, column=5, sticky='w', padx=(4, 10))
        self.eng_btn = ttk.Button(self.eng_entry_frame, text='Oblicz', command=self.refresh_engineering_tab, state=tk.DISABLED)
        self.eng_btn.grid(row=1, column=6, sticky='e')

        self.eng_text = tk.Text(self.tab_engineering, height=20, width=80, wrap=tk.WORD)
        self.eng_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 10))
        self.eng_text.insert('1.0', '(wczytuję listę blueprintów...)')
        self.eng_text.config(state=tk.DISABLED)
        # Start z mainloopa: after() z watku roboczego dziala tylko gdy mainloop juz chodzi
        self.window.after(200, self._start_engineering_data_load)

        # --- Zakładka Ustawienia ---
        self.tab_settings = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_settings, text='Ustawienia')

        self.settings_frame = ttk.Frame(self.tab_settings)
        self.settings_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.settings_frame.columnconfigure(1, weight=1)

        ttk.Label(self.settings_frame, text='Cel journey (system):').grid(row=0, column=0, sticky='w', padx=(0, 8), pady=4)
        self.journey_target_var = tk.StringVar(value=str(self.user_config.get('journey_target_system', '')))
        ttk.Entry(self.settings_frame, textvariable=self.journey_target_var).grid(row=0, column=1, sticky='ew', pady=4)

        ttk.Label(self.settings_frame, text='Zasięg statku (ly):').grid(row=1, column=0, sticky='w', padx=(0, 8), pady=4)
        self.ship_range_var = tk.StringVar(value=str(self.user_config.get('ship_range_ly', 30.0)))
        ttk.Entry(self.settings_frame, textvariable=self.ship_range_var).grid(row=1, column=1, sticky='ew', pady=4)

        ttk.Label(self.settings_frame, text='Materiały (kind):').grid(row=2, column=0, sticky='w', padx=(0, 8), pady=4)
        self.material_kind_var = tk.StringVar(value=str(self.user_config.get('material_kind', '')))
        ttk.Combobox(self.settings_frame, textvariable=self.material_kind_var,
                     values=['', 'Raw', 'Encoded', 'Manufactured'], state='readonly').grid(row=2, column=1, sticky='ew', pady=4)

        ttk.Label(self.settings_frame, text='Mining (minerał):').grid(row=3, column=0, sticky='w', padx=(0, 8), pady=4)
        self.mining_mineral_var = tk.StringVar(value=str(self.user_config.get('mining_mineral', '')))
        ttk.Entry(self.settings_frame, textvariable=self.mining_mineral_var).grid(row=3, column=1, sticky='ew', pady=4)

        ttk.Label(self.settings_frame, text='Klasa okna gry:').grid(row=4, column=0, sticky='w', padx=(0, 8), pady=4)
        self.game_window_class_var = tk.StringVar(value=str(self.user_config.get('game_window_class', '')))
        ttk.Entry(self.settings_frame, textvariable=self.game_window_class_var).grid(row=4, column=1, sticky='ew', pady=4)

        self.bar_only_var = tk.BooleanVar(value=bool(self.user_config.get('bar_only_when_game_focused', False)))
        ttk.Checkbutton(self.settings_frame, text='Pasek tylko gdy gra ma fokus', variable=self.bar_only_var).grid(row=5, column=1, sticky='w', pady=4)

        self.save_settings_btn = ttk.Button(self.settings_frame, text='Zapisz', command=self.save_settings)
        self.save_settings_btn.grid(row=6, column=1, sticky='w', pady=(10, 4))

        self.settings_status_var = tk.StringVar(value='')
        ttk.Label(self.settings_frame, textvariable=self.settings_status_var).grid(row=7, column=1, sticky='w', pady=4)

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

    def _set_commodity_text(self, text: str) -> None:
        self.commodity_text.config(state=tk.NORMAL)
        self.commodity_text.delete('1.0', tk.END)
        self.commodity_text.insert('1.0', text)
        self.commodity_text.config(state=tk.DISABLED)

    def refresh_commodity_tab(self) -> None:
        """Waliduj w watku Tk i szukaj gdzie kupic/sprzedac towar w watku roboczym (UI nie zamarza)."""
        system_name = self.commodity_system_var.get().strip()
        commodity = self.commodity_name_var.get().strip()
        mode = self.commodity_mode_var.get()
        if not system_name or not commodity:
            return
        self.commodity_btn.config(state=tk.DISABLED)
        self._set_commodity_text(f'{mode}: {commodity} | System: {system_name}\n\nSzukam...')
        threading.Thread(target=self._commodity_worker, args=(system_name, commodity, mode), daemon=True).start()

    def _commodity_worker(self, system_name: str, commodity: str, mode: str) -> None:
        """Watek roboczy: NIE dotyka widgetow Tk — liczy i oddaje tekst przez after(0)."""
        lines = [f'{mode}: {commodity} | System: {system_name}', '']
        try:
            if mode == 'Sprzedaj':
                buyers = find_mineral_buyers(commodity, system_name, max_ly=60, size=15)
                if buyers:
                    lines.append(f'Gdzie sprzedać ({len(buyers)}), najdrożej najpierw:')
                    for b in buyers:
                        lines.append(f'  - {b.station_name} ({b.system_name}) {b.sell_price:,}cr, popyt {b.demand:,}, '
                                     f'{b.distance:.1f} ly, pad {b.pad_size or "?"}, dane {_data_age(b.updated_at)}')
                else:
                    lines.append('Brak kupców w zasięgu (albo nieznana nazwa towaru).')
            else:
                sellers = find_commodity_sellers(commodity, system_name, max_ly=60, size=15)
                if sellers:
                    lines.append(f'Gdzie kupić ({len(sellers)}), najtaniej najpierw:')
                    for s in sellers:
                        lines.append(f'  - {s.station_name} ({s.system_name}) {s.buy_price:,}cr, zapas {s.stock:,}, '
                                     f'{s.distance:.1f} ly, pad {s.pad_size or "?"}, dane {_data_age(s.updated_at)}')
                else:
                    lines.append('Brak sprzedawców w zasięgu (albo nieznana nazwa towaru).')
        except Exception as e:
            lines.append(f'Błąd wyszukiwania: {e}')
        try:
            self.window.after(0, self._commodity_done, '\n'.join(lines))
        except Exception:
            pass

    def _commodity_done(self, text: str) -> None:
        """Wywolywane w watku Tk: pokaz wynik i odblokuj przycisk."""
        self._set_commodity_text(text)
        self.commodity_btn.config(state=tk.NORMAL)

    def show_docked_station(self, system_name: str, station_name: str) -> None:
        """Wolane z watku watchera po Docked: przekaz do watku Tk przez after(0)."""
        self.window.after(0, self._show_docked_station_inner, system_name, station_name)

    def _show_docked_station_inner(self, system_name: str, station_name: str) -> None:
        """Wpisz biezacy system/stacje w zakladki i odswiez Market (inne zakladki tylko wypelnione, bez sieci)."""
        for var in (self.system_entry_var, self.materials_system_var, self.mining_system_var,
                    self.commodity_system_var, self.market_system_var):
            var.set(system_name)
        self.market_station_var.set(station_name)
        if str(self.market_btn['state']) != tk.DISABLED:
            self.refresh_market_tab()

    def set_materials(self, event: dict) -> None:
        """Wolane z watku watchera (event Materials). Stan pod lockiem — przezyje nawet nieudane after()."""
        inventory = mats.parse_materials_event(event)
        with self._materials_lock:
            self._materials_inventory = inventory
            self._materials_timestamp = event.get('timestamp', '')
        try:
            self.window.after(0, self._materials_updated)
        except Exception:
            pass

    def _materials_updated(self) -> None:
        if str(self.eng_btn['state']) != tk.DISABLED and self.eng_blueprint_var.get():
            self.refresh_engineering_tab()

    def _start_engineering_data_load(self) -> None:
        threading.Thread(target=self._engineering_data_worker, daemon=True).start()

    def _engineering_data_worker(self) -> None:
        """Watek roboczy: pobierz (albo z cache) tabele materialow i blueprinty."""
        table = mats.load_material_table()
        blueprints = mats.load_blueprints()
        try:
            self.window.after(0, self._engineering_data_done, table, blueprints)
        except Exception:
            pass

    def _engineering_data_done(self, table: dict, blueprints: dict) -> None:
        self._material_table = table
        self._blueprints = {}
        for bp in blueprints.values():
            label = bp.label if bp.label not in self._blueprints else f'{bp.label} ({bp.key})'
            self._blueprints[label] = bp
        labels = sorted(self._blueprints)
        self.eng_blueprint_combo.config(values=labels)
        if not labels or not table:
            self._set_eng_text('Nie udało się pobrać danych blueprintów/materiałów (brak sieci i brak cache).')
            return
        self.eng_btn.config(state=tk.NORMAL)
        self._set_eng_text(f'Blueprintów: {len(labels)}. Wybierz blueprint i grade, kliknij Oblicz.\n\n'
                           + self._materials_status_line())

    def _materials_status_line(self) -> str:
        with self._materials_lock:
            count, ts = len(self._materials_inventory), self._materials_timestamp
        if not ts:
            return 'Stan materiałów: brak (event Materials pojawia się w journalu przy starcie gry).'
        return f'Stan materiałów z journala: {ts} ({count} pozycji).'

    def _set_eng_text(self, text: str) -> None:
        self.eng_text.config(state=tk.NORMAL)
        self.eng_text.delete('1.0', tk.END)
        self.eng_text.insert('1.0', text)
        self.eng_text.config(state=tk.DISABLED)

    def refresh_engineering_tab(self) -> None:
        """Bez sieci: dane juz w pamieci — liczymy w watku Tk."""
        bp = self._blueprints.get(self.eng_blueprint_var.get())
        if bp is None:
            return
        try:
            g_from, g_to = int(self.eng_grade_from_var.get()), int(self.eng_grade_to_var.get())
            rolls = int(self.eng_rolls_var.get().strip())
        except ValueError:
            self._set_eng_text('Błąd: grade i rolle muszą być liczbami.')
            return
        if g_from > g_to or rolls < 1:
            self._set_eng_text('Błąd: "grade od" nie może być większy niż "do", rolle >= 1.')
            return
        with self._materials_lock:
            inventory = dict(self._materials_inventory)
        needs = mats.missing_for(bp, g_from, g_to, rolls, inventory, self._material_table)
        self._set_eng_text('\n'.join(_format_engineering(bp, g_from, g_to, rolls, needs, self._materials_status_line())))

    def _set_market_text(self, text: str) -> None:
        self.market_text.config(state=tk.NORMAL)
        self.market_text.delete('1.0', tk.END)
        self.market_text.insert('1.0', text)
        self.market_text.config(state=tk.DISABLED)

    def refresh_market_tab(self) -> None:
        """Waliduj w watku Tk i pobierz pelny rynek stacji w watku roboczym (UI nie zamarza)."""
        system_name = self.market_system_var.get().strip()
        station_name = self.market_station_var.get().strip()
        if not system_name or not station_name:
            return
        self.market_btn.config(state=tk.DISABLED)
        self._set_market_text(f'{station_name} ({system_name})\n\nPobieram rynek...')
        threading.Thread(target=self._market_worker, args=(system_name, station_name), daemon=True).start()

    def _market_worker(self, system_name: str, station_name: str) -> None:
        """Watek roboczy: NIE dotyka widgetow Tk — liczy i oddaje tekst przez after(0)."""
        try:
            lines = _format_market(get_station_market(system_name, station_name))
        except Exception as e:
            lines = [f'{station_name} ({system_name})', '', f'Błąd: {e}']
        try:
            self.window.after(0, self._market_done, '\n'.join(lines))
        except Exception:
            pass

    def _market_done(self, text: str) -> None:
        """Wywolywane w watku Tk: pokaz wynik i odblokuj przycisk."""
        self._set_market_text(text)
        self.market_btn.config(state=tk.NORMAL)

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

    def save_settings(self) -> None:
        """Zapisz ustawienia do self.user_config (in-place) i do pliku."""
        journey_target = self.journey_target_var.get().strip()
        ship_range_str = self.ship_range_var.get().strip()
        material_kind = self.material_kind_var.get().strip()
        mining_mineral = self.mining_mineral_var.get().strip()

        # Walidacja zasięgu
        try:
            ship_range = float(ship_range_str)
        except ValueError:
            self.settings_status_var.set('Błąd: zasięg musi być liczbą.')
            return

        # Aktualizuj config in-place
        self.user_config.update({
            'journey_target_system': journey_target,
            'ship_range_ly': ship_range,
            'material_kind': material_kind,
            'mining_mineral': mining_mineral,
            'game_window_class': self.game_window_class_var.get().strip(),
            'bar_only_when_game_focused': bool(self.bar_only_var.get()),
        })

        # Zapisz do pliku
        try:
            save_user_config(self.user_config, self.config_path)
            self.settings_status_var.set('Zapisano.')
        except Exception as e:
            self.settings_status_var.set(f'Błąd zapisu: {e}')

    def show(self) -> None:
        """Pokaż okno panelu (deiconify + podnieś na wierzch)."""
        self.window.deiconify()
        self.window.lift()

    def hide(self) -> None:
        """Ukryj okno panelu."""
        self.window.withdraw()
