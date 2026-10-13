# Zadanie (JEDEN mały krok, 3C-2): nowy klucz configu `bar_only_when_game_focused` — TYLKO edtrade/config.py
Nie ruszaj żadnego innego pliku. NIE twórz żadnych dodatkowych plików (żadnych .bak ani kopii w katalogu edtrade/ ani projektu — kopia zapasowa już jest w /tmp/config.py.bak-bar). Nie usuwaj ani nie zmieniaj istniejących linii poza wskazaną. Bez researchu.

## Zmiana (jedna linia + jedna linia w docstringu)
1. W słowniku `DEFAULT_CONFIG` dopisz NA KOŃCU (po `'game_window_class': 'steam_app_359320',`) nowy klucz:
    'bar_only_when_game_focused': False,
2. W docstringu modułu, zaraz po zdaniu zaczynającym się od `Klucz game_window_class`, dopisz nową linię: `Klucz bar_only_when_game_focused = czy pasek ma być widoczny tylko, gdy okno gry ma fokus (domyślnie False, włączyć dopiero po zweryfikowaniu game_window_class).`
Nic więcej. Nie zmieniaj `load_user_config` ani `save_user_config`.

## Test (max 30 s), z katalogu ~/Projekty/ed-trade-overlay. NIE dotykaj ~/.config/ed-trade-overlay/config.json — używaj plików w /tmp:
a) python3 -m py_compile edtrade/config.py
b) diff /tmp/config.py.bak-bar edtrade/config.py  → wypisz CAŁY diff (tylko 2 dodane linie).
c) echo '{"journey_target_system": "Sol", "ship_range_ly": 25.0, "material_kind": "", "mining_mineral": "", "game_window_class": "steam_app_359320"}' > /tmp/old_cfg3.json
   python3 -c "from pathlib import Path; from edtrade.config import load_user_config; print(load_user_config(Path('/tmp/old_cfg3.json')))"
   Oczekiwane: słownik z 6 kluczami, 'bar_only_when_game_focused': False, journey_target_system='Sol'.
d) rm -f /tmp/new_cfg3.json; python3 -c "from pathlib import Path; from edtrade.config import load_user_config; load_user_config(Path('/tmp/new_cfg3.json'))"; cat /tmp/new_cfg3.json  → 6 kluczy w pliku.
e) ls edtrade/ | grep -i bak  → ma nic nie wypisać.
Na końcu krótko: wyniki a/b/c/d/e (wypisz dosłownie).
