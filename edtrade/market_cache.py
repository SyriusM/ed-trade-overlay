"""Market cache — lokalna baza cen zasilana z Market.json.

SQLite cache do przechowywania cen rynkowych z eventów Market.
Cache działa jako fallback dla Spansh API (offline, szybkie powtórne zapytania).
"""

import json
import sqlite3
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Ścieżka do bazy danych
_MARKET_CACHE_DB = Path("~/.local/share/ed-trade-overlay/market_cache.db").expanduser()


def init_market_cache(db_path: Path) -> sqlite3.Connection:
    """Inicjalizacja bazy, tworzenie tabeli MarketHistory.

    Args:
        db_path: Ścieżka do pliku SQLite.

    Returns:
        Połączona baza danych.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Tworzone w wątku głównym, używane wyłącznie przez wątek watchera (event Market) — jeden użytkownik naraz
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cursor = conn.cursor()

    # Tabela MarketHistory
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS MarketHistory (
            market_id BIGINT,
            item_id INT,
            supply_price INT,
            demand_price INT,
            supply_units INT,
            demand_units INT,
            timestamp DATETIME,
            market_updated_at DATETIME,
            star_system TEXT,
            station_name TEXT,
            station_id BIGINT,
            PRIMARY KEY (market_id, item_id)
        )
    """)

    # Indeks dla szybszego wyszukiwania
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_market_history ON MarketHistory(market_id, item_id)
    """)

    conn.commit()
    logger.info("Market cache zainicjowany: %s", db_path)
    return conn


def record_market_prices(
    conn: sqlite3.Connection,
    market_id: int,
    prices: list[dict],
    timestamp: float,
    market_updated_at: Optional[str] = None,
    star_system: Optional[str] = None,
    station_name: Optional[str] = None,
) -> None:
    """Zapisz ceny z Market.json do bazy.

    Args:
        conn: Połączona baza.
        market_id: ID rynku.
        prices: Lista cen {item_id, supply_price, demand_price, supply_units, demand_units}.
        timestamp: Czas odczytu (float, unix).
        market_updated_at: Czas aktualizacji rynku (ISO string, opcjonalne).
        star_system: Nazwa systemu gwiazdowego (opcjonalne).
        station_name: Nazwa stacji (opcjonalne).
    """
    cursor = conn.cursor()

    # Jeśli market_updated_at nie podane, użyj czasu z timestamp
    if market_updated_at is None:
        market_updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.localtime(timestamp))

    for p in prices:
        cursor.execute("""
            INSERT OR REPLACE INTO MarketHistory
            (market_id, item_id, supply_price, demand_price, supply_units, demand_units,
             timestamp, market_updated_at, star_system, station_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            market_id,
            p.get("item_id"),
            p.get("supply_price"),
            p.get("demand_price"),
            p.get("supply_units"),
            p.get("demand_units"),
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.localtime(timestamp)),
            market_updated_at,
            star_system,
            station_name,
        ))

    conn.commit()
    logger.debug("Zapisano %d pozycji do MarketHistory (market_id=%d)", len(prices), market_id)


def get_cached_prices(
    conn: sqlite3.Connection,
    market_id: int,
    max_age_hours: float = 24.0,
) -> list[dict] | None:
    """Zwóć ceny z cache jeśli świeże (<= max_age_hours), inaczej None.

    Zwraca tylko najnowszy wpis dla każdego item_id (MAX(timestamp)).

    Args:
        conn: Połączona baza.
        market_id: ID rynku.
        max_age_hours: Maksymalny wiek danych w godzinach (domyślnie 24h).

    Returns:
        Lista cen lub None jeśli dane starsze niż max_age_hours.
    """
    cursor = conn.cursor()

    # Oblicz czas prógu
    cutoff = time.time() - (max_age_hours * 3600)
    cutoff_dt = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.localtime(cutoff))

    # Znajdź najnowszy market_updated_at dla market_id
    cursor.execute("""
        SELECT MAX(market_updated_at) FROM MarketHistory WHERE market_id = ?
    """, (market_id,))
    result = cursor.fetchone()[0]

    if result is None:
        logger.debug("Brak danych w cache dla market_id=%d", market_id)
        return None

    # Sprawdź czy dane są świeże
    if result < cutoff_dt:
        logger.debug("Dane cache dla market_id=%d starsze niż %dh", market_id, max_age_hours)
        return None

    # Zwróć najnowszy wpis dla każdego item_id (MAX(timestamp) GROUP BY item_id)
    cursor.execute("""
        SELECT item_id, supply_price, demand_price, supply_units, demand_units
        FROM (
            SELECT item_id, supply_price, demand_price, supply_units, demand_units,
                   ROW_NUMBER() OVER (PARTITION BY item_id ORDER BY timestamp DESC) as rn
            FROM MarketHistory
            WHERE market_id = ?
        )
        WHERE rn = 1
    """, (market_id,))

    rows = cursor.fetchall()
    prices = [
        {
            "item_id": row[0],
            "supply_price": row[1],
            "demand_price": row[2],
            "supply_units": row[3],
            "demand_units": row[4],
        }
        for row in rows
    ]

    logger.debug("Cache hit dla market_id=%d: %d pozycji", market_id, len(prices))
    return prices


def should_use_cache(market_id: int, max_age_hours: float = 24.0, db_path: Optional[Path] = None) -> bool:
    """Sprawdź czy cache ma świeże dane (<= 24h).

    Args:
        market_id: ID rynku.
        max_age_hours: Maksymalny wiek danych w godzinach (domyślnie 24h).
        db_path: Ścieżka do bazy (domyślnie _MARKET_CACHE_DB).

    Returns:
        True jeśli cache ma świeże dane, False inaczej.
    """
    path = db_path if db_path is not None else _MARKET_CACHE_DB
    conn = init_market_cache(path)
    try:
        prices = get_cached_prices(conn, market_id, max_age_hours)
        return prices is not None
    finally:
        conn.close()


def _load_market_json(market_file: Path) -> Optional[dict]:
    """Załaduj Market.json (analogicznie do _load_cargo_json).

    Plik może nie istnieć lub być niekompletny — bezpieczne pomijamy.

    Args:
        market_file: Ścieżka do Market.json.

    Returns:
        Zładowane dane lub None.
    """
    if not market_file.is_file():
        logger.debug("Market.json nie istnieje: %s", market_file)
        return None

    try:
        with open(market_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.debug("Market.json odczytany: market_id=%d, items=%d",
                    data.get("MarketID"), len(data.get("Items", [])))
        return data
    except (json.JSONDecodeError, OSError, IOError) as e:
        logger.warning("Błąd odczytu Market.json: %s", e)
        return None


def update_market_cache_from_journal(
    conn: sqlite3.Connection,
    journal_dir: Path,
    market_id: int,
    timestamp: float,
    market_updated_at: Optional[str] = None,
    star_system: Optional[str] = None,
    station_name: Optional[str] = None,
) -> None:
    """Przejdź Market.json w journal_dir, zapisz ceny do cache.

    Market event z journala sygnalizuje tylko, że Market.json został zapisany.
    Trzeba go wczytać i pobrać ceny z pola 'Items'.

    Args:
        journal_dir: Katalog z journalami (Market.json musi być w tym samym miejscu).
        market_id: ID rynku do zapisania.
        timestamp: Czas odczytu (float, unix).
        market_updated_at: Czas aktualizacji rynku (ISO string, opcjonalne).
        star_system: Nazwa systemu gwiazdowego (opcjonalne).
        station_name: Nazwa stacji (opcjonalne).
    """
    market_file = journal_dir / "Market.json"
    data = _load_market_json(market_file)

    if data is None:
        logger.debug("Market.json nie dostępny dla market_id=%d", market_id)
        return

    # MarketID z pliku Market.json
    file_market_id = data.get("MarketID")
    if file_market_id != market_id:
        logger.debug("MarketID w pliku (%d) różni się od oczekiwanego (%d)",
                    file_market_id, market_id)
        return

    items = data.get("Items", [])
    prices = [
        {
            "item_id": item.get("id"),
            "supply_price": item.get("BuyPrice"),
            "demand_price": item.get("SellPrice"),
            "supply_units": item.get("Stock"),
            "demand_units": item.get("Demand"),
        }
        for item in items
    ]

    record_market_prices(
        conn,
        market_id,
        prices,
        timestamp,
        market_updated_at,
        star_system,
        station_name,
    )

    logger.info("Zapisano %d cen do MarketHistory (market_id=%d)", len(prices), market_id)
