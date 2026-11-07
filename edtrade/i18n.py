"""UI language: Polish (the source language of every text in the code) or English.

The code keeps writing its texts in Polish. When English is selected, `install()` hooks Tk so that every
widget text (labels, buttons, tabs, table headings and cells) passes through `tr()` on its way to the screen.
`tr()` first looks the whole text up in the table, then translates the known phrases inside longer, composed
texts (e.g. "LICZĘ TRASĘ… 12s"). Upper case is kept: "BŁĄD TRASY" becomes "ROUTE ERROR".

Language is picked once at start-up (config key `language`: "auto" / "pl" / "en"); "auto" follows the
system locale — Polish for pl_*, English otherwise.
"""

from __future__ import annotations

import locale
import os
import re
from typing import Any, Optional

LANGUAGES = {'auto': 'Auto (system)', 'pl': 'Polski', 'en': 'English'}

# Polski → English. Klucze: całe teksty albo frazy, które występują w złożonych tekstach (f-stringi).
EN: dict[str, str] = {
    # --- nawigacja i strony panelu ---
    'Handel': 'Trade', 'Nawigacja': 'Navigation', 'Inżynieria': 'Engineering', 'Eksploracja': 'Exploration',
    'Ustawienia': 'Settings', 'Trasa': 'Route', 'Okolica': 'Nearby', 'Porównaj': 'Compare',
    'Towary': 'Commodities', 'Materiały': 'Materials', 'Blueprinty': 'Blueprints', 'Sesja': 'Session',
    'Najlepsza trasa z bieżącej stacji — liczy się sama po dokowaniu, kroki odhaczają się z gry.':
        'Best route from the current station — plotted automatically after docking, steps tick off from the game.',
    'klik: SWOT · dwuklik: kopiuj system': 'click: SWOT · double-click: copy system',
    'Bieżąca stacja vs cel (jak Trade Overview w TCE). Otwórz z OKOLICY: prawy klik → Porównaj.':
        'Current station vs destination (like Trade Overview in TCE). Open from NEARBY: right-click → Compare.',
    'Pełny rynek jednej stacji. Wypełnia się sam po dokowaniu.':
        'Full market of one station. Fills in by itself after docking.',
    'Gdzie najtaniej kupić / najdrożej sprzedać dowolny towar. Wpisz kilka liter — lista podpowie. Dwuklik: kopiuj system.':
        'Where to buy cheapest / sell highest for any commodity. Type a few letters — the list suggests. '
        'Double-click: copy system.',
    'Trasa skoków A → B (Spansh). Dwuklik na systemie: kopiuj do mapy galaktyki.':
        'Jump route A → B (Spansh). Double-click a system: copy it for the galaxy map.',
    'Stacje w systemie. Dwuklik: kopiuj system · prawy klik: rynek / porównaj.':
        'Stations in the system. Double-click: copy system · right-click: market / compare.',
    'Najbliżsi handlarze materiałów. Dwuklik: kopiuj system.': 'Nearest material traders. Double-click: copy system.',
    'Gdzie kopać (hotspoty) i gdzie sprzedać. Minerał: kilka liter i wybór z listy. Dwuklik: kopiuj system.':
        'Where to mine (hotspots) and where to sell. Mineral: type a few letters and pick from the list. '
        'Double-click: copy system.',
    'Czego brakuje do ulepszenia — wpisz kilka liter blueprintu i wybierz z listy. Stan materiałów z journala.':
        'What is missing for an upgrade — type a few letters of a blueprint and pick from the list. '
        'Materials from the journal.',
    'Zarobki z tej sesji gry (od uruchomienia gry), liczone z journala. Prawy klik: rynek stacji.':
        'Earnings of this game session (since the game started), counted from the journal. Right-click: station market.',
    'Filtry rynków, wygląd paska i panelu. Zmiany zapisują się same.':
        'Market filters, bar and panel look. Changes are saved automatically.',
    'Najbliższe ruiny i struktury Guardian (Spansh). Dwuklik: kopiuj system · zaznacz wiersz: współrzędne miejsc na planecie.':
        'Nearest Guardian ruins and structures (Spansh). Double-click: copy system · select a row: site '
        'coordinates on the planet.',

    # --- strona Trasa / ogólne ---
    'Trasa handlowa': 'Trade route', 'Trasa z': 'Route from', 'TRASA AKTYWNA': 'ROUTE ACTIVE',
    'TRASA UKOŃCZONA': 'ROUTE COMPLETE', 'trasa ukończona': 'route complete', 'ukończona': 'complete',
    'BŁĄD TRASY': 'ROUTE ERROR', 'Błąd zapisu': 'Save error', 'Błąd sieci': 'Network error', 'Błąd': 'Error',
    'błąd': 'error', 'KOPIUJ CEL': 'COPY TARGET', 'KOPIUJ SYSTEM': 'COPY SYSTEM', 'POKAŻ RYNEK': 'SHOW MARKET',
    'PORÓWNAJ Z MOJĄ STACJĄ': 'COMPARE WITH MY STATION', 'SPRZEDAJ WSZYSTKO': 'SELL ALL',
    'SPRZEDAJ PO': 'SELL AT', 'SPRZEDAJ ŁADUNEK': 'SELL CARGO', 'BEZ ŁADUNKU': 'NO CARGO',
    'sprzedaj w okolicy': 'sell nearby', 'Kup tutaj': 'Buy here', 'Kup w': 'Buy at', 'Sprzedaj w': 'Sell at',
    'Sprzedaj': 'Sell', 'sprzedaj': 'sell', 'Kup': 'Buy', 'kup': 'buy', 'leć': 'fly',
    'Skopiowano': 'Copied', 'wklej w wyszukiwarce mapy galaktyki': 'paste into the galaxy map search',
    'OCZEKIWANIE NA DOKOWANIE — TRASA LICZY SIĘ PO DOKOWANIU': 'WAITING FOR DOCKING — ROUTE IS PLOTTED AFTER DOCKING',
    'OCZEKIWANIE NA DOKOWANIE': 'WAITING FOR DOCKING', 'SZYBKA TRASA · PEŁNA ZA CHWILĘ…': 'QUICK ROUTE · FULL ONE SOON…',
    'LICZĘ TRASĘ…': 'PLOTTING ROUTE…', 'ZAMIAST': 'INSTEAD', 'CENY NA ŻYWO': 'LIVE PRICES',
    'W SCHOWKU': 'IN CLIPBOARD', 'MASZ': 'HAVE', 'SKOKI': 'JUMPS', 'w locie': 'in flight',
    'SPRZEDAŻY': 'SALES', 'sprzedaży': 'sales', 'SESJA': 'SESSION',
    'Bieżąca stacja': 'Current station', 'Stacja docelowa': 'Destination station',
    'Trade advisor (bieżąca → docelowa)': 'Trade advisor (current → destination)',
    'pobieram oba rynki': 'loading both markets', 'pobieram rynek': 'loading market',
    'Kupisz tu (eksport)': 'Buy here (export)', 'Sprzedasz tu (import)': 'Sell here (import)',
    'Eksport (kupisz)': 'Export (you buy)', 'Import (sprzedasz)': 'Import (you sell)',
    'BRAK ZYSKOWNYCH TOWARÓW': 'NO PROFITABLE COMMODITIES', 'NA TEJ PARZE STACJI': 'BETWEEN THESE STATIONS',
    'NAJLEPIEJ': 'BEST', 'brak zysku': 'no profit', 'brak uwag': 'no remarks',
    'OKAZJE W OKOLICY': 'NEARBY TRADES', 'liczę okazje w': 'finding trades within',
    'brak zyskownych okazji w zasięgu': 'no profitable trades in range', 'liczę wokół': 'calculating around',
    'TWÓJ ŁADUNEK': 'YOUR CARGO', 'Twój ładunek — gdzie sprzedać': 'Your cargo — where to sell',
    'Twój ładunek': 'Your cargo', 'czy': 'or', 'razem': 'total', 'Razem': 'Total',
    'ładownia pusta': 'hold empty', 'ładownia': 'hold', 'domyślnie — czekam na Loadout': 'default — waiting for Loadout',
    'ceny zakupu na żywo z gry': 'live buy prices from the game', 'ceny na żywo z gry': 'live prices from the game',
    'nieznana (czekam na journal)': 'unknown (waiting for the journal)', 'nieznany': 'unknown',

    # --- kolumny tabel ---
    'Ocena': 'Rating', 'Towar': 'Commodity', 'Cena/t': 'Price/t', 'Cena': 'Price', 'Ceny': 'Prices',
    'CENY': 'PRICES', 'Zysk/t': 'Profit/t', 'Zysk na godzinę': 'Profit per hour', 'Zysk': 'Profit', 'zysk': 'profit',
    'Czas sesji': 'Session time', 'Czas': 'Time', 'Odl.': 'Dist.', 'ODL.': 'DIST.', 'Odległość': 'Distance',
    'Dystans': 'Distance', 'Od gwiazdy': 'From star', 'OD GWIAZDY': 'FROM STAR', 'Ilość': 'Amount',
    'Stacja': 'Station', 'Stacje w systemie': 'Stations in system', 'Typ': 'Type', 'TYP': 'TYPE',
    'Ekonomia': 'Economy', 'Rząd': 'Government', 'Frakcja': 'Faction', 'FRAKCJA': 'FACTION',
    'BEZPIECZ.': 'SECURITY', 'USŁUGI': 'SERVICES', 'DANE RYNKU': 'MARKET DATA', 'Pierścień': 'Ring',
    'Popyt': 'Demand', 'Zapas/popyt': 'Stock/demand', 'ZAPAS': 'STOCK', 'Zapas': 'Stock', 'vs śr.': 'vs avg.',
    'Skoki': 'Jumps', 'Skok (ly)': 'Jump (ly)', 'Pozostało (ly)': 'Remaining (ly)', 'Materiał': 'Material',
    'Potrzeba': 'Needed', 'Masz': 'Have', 'Gdzie zdobyć': 'Where to get', 'Podsumowanie sesji': 'Session summary',
    'Wydano na towar': 'Spent on goods', 'Najlepszy kurs': 'Best run', 'Twoje tempo lotu': 'Your flight pace',
    'Sprzedano': 'Sold', 'Wartość': 'Value', 'Transakcje': 'Trades', 'Brak transakcji w tej sesji': 'No trades this session',
    'Sprzedaż': 'Sell', 'Kupno': 'Buy', 'Co tu jest': 'What is here', 'Do zdobycia': 'Rewards', 'Projekty': 'Projects',
    'Na miejscu': 'On site', 'Planeta': 'Planet', 'Brakuje': 'Missing', 'Ile': 'Count', 'Dane': 'Data',
    'do:': 'to:', 'grawitacja': 'gravity', 'NIE DO LĄDOWANIA': 'NOT LANDABLE',

    # --- formularze ---
    'Szukaj': 'Search', 'Szukam': 'Searching', 'Odśwież': 'Refresh', 'Pokaż': 'Show', 'Oblicz': 'Calculate',
    'Zapisz': 'Save', 'Zapisano.': 'Saved.', 'Stacja:': 'Station:', 'Towar:': 'Commodity:', 'Rodzaj:': 'Kind:',
    'Minerał:': 'Mineral:', 'Zasięg (ly):': 'Range (ly):', 'Zasięg statku (ly):': 'Ship jump range (ly):',
    'Skąd:': 'From:', 'Dokąd:': 'To:', 'Cel:': 'Destination:', 'Od systemu:': 'From system:',
    'Grade od:': 'Grade from:', 'Rolle/grade:': 'Rolls/grade:', 'Gdzie kupić': 'Where to buy',
    'Gdzie sprzedać': 'Where to sell', 'Gdzie': 'Where', 'kupić': 'to buy', 'sprzedać': 'to sell',
    'najtaniej najpierw': 'cheapest first', 'najdrożej najpierw': 'highest first',
    'Wybierz blueprint i grade, kliknij Oblicz': 'Pick a blueprint and grade, click Calculate',
    'Wczytuję listę blueprintów...': 'Loading the blueprint list...', 'blueprintów': 'blueprints',
    'masz wszystko': 'you have everything', 'brakuje': 'missing',
    'Stan materiałów z journala': 'Materials from the journal', 'pozycji': 'items',
    'Stan materiałów: brak (event Materials pojawia się w journalu przy starcie gry).':
        'Materials: none yet (the Materials event appears in the journal when the game starts).',
    'Nie udało się pobrać danych blueprintów/materiałów (brak sieci i brak cache)':
        'Could not load blueprint/material data (no network and no cache)',
    'Błąd: "grade od" nie może być większy niż "do", rolle >= 1': 'Error: "grade from" cannot exceed "to", rolls >= 1',
    'Błąd: grade i rolle muszą być liczbami': 'Error: grade and rolls must be numbers',

    # --- strona Ustawienia ---
    'Cel journey (system):': 'Journey destination (system):', 'Materiały (kind):': 'Materials (kind):',
    'Mining (minerał):': 'Mining (mineral):', 'Klasa okna gry:': 'Game window class:',
    'Pasek tylko gdy gra ma fokus': 'Bar only when game focused',
    'Po zmianie trasy kopiuj do schowka:': 'On route change copy to clipboard:',
    'nazwę stacji': 'station name', 'nazwę systemu': 'system name', 'stację i system': 'station and system',
    'Minimalny pad:': 'Minimum pad:', 'Automatycznie (ze statku)': 'Automatic (from ship)', 'Tylko pad L': 'L pad only',
    'Wszystkie pady': 'All pads', 'Maks. od gwiazdy (ls, 0 = bez limitu):': 'Max. from star (ls, 0 = no limit):',
    'Typ rynku:': 'Market type:', 'Wszystkie': 'All', 'Tylko kosmiczne': 'Space only',
    'Tylko planetarne': 'Planetary only', 'Min. zysk (cr/t):': 'Min. profit (cr/t):',
    'Maks. wiek cen (dni):': 'Max. price age (days):', 'Przezroczystość paska:': 'Bar opacity:',
    'Czcionka paska (skala):': 'Bar font (scale):', 'Czcionka panelu (skala):': 'Panel font (scale):',
    'Ocena okazji:': 'Trade rating:', 'Ikonki (= ≈ ▲ ▼)': 'Icons (= ≈ ▲ ▼)', 'Opis (OPTIMAL, SAFE…)': 'Labels (OPTIMAL, SAFE…)',
    'Profil ryzyka:': 'Risk profile:', 'Unikanie low-sec:': 'Avoid low-sec:', 'Omijaj Low / Anarchy': 'Skip Low / Anarchy',
    'Maks. hopów trasy:': 'Max. route hops:', 'Ceny na żywo (EDDN):': 'Live prices (EDDN):',
    'Włączone (po restarcie)': 'Enabled (after restart)', 'wyłączone': 'disabled',
    'niedostępne — zainstaluj pyzmq': 'unavailable — install pyzmq', 'baza': 'database', 'rynków': 'markets',
    'w tej sesji': 'this session', 'Skróty (klawiatura numeryczna):': 'Hotkeys (numeric keypad):',
    'Modyfikator:': 'Modifier:', 'brak': 'none', 'Górny pasek': 'Top bar', 'Dolny pasek': 'Bottom bar',
    'Kopiuj cel (2× stacja/system)': 'Copy target (2× station/system)',
    'Pozycja klawisza = miejsce na ekranie. Skróty działają, gdy fokus ma okno aplikacji;':
        'Key position = place on screen. Hotkeys work while the app window has focus;',
    'w grze przez skróty KDE': 'in game via KDE shortcuts', 'lista': 'list', 'cel': 'target',
    'Błąd: zasięg musi być liczbą': 'Error: range must be a number',
    'Błąd: odległość od gwiazdy musi być liczbą ≥ 0.': 'Error: distance from star must be a number ≥ 0.',
    'Błąd: min. zysk ≥ 0, wiek cen ≥ 1 dzień (liczby).': 'Error: min. profit ≥ 0, price age ≥ 1 day (numbers).',
    'Błąd: maks. hopów 1–10.': 'Error: max. hops 1–10.',
    'Największy zysk': 'Biggest profit', 'Najszybszy zysk (cr/h)': 'Fastest profit (cr/h)',
    'Najkrótsza droga': 'Shortest trip',
    'AUTO — profil dobierany do każdej okazji': 'AUTO — profile chosen per opportunity',
    'SAFE — pewne ceny, mniejsze ryzyko': 'SAFE — reliable prices, lower risk',
    'OPTIMAL — drogie towary, ale świeże ceny': 'OPTIMAL — valuable goods, but fresh prices',
    'RISKY — drogie towary, ryzyko za dużą nagrodę': 'RISKY — valuable goods, risk for a big reward',
    'POZYCJA': 'POSITION', 'STATEK': 'SHIP', 'ŁADUNEK': 'CARGO', 'FILTR': 'FILTER', 'PROFIL': 'PROFILE',
    'każdy pad': 'any pad', 'bez limitu ls': 'no ls limit', 'dane': 'data',

    # --- System / Materiały / Mining / Towary / Journey ---
    'szukam stacji': 'searching stations', 'szukam wokół': 'searching around', 'szukam': 'searching',
    'wokół': 'around', 'brak danych o stacjach': 'no station data', 'najbliżej najpierw': 'nearest first',
    'Handlarze materiałów': 'Material traders', 'Hotspoty (gdzie kopać)': 'Hotspots (where to mine)',
    'Kupcy (gdzie sprzedać)': 'Buyers (where to sell)', 'hotspoty': 'hotspots', 'kupcy': 'buyers',
    'trader Raw / planety (zakładka Materiały)': 'Raw trader / planets (Materials page)',
    'trader Manufactured / sygnały, wraki': 'Manufactured trader / signals, wrecks',
    'trader Encoded / skanowanie': 'Encoded trader / scanning',
    'albo nieznana nazwa': 'or unknown name', 'zasięg': 'range', 'liczę trasę, do 2 min': 'plotting route, up to 2 min',
    'skoków': 'jumps', 'skokow': 'jumps', 'stacji': 'stations', 'stacje': 'stations', 'stacja': 'station',
    'towarów': 'commodities', 'hopów': 'hops', 'hopy': 'hops',

    # --- Guardian ---
    'Ruiny i struktury Guardian': 'Guardian ruins and structures', 'Wszystko': 'Everything',
    'Ruiny (artefakty)': 'Ruins (artefacts)', 'Struktury (blueprinty)': 'Structures (blueprints)',
    'Blueprint broni': 'Weapon blueprint', 'Blueprint modułów': 'Module blueprint', 'Blueprint myśliwców': 'Fighter blueprint',
    'blueprint broni': 'weapon blueprint', 'blueprint modułów': 'module blueprint', 'blueprint myśliwców': 'fighter blueprint',
    'Ruiny': 'Ruins', 'Struktura': 'Structure', 'typ': 'type', 'wieża reliktu': 'relic tower',
    'nieznane — brak wpisów Codexu': 'unknown — no Codex entries', 'sygnał Guardian': 'Guardian signal',
    'artefakty + dane': 'artefacts + data', 'części Guardian (typ struktury ?)': 'Guardian parts (structure type ?)',
    'artefakty': 'artefacts', 'dane obelisków': 'obelisk data',
    'Brak wpisów Codexu — miejsce znajdziesz skanerem DSS (sygnał Guardian).':
        'No Codex entries — find the site with the DSS scanner (Guardian signal).',

    # --- dolny pasek / karta stacji ---
    'STACJA DOCELOWA': 'DESTINATION STATION', 'POBIERAM DANE STACJI…': 'LOADING STATION DATA…',
    'BRAK DANYCH O STACJI': 'NO STATION DATA', 'BRAK CELU — CZEKAM NA TRASĘ': 'NO TARGET — WAITING FOR A ROUTE',
    '⚠ LOCKDOWN — USŁUGI STACJI MOGĄ BYĆ ZAMKNIĘTE': '⚠ LOCKDOWN — STATION SERVICES MAY BE CLOSED',
    'temu': 'ago', 'paliwo': 'fuel', 'naprawa': 'repair', 'amunicja': 'rearm', 'stocznia': 'shipyard',
    'handlarz mat.': 'mat. trader', 'broker tech.': 'tech broker', 'czarny rynek': 'black market',

    # --- weryfikacja cen na żywo ---
    'CENY KUPNA POTWIERDZONE': 'BUY PRICES CONFIRMED', 'CENA SPRZEDAŻY POTWIERDZONA': 'SELL PRICE CONFIRMED',
    'TOWARÓW Z TRASY JUŻ NIE MA': 'ROUTE COMMODITIES ARE GONE', 'TOWARU JUŻ NIE MA': 'SOLD OUT',
    'NIEOPŁACALNY': 'UNPROFITABLE', 'KUPNO': 'BUY', 'TU JUŻ NIE SKUPUJĄ': 'NO LONGER BOUGHT HERE:',
    'ZOBACZ OKOLICĘ': 'SEE NEARBY', 'SPRZEDAŻ': 'SELL', 'ŁADUNEK ZMIENIONY WG RYNKU — PATRZ CEL':
        'CARGO CHANGED BY MARKET — SEE TARGET',

    # --- tempo lotu ---
    'szacunek ogólny': 'generic estimate', 'szacunku': 'of estimate', 'kalibracja': 'calibration',
    'kursów': 'runs', 'kursy': 'runs', 'kurs': 'run', 'za mało danych': 'not enough data',

    # --- błędy z trade.py (pokazywane na pasku i w panelu) ---
    'Nieoczekiwana odpowiedź Ardent': 'Unexpected Ardent response',
    'Na tym rynku nie ma już opłacalnych towarów z trasy (dane Spansh nieaktualne)':
        'This market no longer has profitable route commodities (Spansh data out of date)',
    'Spansh zwrócił pusty wynik (brak trasy?)': 'Spansh returned an empty result (no route?)',
    'Spansh zwrócił pusty wynik (brak opłacalnych tras?)': 'Spansh returned an empty result (no profitable routes?)',
    'Spansh: najlepsza trasa ma zysk <= 0': 'Spansh: the best route has profit <= 0',
    'Trade Dangerous zwrócił pusty wynik (brak opłacalnych tras?)':
        'Trade Dangerous returned an empty result (no profitable routes?)',
    'Trade Dangerous przekroczył limit 120s': 'Trade Dangerous exceeded the 120 s limit',
    'nie znaleziony': 'not found', 'Nie znaleziono': 'Not found', 'Wyjątek': 'Exception',
    'Brak job_id w odpowiedzi': 'No job_id in response', 'Docelowy system': 'Destination system',
    'nie znajduje się na końcu trasy': 'is not at the end of the route',
}

# Zmiana szyku zdania — wzorce stosowane przed frazami
PATTERNS: list[tuple[str, str]] = [
    (r"Brak danych rynku dla stacji '([^']*)' w ", r"No market data for station '\1' in "),
    (r'Brak traderów (\S+) w zasięgu (\d+) ly od ', r'No \1 traders within \2 ly of '),
    (r'Brak stacji, gdzie kupić', 'No stations to buy'),
    (r'Brak stacji, gdzie sprzedać', 'No stations to sell'),
    (r'Trader (\S+) wokół ', r'\1 traders around '),
    (r'brakuje (\d+) z (\d+)', r'missing \1 of \2'),
    (r'([\d,]+) t za ([\d,]+) cr', r'\1 t for \2 cr'),
    (r'(\d+) planet\b', r'\1 planets'),
    (r'\b1 stacja\b', '1 station'),
    (r'\b1 kurs\b', '1 run'),
    (r'(\d+)\s*hop\b', r'\1 hop'),
]

_lang = 'pl'
_phrase_re: Optional[re.Pattern] = None
_lookup: dict[str, str] = {}
_reverse: dict[str, str] = {}
_patterns: list[tuple[re.Pattern, str]] = []
_installed = False


def detect_language(setting: Any = 'auto', env: Optional[dict] = None) -> str:
    """'pl' / 'en' z ustawienia; 'auto' → locale systemu (pl_* → polski, inaczej angielski)."""
    setting = str(setting or 'auto').lower()
    if setting in ('pl', 'en'):
        return setting
    env = os.environ if env is None else env
    for key in ('LC_ALL', 'LC_MESSAGES', 'LANG', 'LANGUAGE'):
        value = env.get(key)
        if value:
            return 'pl' if value.lower().startswith('pl') else 'en'
    try:
        loc = locale.getlocale()[0] or ''
    except ValueError:
        loc = ''
    return 'pl' if loc.lower().startswith('pl') else 'en'


def set_language(lang: str) -> None:
    global _lang
    _lang = 'en' if lang == 'en' else 'pl'
    _build()


def language() -> str:
    return _lang


def _build() -> None:
    global _phrase_re
    if _phrase_re is not None:
        return
    _lookup.update({k.casefold(): v for k, v in EN.items()})
    _reverse.update({v.casefold(): k for k, v in EN.items()})
    keys = sorted(EN, key=len, reverse=True)
    _phrase_re = re.compile(r'(?<!\w)(' + '|'.join(re.escape(k) for k in keys) + r')(?!\w)', re.IGNORECASE)
    _patterns.extend((re.compile(p, re.IGNORECASE), r) for p, r in PATTERNS)


def _match_case(source: str, text: str) -> str:
    if source.upper() == source and source.lower() != source:
        return text.upper()
    if source[:1].isupper() and text[:1].islower():
        return text[:1].upper() + text[1:]
    return text


def tr(text: Any) -> Any:
    """Tekst w bieżącym języku. Nie-teksty i teksty bez polskich fraz wracają bez zmian."""
    if _lang == 'pl' or not isinstance(text, str) or not text.strip():
        return text
    _build()
    stripped = text.strip()
    whole = EN.get(stripped) or _lookup.get(stripped.casefold())
    if whole is not None:
        return text.replace(stripped, _match_case(stripped, whole))
    for pattern, replacement in _patterns:
        text = pattern.sub(lambda m, r=replacement: _match_case(m.group(0), m.expand(r)), text)
    return _phrase_re.sub(lambda m: _match_case(m.group(0), _lookup[m.group(0).casefold()]), text)


def source(text: str) -> str:
    """Odwrotność tr() dla całych tekstów (np. tytuł strony z Tk → polski klucz w configu)."""
    if _lang == 'pl' or not isinstance(text, str):
        return text
    _build()
    return _reverse.get(text.strip().casefold(), text)


def _tr_options(options: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(options, dict) or _lang == 'pl':
        return options
    changed = None
    for key in keys:
        for name in (key, '-' + key):
            if name in options:
                value = options[name]
                if isinstance(value, str):
                    new = tr(value)
                elif isinstance(value, (list, tuple)) and key == 'values':
                    new = type(value)(tr(v) for v in value)
                else:
                    continue
                if new is not value:
                    changed = changed or dict(options)
                    changed[name] = new
    return changed or options


def install() -> None:
    """Przepuść teksty widżetów Tk przez tr(): text= (wszystkie widżety), nagłówki i komórki tabel, zakładki."""
    global _installed
    if _installed:
        return
    import tkinter
    from tkinter import ttk

    original_options = tkinter.Misc._options

    def _options(self, cnf, kw=None):
        return original_options(self, _tr_options(cnf, ('text',)), _tr_options(kw, ('text',)))

    original_format = ttk._format_optdict

    def _format_optdict(optdict, script=False, ignore=None):
        return original_format(_tr_options(optdict, ('text', 'values')), script, ignore)

    tkinter.Misc._options = _options
    ttk._format_optdict = _format_optdict
    _installed = True
