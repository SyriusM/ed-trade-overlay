"""TCE-style panel — osobne, zwykłe okno (Alt-Tab działa), z zakładkami.

W odróżnieniu od overlay.py (cienki pasek, overrideredirect, bez fokusu),
to jest zwykły tk.Toplevel — widoczny w Alt-Tab, przeciągalny, z dekoracją.
"""

import logging
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable, Optional
from .config import load_user_config, save_user_config
from . import materials as mats
from . import tce_theme as tce
from .checklist import load_commodity_names
from datetime import datetime, timezone
from .trade import get_system_info, search_stations, find_material_traders, find_mining_hotspots, find_mineral_buyers, find_commodity_sellers, get_station_market, StationMarket, JourneyPlan, TradeEngine

COMMODITY_MODES = ('Kup', 'Sprzedaj')
PANEL_TITLE = 'ED Trade Panel'


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


MATERIAL_HINTS = {
    'Raw': 'trader Raw / planety (zakładka Materiały)',
    'Manufactured': 'trader Manufactured / sygnały, wraki',
    'Encoded': 'trader Encoded / skanowanie',
}


def _hops_word(n: int) -> str:
    if n == 1:
        return 'hop'
    return 'hopy' if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 'hopów'


class TradePanel:
    """Osobne okno z zakładkami (System/Materiały/Mining/Towary/Market/Journey/Inżynieria/Ustawienia)."""

    def __init__(self, master: tk.Tk, user_config: Optional[dict] = None, config_path: Optional[Path] = None,
                 on_appearance_change: Optional[Callable[[float, float], None]] = None):
        self.master = master
        self.config_path = config_path
        self.user_config = user_config if user_config is not None else load_user_config(config_path)
        self.trade_engine = TradeEngine()
        self.window = tk.Toplevel(master)
        self.window.title(PANEL_TITLE)
        self.window.geometry('1100x700')
        self.window.configure(bg=tce.BG)
        # X minimalizuje okno zamiast je niszczyć — panel wraca z paska zadań / Alt-Tab
        self.window.protocol('WM_DELETE_WINDOW', self.window.iconify)
        self.on_appearance_change = on_appearance_change
        self.fonts = tce.Fonts(self.window, scale=float(self.user_config.get('panel_font_scale', 1.0)))
        tce.apply_ttk_theme(self.window, self.fonts)

        self.title_bar = tce.TitleBar(self.window, 'Trasa', self.fonts,
                                      on_control=self._open_settings, on_hide=self.window.iconify)
        self.title_bar.pack(fill=tk.X)
        self.notebook = ttk.Notebook(self.window, style='TCE.TNotebook')
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 8))

        self.tab_route = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_route, text='Trasa')
        self._route_lock = threading.Lock()
        self._route = None
        self.route_header = tce.SectionHeader(self.tab_route, 'Trasa handlowa', self.fonts)
        self.route_header.pack(fill=tk.X, padx=10, pady=(10, 2))
        self.route_status = tk.Label(self.tab_route, text='OCZEKIWANIE NA DOKOWANIE — TRASA LICZY SIĘ PO DOKOWANIU',
                                     bg=tce.BG, fg=tce.ORANGE_DIM, font=self.fonts.title, anchor='w')
        self.route_status.pack(fill=tk.X, padx=10, pady=(4, 6))
        self.route_cards = tk.Frame(self.tab_route, bg=tce.BG)
        self.route_cards.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

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

        self.system_header = tce.SectionHeader(self.tab_system, 'Stacje w systemie', self.fonts)
        self.system_header.pack(fill=tk.X, padx=10, pady=(8, 2))
        self.system_table = tce.DataTable(self.tab_system, [
            ('name', 'Stacja', 260, 'w'), ('type', 'Typ', 170, 'w'), ('pad', 'Pad', 80, 'center'),
            ('arrival', 'Od gwiazdy', 110, 'e'), ('economy', 'Ekonomia', 150, 'w'), ('allegiance', 'Frakcja', 130, 'w')],
            height=18)
        self.system_table.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 10))

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

        self.materials_header = tce.SectionHeader(self.tab_materials, 'Handlarze materiałów', self.fonts)
        self.materials_header.pack(fill=tk.X, padx=10, pady=(8, 2))
        self.materials_table = tce.DataTable(self.tab_materials, [
            ('name', 'Stacja', 240, 'w'), ('system', 'System', 200, 'w'), ('trader', 'Trader', 140, 'w'),
            ('distance', 'Dystans', 100, 'e'), ('arrival', 'Od gwiazdy', 110, 'e'), ('pad', 'Pad', 70, 'center')],
            height=18)
        self.materials_table.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 10))

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

        self.mining_header = tce.SectionHeader(self.tab_mining, 'Mining', self.fonts)
        self.mining_header.pack(fill=tk.X, padx=10, pady=(8, 4))
        self.mining_tables = tk.Frame(self.tab_mining, bg=tce.BG)
        self.mining_tables.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 10))
        self.mining_tables.columnconfigure((0, 1), weight=1, uniform='mn')
        self.mining_tables.rowconfigure(1, weight=1)
        self.mining_hotspots_header = tce.SectionHeader(self.mining_tables, 'Hotspoty (gdzie kopać)', self.fonts)
        self.mining_hotspots_header.grid(row=0, column=0, sticky='ew', padx=(0, 6))
        self.mining_buyers_header = tce.SectionHeader(self.mining_tables, 'Kupcy (gdzie sprzedać)', self.fonts)
        self.mining_buyers_header.grid(row=0, column=1, sticky='ew', padx=(6, 0))
        self.mining_hotspots_table = tce.DataTable(self.mining_tables, [
            ('body', 'Pierścień', 220, 'w'), ('type', 'Typ', 90, 'w'), ('count', 'Ile', 60, 'e'),
            ('distance', 'Odl.', 80, 'e'), ('arrival', 'LS', 70, 'e')], height=16)
        self.mining_hotspots_table.grid(row=1, column=0, sticky='nsew', padx=(0, 6), pady=(4, 0))
        self.mining_buyers_table = tce.DataTable(self.mining_tables, [
            ('station', 'Stacja', 170, 'w'), ('price', 'Cena', 90, 'e'), ('demand', 'Popyt', 80, 'e'),
            ('distance', 'Odl.', 80, 'e'), ('pad', 'Pad', 60, 'center'), ('age', 'Dane', 50, 'e')], height=16)
        self.mining_buyers_table.grid(row=1, column=1, sticky='nsew', padx=(6, 0), pady=(4, 0))

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
        self.commodity_btn = ttk.Button(self.commodity_entry_frame, text='Szukaj', command=self.refresh_commodity_tab)
        self.commodity_btn.pack(side=tk.LEFT)
        self.commodity_modes = tce.SegmentedButtons(
            self.tab_commodity, [(m, 'Gdzie kupić' if m == 'Kup' else 'Gdzie sprzedać') for m in COMMODITY_MODES],
            self.fonts, command=lambda _m: self.refresh_commodity_tab(), variable=self.commodity_mode_var)
        self.commodity_modes.pack(fill=tk.X, padx=10, pady=(6, 4))
        self.commodity_header = tce.SectionHeader(self.tab_commodity, 'Find location', self.fonts)
        self.commodity_header.pack(fill=tk.X, padx=10, pady=(6, 2))
        self.commodity_table = tce.DataTable(self.tab_commodity, [
            ('station', 'Stacja', 220, 'w'), ('system', 'System', 180, 'w'), ('price', 'Cena', 100, 'e'),
            ('volume', 'Zapas/popyt', 125, 'e'), ('distance', 'Dystans', 90, 'e'), ('pad', 'Pad', 70, 'center'),
            ('age', 'Dane', 60, 'e')], height=15)
        self.commodity_table.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 10))

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

        self.market_header = tce.SectionHeader(self.tab_market, 'Market details', self.fonts)
        self.market_header.pack(fill=tk.X, padx=10, pady=(8, 4))
        self.market_tables = tk.Frame(self.tab_market, bg=tce.BG)
        self.market_tables.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 10))
        self.market_tables.columnconfigure((0, 1), weight=1, uniform='m')
        self.market_tables.rowconfigure(1, weight=1)
        self.market_exports_header = tce.SectionHeader(self.market_tables, 'Kupisz tu (eksport)', self.fonts)
        self.market_exports_header.grid(row=0, column=0, sticky='ew', padx=(0, 6))
        self.market_imports_header = tce.SectionHeader(self.market_tables, 'Sprzedasz tu (import)', self.fonts)
        self.market_imports_header.grid(row=0, column=1, sticky='ew', padx=(6, 0))
        self.market_exports_table = tce.DataTable(self.market_tables, [
            ('name', 'Towar', 200, 'w'), ('price', 'Cena', 90, 'e'), ('vs', 'vs śr.', 70, 'e'),
            ('stock', 'Zapas', 90, 'e')], height=16)
        self.market_exports_table.grid(row=1, column=0, sticky='nsew', padx=(0, 6), pady=(4, 0))
        self.market_imports_table = tce.DataTable(self.market_tables, [
            ('name', 'Towar', 200, 'w'), ('price', 'Cena', 90, 'e'), ('vs', 'vs śr.', 70, 'e'),
            ('demand', 'Popyt', 90, 'e')], height=16)
        self.market_imports_table.grid(row=1, column=1, sticky='nsew', padx=(6, 0), pady=(4, 0))

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

        self.journey_header = tce.SectionHeader(self.tab_journey, 'Waypoints', self.fonts)
        self.journey_header.pack(fill=tk.X, padx=10, pady=(8, 2))
        self.journey_table = tce.DataTable(self.tab_journey, [
            ('n', '#', 50, 'e'), ('system', 'System', 320, 'w'), ('jumps', 'Skoki', 80, 'e'),
            ('jumped', 'Skok (ly)', 110, 'e'), ('left', 'Pozostało (ly)', 130, 'e'), ('neutron', 'Neutron', 90, 'center')],
            height=18)
        self.journey_table.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 10))

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

        self.eng_header = tce.SectionHeader(self.tab_engineering, 'Wczytuję listę blueprintów...', self.fonts)
        self.eng_header.pack(fill=tk.X, padx=10, pady=(8, 2))
        self.eng_status = tk.Label(self.tab_engineering, text='', bg=tce.BG, fg=tce.ORANGE_DIM,
                                   font=self.fonts.body_bold, anchor='w')
        self.eng_status.pack(fill=tk.X, padx=10)
        self.eng_table = tce.DataTable(self.tab_engineering, [
            ('name', 'Materiał', 280, 'w'), ('type', 'Typ', 120, 'w'), ('grade', 'G', 40, 'center'),
            ('need', 'Potrzeba', 90, 'e'), ('have', 'Masz', 80, 'e'), ('missing', 'Brakuje', 90, 'e'),
            ('hint', 'Gdzie zdobyć', 260, 'w')], height=16)
        self.eng_table.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 10))
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

        self.bar_alpha_var = tk.DoubleVar(value=float(self.user_config.get('bar_alpha', 0.75)))
        self.bar_scale_var = tk.DoubleVar(value=float(self.user_config.get('bar_font_scale', 1.0)))
        self.panel_scale_var = tk.DoubleVar(value=float(self.user_config.get('panel_font_scale', 1.0)))
        for row, (title, var, lo, hi) in enumerate((
                ('Przezroczystość paska:', self.bar_alpha_var, 0.3, 1.0),
                ('Czcionka paska (skala):', self.bar_scale_var, 0.7, 1.8),
                ('Czcionka panelu (skala):', self.panel_scale_var, 0.7, 1.8)), start=6):
            ttk.Label(self.settings_frame, text=title).grid(row=row, column=0, sticky='w', padx=(0, 8), pady=4)
            line = ttk.Frame(self.settings_frame)
            line.grid(row=row, column=1, sticky='ew', pady=4)
            value = ttk.Label(line, text=f'{var.get():.2f}', width=5)
            value.pack(side=tk.RIGHT)
            ttk.Scale(line, from_=lo, to=hi, variable=var, orient=tk.HORIZONTAL,
                      command=lambda _v, var=var, value=value: self._appearance_preview(var, value)).pack(
                side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self.save_settings_btn = ttk.Button(self.settings_frame, text='Zapisz', command=self.save_settings)
        self.save_settings_btn.grid(row=9, column=1, sticky='w', pady=(10, 4))

        self.settings_status_var = tk.StringVar(value='')
        ttk.Label(self.settings_frame, textvariable=self.settings_status_var).grid(row=10, column=1, sticky='w', pady=4)

        tce.uppercase_static_texts(self.window)
        self.nav = tce.NavBar(self.window, self.notebook, self.fonts, on_change=self.title_bar.set_title)
        self.nav.pack(fill=tk.X, padx=8, pady=(6, 0), before=self.notebook)

    def _appearance_preview(self, var: tk.DoubleVar, value_label: ttk.Label) -> None:
        """Suwaki CONTROL działają na żywo; zapis do configu dopiero przyciskiem ZAPISZ."""
        value_label.configure(text=f'{var.get():.2f}')
        if var is self.panel_scale_var:
            self.fonts.set_scale(var.get())
            tce.set_table_row_height(self.window, self.fonts)
        elif self.on_appearance_change is not None:
            self.on_appearance_change(self.bar_alpha_var.get(), self.bar_scale_var.get())

    def _open_settings(self) -> None:
        self.nav.select_frame(self.tab_settings)

    def refresh_system_tab(self) -> None:
        """Waliduj w watku Tk i pobierz stacje systemu w watku roboczym (UI nie zamarza)."""
        system_name = self.system_entry_var.get().strip()
        if not system_name:
            return
        self.system_refresh_btn.config(state=tk.DISABLED)
        self.system_header.set(f'{system_name} — szukam stacji...', '')
        threading.Thread(target=self._system_worker, args=(system_name,), daemon=True).start()

    def _system_worker(self, system_name: str) -> None:
        """Watek roboczy: NIE dotyka widgetow Tk — oddaje stacje przez after(0)."""
        try:
            stations, error = search_stations(system_name), ''
        except Exception as e:
            stations, error = [], str(e)
        try:
            self.window.after(0, self._system_done, system_name, stations, error)
        except Exception:
            pass

    def _system_done(self, system_name: str, stations: list, error: str) -> None:
        """Wywolywane w watku Tk: wypelnij tabele i odblokuj przycisk."""
        stations = sorted(stations, key=lambda s: s.distance_to_arrival)
        self.system_table.set_rows(
            [(s.name, s.station_type or '?', s.pad_size or '?', f'{s.distance_to_arrival:,.0f} ls',
              s.primary_economy or '?', s.allegiance or '?') for s in stations],
            sort_values=[{'arrival': s.distance_to_arrival} for s in stations])
        if error:
            self.system_header.set(f'{system_name} — błąd: {error}', '')
        elif stations:
            self.system_header.set(f'Stacje w systemie {system_name}', f'{len(stations)} stacji')
        else:
            self.system_header.set(f'{system_name}: brak danych o stacjach', '')
        self.system_refresh_btn.config(state=tk.NORMAL)

    def refresh_materials_tab(self) -> None:
        """Waliduj w watku Tk i pobierz handlarzy materialow w watku roboczym (UI nie zamarza)."""
        system_name = self.materials_system_var.get().strip()
        kind = self.materials_kind_var.get().strip()
        if not system_name or not kind:
            return
        self.materials_btn.config(state=tk.DISABLED)
        self.materials_header.set(f'Trader {kind} wokół {system_name} — szukam...', '')
        threading.Thread(target=self._materials_worker, args=(system_name, kind), daemon=True).start()

    def _materials_worker(self, system_name: str, kind: str) -> None:
        """Watek roboczy: NIE dotyka widgetow Tk — oddaje handlarzy przez after(0)."""
        try:
            traders, error = find_material_traders(system_name, kind, max_ly=50, size=25), ''
        except Exception as e:
            traders, error = [], str(e)
        try:
            self.window.after(0, self._materials_done, system_name, kind, traders, error)
        except Exception:
            pass

    def _materials_done(self, system_name: str, kind: str, traders: list, error: str) -> None:
        """Wywolywane w watku Tk: wypelnij tabele i odblokuj przycisk."""
        traders = sorted(traders, key=lambda t: t.distance)
        self.materials_table.set_rows(
            [(t.name, t.system_name, t.material_trader or t.technology_broker or kind, f'{t.distance:.1f} ly',
              f'{t.distance_to_arrival:,.0f} ls', 'L' if t.large_pads else ('M' if t.medium_pads else '?'))
             for t in traders],
            sort_values=[{'distance': t.distance, 'arrival': t.distance_to_arrival} for t in traders])
        if error:
            self.materials_header.set(f'Błąd: {error}', '')
        elif traders:
            self.materials_header.set(f'Trader {kind} wokół {system_name}', f'{len(traders)} stacji, najbliżej najpierw')
        else:
            self.materials_header.set(f'Brak traderów {kind} w zasięgu 50 ly od {system_name}', '')
        self.materials_btn.config(state=tk.NORMAL)

    def refresh_mining_tab(self) -> None:
        """Waliduj w watku Tk i pobierz hotspoty i kupcow w watku roboczym (UI nie zamarza)."""
        system_name = self.mining_system_var.get().strip()
        mineral = self.mining_tab_mineral_var.get().strip()
        if not system_name or not mineral:
            return
        self.mining_btn.config(state=tk.DISABLED)
        self.mining_header.set(f'{mineral} wokół {system_name} — szukam...', '')
        threading.Thread(target=self._mining_worker, args=(system_name, mineral), daemon=True).start()

    def _mining_worker(self, system_name: str, mineral: str) -> None:
        """Watek roboczy: NIE dotyka widgetow Tk — hotspoty i kupcy w jednym watku, wynik przez after(0)."""
        errors = []
        try:
            hotspots = find_mining_hotspots(system_name, mineral, max_ly=50, size=20)
        except Exception as e:
            hotspots = []
            errors.append(f'hotspoty: {e}')
        try:
            buyers = find_mineral_buyers(mineral, system_name, max_ly=60, size=20)
        except Exception as e:
            buyers = []
            errors.append(f'kupcy: {e}')
        try:
            self.window.after(0, self._mining_done, system_name, mineral, hotspots, buyers, '; '.join(errors))
        except Exception:
            pass

    def _mining_done(self, system_name: str, mineral: str, hotspots: list, buyers: list, error: str) -> None:
        """Wywolywane w watku Tk: wypelnij obie tabele i odblokuj przycisk."""
        self.mining_hotspots_table.set_rows(
            [(h.ring_name or h.body_name, h.ring_type, h.count, f'{h.distance:.1f} ly', f'{h.distance_to_arrival:,.0f}')
             for h in hotspots],
            sort_values=[{'count': h.count, 'distance': h.distance, 'arrival': h.distance_to_arrival} for h in hotspots])
        self.mining_buyers_table.set_rows(
            [(b.station_name, f'{b.sell_price:,}', f'{b.demand:,}', f'{b.distance:.1f} ly', b.pad_size or '?',
              _data_age(b.updated_at)) for b in buyers],
            sort_values=[{'price': b.sell_price, 'demand': b.demand, 'distance': b.distance} for b in buyers])
        self.mining_hotspots_header.set(right_text=str(len(hotspots)))
        self.mining_buyers_header.set(right_text=str(len(buyers)))
        self.mining_header.set(f'Błąd: {error}' if error else f'{mineral} wokół {system_name}', '')
        self.mining_btn.config(state=tk.NORMAL)

    def refresh_commodity_tab(self) -> None:
        """Waliduj w watku Tk i szukaj gdzie kupic/sprzedac towar w watku roboczym (UI nie zamarza)."""
        system_name = self.commodity_system_var.get().strip()
        commodity = self.commodity_name_var.get().strip()
        mode = self.commodity_mode_var.get()
        if not system_name or not commodity or str(self.commodity_btn['state']) == tk.DISABLED:
            return
        self.commodity_btn.config(state=tk.DISABLED)
        self.commodity_header.set(f'{commodity} — szukam wokół {system_name}...', '')
        threading.Thread(target=self._commodity_worker, args=(system_name, commodity, mode), daemon=True).start()

    def _commodity_worker(self, system_name: str, commodity: str, mode: str) -> None:
        """Watek roboczy: NIE dotyka widgetow Tk — pobiera dane i oddaje wiersze przez after(0)."""
        rows, error = [], ''
        try:
            if mode == 'Sprzedaj':
                rows = [(b.station_name, b.system_name, f'{b.sell_price:,} cr', f'{b.demand:,}', f'{b.distance:.1f} ly',
                         b.pad_size or '?', _data_age(b.updated_at),
                         {'price': b.sell_price, 'volume': b.demand, 'distance': b.distance})
                        for b in find_mineral_buyers(commodity, system_name, max_ly=60, size=25)]
            else:
                rows = [(s.station_name, s.system_name, f'{s.buy_price:,} cr', f'{s.stock:,}', f'{s.distance:.1f} ly',
                         s.pad_size or '?', _data_age(s.updated_at),
                         {'price': s.buy_price, 'volume': s.stock, 'distance': s.distance})
                        for s in find_commodity_sellers(commodity, system_name, max_ly=60, size=25)]
        except Exception as e:
            error = str(e)
        try:
            self.window.after(0, self._commodity_done, commodity, system_name, mode, rows, error)
        except Exception:
            pass

    def _commodity_done(self, commodity: str, system_name: str, mode: str, rows: list, error: str) -> None:
        """Wywolywane w watku Tk: pokaz wynik i odblokuj przycisk."""
        self.commodity_table.set_rows([r[:-1] for r in rows], sort_values=[r[-1] for r in rows])
        what = 'kupić' if mode == 'Kup' else 'sprzedać'
        if error:
            self.commodity_header.set(f'Błąd: {error}', '')
        elif rows:
            order = 'najtaniej najpierw' if mode == 'Kup' else 'najdrożej najpierw'
            self.commodity_header.set(f'Gdzie {what}: {commodity} (wokół {system_name})', f'{len(rows)} stacji, {order}')
        else:
            self.commodity_header.set(f'Brak stacji, gdzie {what} {commodity} (albo nieznana nazwa)', '')
        self.commodity_btn.config(state=tk.NORMAL)

    def show_route(self, route) -> None:
        """Wolane z watku watchera (nowa trasa albo zmiana checklisty). Stan pod lockiem, render w watku Tk."""
        with self._route_lock:
            self._route = route
        try:
            self.window.after(0, self._render_route)
        except Exception:
            pass

    def _render_route(self) -> None:
        """Karty hopow jak w Route Finder TCE: → kup tu / ← sprzedaj tam, po prawej dystans i zysk."""
        with self._route_lock:
            route = self._route
        for child in self.route_cards.winfo_children():
            child.destroy()
        if route is None:
            return
        if route.error:
            self.route_header.set('Trasa handlowa', '')
            self.route_status.config(text=f'BŁĄD TRASY: {route.error}'.upper(), fg=tce.RED)
            return
        hops = route.hops_list or []
        current = getattr(route, '_current_hop', 1)
        steps = getattr(route, '_checklist_text', '')
        finished = 'ukończona' in steps
        start = hops[0] if hops else None
        self.route_header.set(f'Trasa z {start.source_system} · {start.source_station}' if start else 'Trasa handlowa',
                              f'{len(hops)} {_hops_word(len(hops))} · zysk {route.total_profit:,} cr')
        if finished:
            self.route_status.config(text='TRASA UKOŃCZONA', fg=tce.GREEN)
        else:
            self.route_status.config(text=f'TRASA AKTYWNA — HOP {current}/{len(hops)}', fg=tce.GREEN)
        for i, hop in enumerate(hops, 1):
            self._route_card(i, hop, done=finished or i < current, active=not finished and i == current,
                             steps=steps if not finished and i == current else '')

    def _route_card(self, index: int, hop, done: bool, active: bool, steps: str) -> None:
        f = self.fonts
        bg = tce.ROW_BG if active else tce.ROW_BG_DARK
        fg = tce.ORANGE_DIM if done else tce.ORANGE
        card = tk.Frame(self.route_cards, bg=bg, highlightthickness=2 if active else 1,
                        highlightbackground=tce.ORANGE if active else tce.ORANGE_DIM)
        card.pack(fill=tk.X, pady=(0, 6))
        card.columnconfigure(1, weight=1)
        mark = '✓' if done else ('▶' if active else str(index))
        tk.Label(card, text=mark, bg=bg, fg=tce.GREEN if done else fg, font=f.big, width=3).grid(
            row=0, column=0, rowspan=3, sticky='ns')
        buy = f'→  {hop.source_station} · {hop.source_system}    KUP {hop.commodity} ×{hop.amount} @ {hop.buy_price:,} CR'
        sell = f'←  {hop.destination_station} · {hop.destination_system}    SPRZEDAJ @ {hop.sell_price:,} CR'
        tk.Label(card, text=buy.upper(), bg=bg, fg=fg, font=f.body_bold, anchor='w').grid(
            row=0, column=1, sticky='ew', padx=(4, 8), pady=(6, 0))
        tk.Label(card, text=sell.upper(), bg=bg, fg=fg, font=f.body_bold, anchor='w').grid(
            row=1, column=1, sticky='ew', padx=(4, 8), pady=(0, 6 if not steps else 0))
        if steps:
            tk.Label(card, text=steps.upper(), bg=bg, fg=tce.TEXT_WHITE, font=f.body_bold, anchor='w').grid(
                row=2, column=1, sticky='ew', padx=(4, 8), pady=(2, 6))
        profit = hop.profit if hop.profit > 0 else (hop.sell_price - hop.buy_price) * hop.amount
        side = tk.Frame(card, bg=bg)
        side.grid(row=0, column=2, rowspan=3, sticky='e', padx=(8, 12))
        if hop.distance:
            tk.Label(side, text=f'{hop.distance:.2f} LY', bg=bg, fg=tce.TEXT_WHITE if not done else fg,
                     font=f.section, anchor='e').pack(anchor='e')
        tk.Label(side, text=f'+{profit:,} CR', bg=bg, fg=tce.GREEN if not done else fg,
                 font=f.big, anchor='e').pack(anchor='e')

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
            self.eng_header.set('Nie udało się pobrać danych blueprintów/materiałów (brak sieci i brak cache)', '')
            return
        self.eng_btn.config(state=tk.NORMAL)
        self.eng_header.set('Wybierz blueprint i grade, kliknij Oblicz', f'{len(labels)} blueprintów')
        self.eng_status.config(text=self._materials_status_line().upper())

    def _materials_status_line(self) -> str:
        with self._materials_lock:
            count, ts = len(self._materials_inventory), self._materials_timestamp
        if not ts:
            return 'Stan materiałów: brak (event Materials pojawia się w journalu przy starcie gry).'
        return f'Stan materiałów z journala: {ts} ({count} pozycji).'

    def refresh_engineering_tab(self) -> None:
        """Bez sieci: dane juz w pamieci — liczymy w watku Tk."""
        bp = self._blueprints.get(self.eng_blueprint_var.get())
        if bp is None:
            return
        try:
            g_from, g_to = int(self.eng_grade_from_var.get()), int(self.eng_grade_to_var.get())
            rolls = int(self.eng_rolls_var.get().strip())
        except ValueError:
            self.eng_header.set('Błąd: grade i rolle muszą być liczbami', '')
            return
        if g_from > g_to or rolls < 1:
            self.eng_header.set('Błąd: "grade od" nie może być większy niż "do", rolle >= 1', '')
            return
        with self._materials_lock:
            inventory = dict(self._materials_inventory)
        needs = mats.missing_for(bp, g_from, g_to, rolls, inventory, self._material_table)
        self.eng_table.set_rows(
            [(n.name, n.type, f'G{n.rarity}' if n.rarity else '?', n.need, n.have, n.missing or '✓',
              MATERIAL_HINTS.get(n.type, '?') if n.missing else '') for n in needs],
            sort_values=[{'need': n.need, 'have': n.have, 'missing': n.missing, 'grade': n.rarity} for n in needs],
            tags=['bad' if n.missing else 'good' for n in needs])
        missing = sum(1 for n in needs if n.missing)
        self.eng_header.set(f'{bp.label} — grade {g_from}→{g_to}, {rolls} roll/grade',
                            f'brakuje {missing} z {len(needs)}' if missing else 'masz wszystko')
        self.eng_status.config(text=self._materials_status_line().upper())

    def refresh_market_tab(self) -> None:
        """Waliduj w watku Tk i pobierz pelny rynek stacji w watku roboczym (UI nie zamarza)."""
        system_name = self.market_system_var.get().strip()
        station_name = self.market_station_var.get().strip()
        if not system_name or not station_name:
            return
        self.market_btn.config(state=tk.DISABLED)
        self.market_header.set(f'{station_name} ({system_name}) — pobieram rynek...', '')
        threading.Thread(target=self._market_worker, args=(system_name, station_name), daemon=True).start()

    def _market_worker(self, system_name: str, station_name: str) -> None:
        """Watek roboczy: NIE dotyka widgetow Tk — pobiera rynek i oddaje go przez after(0)."""
        try:
            market = get_station_market(system_name, station_name)
            names = load_commodity_names()
            for item in market.exports + market.imports:
                item.name = names.get(item.name.lower(), item.name)
        except Exception as e:
            market = StationMarket(system_name=system_name, station_name=station_name, error=str(e))
        try:
            self.window.after(0, self._market_done, market)
        except Exception:
            pass

    def _market_done(self, market: 'StationMarket') -> None:
        """Wywolywane w watku Tk: wypelnij tabele i odblokuj przycisk."""
        exports = market.exports
        imports = market.imports
        self.market_exports_table.set_rows(
            [(i.name, f'{i.buy_price:,}', _vs_mean(i.buy_price, i.mean_price), f'{i.stock:,}') for i in exports],
            sort_values=[{'price': i.buy_price, 'vs': i.buy_price - i.mean_price, 'stock': i.stock} for i in exports])
        self.market_imports_table.set_rows(
            [(i.name, f'{i.sell_price:,}', _vs_mean(i.sell_price, i.mean_price), f'{i.demand:,}') for i in imports],
            sort_values=[{'price': i.sell_price, 'vs': i.sell_price - i.mean_price, 'demand': i.demand} for i in imports],
            tags=['good' if i.mean_price and i.sell_price > i.mean_price else '' for i in imports])
        title = f'{market.station_name} ({market.system_name})'
        if market.error:
            self.market_header.set(f'{title} — błąd: {market.error}', '')
        else:
            self.market_header.set(title, f'dane {_data_age(market.updated_at)}')
        self.market_exports_header.set(right_text=str(len(exports)))
        self.market_imports_header.set(right_text=str(len(imports)))
        self.market_btn.config(state=tk.NORMAL)

    def refresh_journey_tab(self) -> None:
        """Waliduj dane w watku Tk i uruchom obliczenie trasy Spansh w watku roboczym (UI nie zamarza)."""
        start = self.journey_start_var.get().strip()
        end = self.journey_end_var.get().strip()
        try:
            ship_range = float(self.journey_range_var.get().strip())
        except ValueError:
            self.journey_header.set('Błąd: zasięg musi być liczbą', '')
            return
        if not start or not end:
            return
        self.journey_calc_btn.config(state=tk.DISABLED)
        self.journey_header.set(f'{start} → {end} (zasięg {ship_range} ly) — liczę trasę, do 2 min...', '')
        threading.Thread(target=self._journey_worker, args=(start, end, ship_range), daemon=True).start()

    def _journey_worker(self, start: str, end: str, ship_range: float) -> None:
        """Watek roboczy: NIE dotyka widgetow Tk — oddaje plan przez after(0)."""
        try:
            plan = self.trade_engine.plan_journey(start, end, ship_range)
        except Exception as e:
            plan = JourneyPlan(start_system=start, end_system=end, error=str(e))
        try:
            self.window.after(0, self._journey_done, plan)
        except Exception:
            pass

    def _journey_done(self, plan: 'JourneyPlan') -> None:
        """Wywolywane w watku Tk: wypelnij tabele waypointow i odblokuj przycisk."""
        hops = [] if plan.error else plan.hops
        self.journey_table.set_rows(
            [(i, h.system, h.jumps, f'{h.distance_jumped:.1f}', f'{h.distance_left:.1f}', '★' if h.neutron_star else '')
             for i, h in enumerate(hops, 1)],
            sort_values=[{'n': i, 'jumps': h.jumps, 'jumped': h.distance_jumped, 'left': h.distance_left}
                         for i, h in enumerate(hops, 1)],
            tags=['good' if h.neutron_star else '' for h in hops])
        if plan.error:
            self.journey_header.set(f'Błąd: {plan.error}', '')
        else:
            self.journey_header.set(f'{plan.start_system} → {plan.end_system}',
                                    f'{plan.total_jumps} skoków · {plan.total_distance:,.0f} ly')
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
            'bar_alpha': round(self.bar_alpha_var.get(), 2),
            'bar_font_scale': round(self.bar_scale_var.get(), 2),
            'panel_font_scale': round(self.panel_scale_var.get(), 2),
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
