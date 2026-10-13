# Zadanie (JEDEN mały krok): zamień układ zakładki Ustawienia na `grid` — TYLKO edtrade/panel.py
Nie ruszaj main.py, trade.py ani żadnej innej metody. Nie edytuj SPEC.md. Bez researchu.

## Problem (zmierzony przeze mnie)
W `TradePanel.__init__` blok zakładki Ustawienia układa WSZYSTKIE widgety przez `pack(side=tk.LEFT)` w jednym rzędzie. Okno ma 700 px, więc ostatnie 4 widgety (etykieta+lista Materiały, Mining, przycisk Zapisz) dostają szerokość 1 px i są NIEWIDOCZNE (`winfo_ismapped() == 0`). Poprzedni Twój test sprawdzał tylko pozycję lewej krawędzi i dlatego przeszedł.

## Co zrobić
Znajdź w panel.py blok od linii `# --- Zakładka Ustawienia ---` do linii z `ttk.Label(self.settings_frame, textvariable=self.settings_status_var)...` (włącznie) i ZASTĄP go DOSŁOWNIE tym kodem (nazwy atrybutów bez zmian):

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

        self.save_settings_btn = ttk.Button(self.settings_frame, text='Zapisz', command=self.save_settings)
        self.save_settings_btn.grid(row=4, column=1, sticky='w', pady=(10, 4))

        self.settings_status_var = tk.StringVar(value='')
        ttk.Label(self.settings_frame, textvariable=self.settings_status_var).grid(row=5, column=1, sticky='w', pady=4)

## Test (max 60 s). Powłoka nie ma wyświetlacza — ustaw DOSŁOWNIE:
export DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 XAUTHORITY=$(tr '\0' '\n' < /proc/$(pgrep -x plasmashell | head -1)/environ | grep ^XAUTHORITY= | cut -d= -f2)
a) cd ~/Projekty/ed-trade-overlay && python3 -m py_compile edtrade/panel.py
b) Test na PLIKU TYMCZASOWYM (nie ruszaj ~/.config/ed-trade-overlay/config.json): utwórz tk.Tk() + withdraw(), cfg={'journey_target_system':'Colonia','ship_range_ly':32.5,'material_kind':'Raw','mining_mineral':'Platinum'}, panel=TradePanel(root, user_config=cfg, config_path=Path('/tmp/test_settings_config4.json')); panel.window.update(); panel.notebook.select(panel.tab_settings); panel.window.update();
   dla KAŻDEGO widgetu w `panel.settings_frame.winfo_children()` wypisz klasę, `winfo_ismapped()` i `winfo_width()`.
   WARUNEK ZALICZENIA: każdy widget ma ismapped()==1 ORAZ width > 20 (a przycisk Zapisz width > 40). Jeśli którykolwiek nie spełnia — napisz to wprost, NIE twierdź że przeszło.
Na końcu krótko: co zrobione + wyniki a/b (tabela widgetów).
