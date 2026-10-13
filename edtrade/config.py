"""Config użytkownika — domyślne parametry dla automatów pkt 3-5 (journey/materiały/mining).

Plik JSON w ~/.config/ed-trade-overlay/config.json. Puste pole ("") = automat wyłączony.
Klucz game_window_class = klasa okna gry (kdotool), domyślnie appid Elite Dangerous — niezweryfikowana, odczytaj z logu "Aktywne okno: class=" gdy gra ma fokus.
Klucz bar_only_when_game_focused = czy pasek ma być widoczny tylko, gdy okno gry ma fokus (domyślnie False, włączyć dopiero po zweryfikowaniu game_window_class).
Klucze min_profit_per_t / max_data_age_days = minimalny zysk na tonę i maks. wiek cen (handel w okolicy, Towary, Mining).
Klucze pad_filter (auto/large/all) / max_star_distance_ls (0 = bez limitu) / market_type (all/space/planetary) = filtry rynków (jak "Market minimum pad size" w TCE).
Klucze bar_alpha / bar_font_scale / panel_font_scale = wygląd (CONTROL jak w TCE): przezroczystość paska i skale czcionek.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_PATH = Path.home() / '.config' / 'ed-trade-overlay' / 'config.json'

DEFAULT_CONFIG: dict[str, Any] = {
    'journey_target_system': '',
    'ship_range_ly': 30.0,
    'material_kind': '',
    'mining_mineral': '',
    'game_window_class': 'steam_app_359320',
    'bar_only_when_game_focused': False,
    'bar_alpha': 0.75,
    'bar_font_scale': 1.0,
    'panel_font_scale': 1.0,
    'pad_filter': 'auto',
    'max_star_distance_ls': 5000,
    'market_type': 'all',
    'min_profit_per_t': 500,
    'max_data_age_days': 7,
    'panel_geometry': '1100x700',
    'panel_page': 'Trasa',
    'verdict_icons': True,    # ocena okazji: ikonki (= ≈ ▲ ▲▲ ▼ ▼▼)
    'verdict_labels': True,   # ocena okazji: opis (OPTIMAL, VERY SAFE…)
    'auto_copy_system': True, # nowa trasa / następny hop → cel do schowka
    'copy_target': 'station', # co kopiować: 'station', 'system' albo 'both' ("Stacja (System)")
}


def load_user_config(path: Path | None = None) -> dict[str, Any]:
    """Wczytaj config użytkownika, uzupełnij brakujące klucze domyślnymi wartościami.

    Jeśli plik nie istnieje — stwórz go z domyślną (wyłączoną) konfiguracją.
    """
    cfg_path = path if path is not None else CONFIG_PATH

    if not cfg_path.is_file():
        logger.info('Config nie istnieje, tworzę domyślny: %s', cfg_path)
        save_user_config(DEFAULT_CONFIG, cfg_path)
        return dict(DEFAULT_CONFIG)

    try:
        with open(cfg_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, IOError) as e:
        logger.warning('Błąd odczytu config %s: %s — używam domyślnych', cfg_path, e)
        return dict(DEFAULT_CONFIG)

    merged = dict(DEFAULT_CONFIG)
    merged.update(data)
    return merged


def save_user_config(config: dict[str, Any], path: Path | None = None) -> None:
    """Zapisz config do pliku JSON, tworząc katalog jeśli trzeba."""
    cfg_path = path if path is not None else CONFIG_PATH
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
