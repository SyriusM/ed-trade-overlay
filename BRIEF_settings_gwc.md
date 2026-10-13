# Zadanie (JEDEN mały krok, 3C-3): dwa nowe pola w zakładce Ustawienia — TYLKO edtrade/panel.py
Nie ruszaj żadnego innego pliku. NIE twórz żadnych plików poza zmianą panel.py (żadnych .bak — kopia zapasowa jest już w /tmp/panel.py.bak-gwc). Nie usuwaj ani nie zmieniaj niczego poza opisanymi dwoma edycjami. Bez researchu.
Kontekst: config ma już klucze `game_window_class` (str) i `bar_only_when_game_focused` (bool). Panel ma pozostałe 4 pola w układzie grid (wiersze 0-3).

## Edycja 1 — blok przycisku i statusu w `TradePanel.__init__`
Znajdź te DWA fragmenty (tuż po wierszu 'Mining (minerał)'):

        self.save_settings_btn = ttk.Button(self.settings_frame, text='Zapisz', command=self.save_settings)
        self.save_settings_btn.grid(row=4, column=1, sticky='w', pady=(10, 4))

        self.settings_status_var = tk.StringVar(value='')
        ttk.Label(self.settings_frame, textvariable=self.settings_status_var).grid(row=5, column=1, sticky='w', pady=4)

i ZASTĄP je DOSŁOWNIE tym kodem:

        ttk.Label(self.settings_frame, text='Klasa okna gry:').grid(row=4, column=0, sticky='w', padx=(0, 8), pady=4)
        self.game_window_class_var = tk.StringVar(value=str(self.user_config.get('game_window_class', '')))
        ttk.Entry(self.settings_frame, textvariable=self.game_window_class_var).grid(row=4, column=1, sticky='ew', pady=4)

        self.bar_only_var = tk.BooleanVar(value=bool(self.user_config.get('bar_only_when_game_focused', False)))
        ttk.Checkbutton(self.settings_frame, text='Pasek tylko gdy gra ma fokus', variable=self.bar_only_var).grid(row=5, column=1, sticky='w', pady=4)

        self.save_settings_btn = ttk.Button(self.settings_frame, text='Zapisz', command=self.save_settings)
        self.save_settings_btn.grid(row=6, column=1, sticky='w', pady=(10, 4))

        self.settings_status_var = tk.StringVar(value='')
        ttk.Label(self.settings_frame, textvariable=self.settings_status_var).grid(row=7, column=1, sticky='w', pady=4)

## Edycja 2 — metoda `save_settings`
W metodzie `save_settings` znajdź wywołanie `self.user_config.update({ ... })`. Do słownika w tym update dopisz DWA klucze na końcu (po `'mining_mineral': mining_mineral,`):
            'game_window_class': self.game_window_class_var.get().strip(),
            'bar_only_when_game_focused': bool(self.bar_only_var.get()),
Reszty `save_settings` (walidacja zasięgu, zapis, statusy) NIE zmieniaj.

## Test (max 90 s). Powłoka nie ma wyświetlacza — ustaw DOSŁOWNIE:
export DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 XAUTHORITY=$(tr '\0' '\n' < /proc/$(pgrep -x plasmashell | head -1)/environ | grep ^XAUTHORITY= | cut -d= -f2)
a) cd ~/Projekty/ed-trade-overlay && python3 -m py_compile edtrade/panel.py
b) diff /tmp/panel.py.bak-gwc edtrade/panel.py  → wypisz CAŁY diff (tylko przesunięcie przycisku/statusu + nowe wiersze + 2 klucze w update).
c) Test GUI na PLIKU TYMCZASOWYM (nie ruszaj ~/.config/ed-trade-overlay/config.json): tk.Tk()+withdraw(); cfg={'journey_target_system':'Colonia','ship_range_ly':32.5,'material_kind':'Raw','mining_mineral':'Platinum','game_window_class':'steam_app_359320','bar_only_when_game_focused':False}; panel=TradePanel(root, user_config=cfg, config_path=Path('/tmp/test_settings_config6.json')); panel.window.update(); panel.notebook.select(panel.tab_settings); panel.window.update();
   - dla KAŻDEGO widgetu w panel.settings_frame.winfo_children() wypisz klasę, winfo_ismapped(), winfo_width() (zaliczenie: ismapped==1 i width>20; przycisk Zapisz >40; pusta etykieta statusu może mieć mały width — zaznacz to);
   - wypisz panel.game_window_class_var.get() (oczekiwane 'steam_app_359320') i panel.bar_only_var.get() (False);
   - ustaw panel.game_window_class_var.set('Elite-Dangerous'), panel.bar_only_var.set(True), wywołaj panel.save_settings(); wypisz cfg['game_window_class'], cfg['bar_only_when_game_focused'] i zawartość /tmp/test_settings_config6.json (oba klucze zapisane);
   - ustaw panel.ship_range_var.set('abc'), save_settings(); wypisz status i że cfg['ship_range_ly'] nadal 32.5.
d) ls edtrade/ | grep -i bak → ma nic nie wypisać.
Na końcu krótko: wyniki a/b/c/d (wypisz dosłownie; nie pisz "zaliczone", jeśli jakikolwiek widget ma mapped=0 lub width<=20 poza pustą etykietą).
