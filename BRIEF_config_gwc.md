# Zadanie (JEDEN mały krok, 3C-1): nowy klucz configu `game_window_class` — TYLKO edtrade/config.py
Nie ruszaj żadnego innego pliku. Nie usuwaj ani nie zmieniaj istniejących linii poza wskazaną. Bez researchu.

## Zmiana (jedna linia + jedna linia w docstringu)
1. W słowniku `DEFAULT_CONFIG` dopisz NA KOŃCU (po `'mining_mineral': '',`) nowy klucz:
    'game_window_class': 'steam_app_359320',
2. W docstringu modułu (pierwsze linie pliku) dopisz zdanie: `Klucz game_window_class = klasa okna gry (kdotool), domyślnie appid Elite Dangerous — niezweryfikowana, odczytaj z logu "Aktywne okno: class=" gdy gra ma fokus.`
Nic więcej. `load_user_config` scala domyślne klucze z plikiem, więc stary plik dostanie nowy klucz sam (nie zmieniaj tej funkcji).

## Test (max 30 s), z katalogu ~/Projekty/ed-trade-overlay. NIE dotykaj ~/.config/ed-trade-overlay/config.json — używaj plików w /tmp:
a) python3 -m py_compile edtrade/config.py
b) diff /tmp/config.py.bak-gwc edtrade/config.py  → wypisz CAŁY diff (mają być tylko linie dodane/zmieniona linia docstringu).
c) Stary format pliku dostaje nowy klucz:
   echo '{"journey_target_system": "Sol", "ship_range_ly": 25.0, "material_kind": "", "mining_mineral": ""}' > /tmp/old_cfg.json
   python3 -c "from pathlib import Path; from edtrade.config import load_user_config; c=load_user_config(Path('/tmp/old_cfg.json')); print(c)"
   Oczekiwane: słownik z 5 kluczami, journey_target_system='Sol', game_window_class='steam_app_359320'.
d) Nowy plik: rm -f /tmp/new_cfg.json; python3 -c "from pathlib import Path; from edtrade.config import load_user_config; print(load_user_config(Path('/tmp/new_cfg.json')))"; cat /tmp/new_cfg.json  → plik zawiera 5 kluczy.
Na końcu krótko: wyniki a/b/c/d (wypisz dosłownie).
