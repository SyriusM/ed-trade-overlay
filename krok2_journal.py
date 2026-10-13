#!/usr/bin/env python3
"""Krok 2: Odczyt pozycji z journala Elite Dangerous.

Znajduje najnowszy Journal.*.log po mtime,
wypisuje ostatnie eventy Docked i Loadout.
"""

import json
import sys
from pathlib import Path

JOURNAL_DIR = Path.home() / ".local" / "share" / "Steam" / "steamapps" / "compatdata" / "359320" / "pfx" / "drive_c" / "users" / "steamuser" / "Saved Games" / "Frontier Developments" / "Elite Dangerous"


def find_latest_journal() -> Path | None:
    """Najnowszy plik journala wg mtime — NIE po nazwie."""
    journals = sorted(
        JOURNAL_DIR.glob("Journal.*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return journals[0] if journals else None


def read_docked_events(journal: Path, count: int = 3) -> list[dict]:
    """Odczytaj ostatnie eventy Docked z pliku."""
    events: list[dict] = []
    with open(journal, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("event") == "Docked":
                    events.append(data)
            except json.JSONDecodeError:
                continue
    return events[-count:] if events else []


def read_loadout(journal: Path) -> dict | None:
    """Odczytaj ostatni event Loadout z pliku."""
    with open(journal, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("event") == "Loadout":
                    return data
            except json.JSONDecodeError:
                continue
    return None


def main():
    print(f"Journal dir: {JOURNAL_DIR}")
    print(f"Dir exists: {JOURNAL_DIR.exists()}\n")

    journal = find_latest_journal()
    if not journal:
        print("BRAK pliku journala!")
        sys.exit(1)

    print(f"Najnowszy journal: {journal.name}")
    print(f"Size: {journal.stat().st_size:,} bytes")
    print(f"Modified: {journal.stat().st_mtime}\n")

    events = read_docked_events(journal, count=3)
    if not events:
        print("BRAK eventów Docked w pliku.")
        sys.exit(1)

    print(f"Ostatnie Docked ({len(events)}):\n")
    for ev in events:
        system = ev.get("StarSystem", "?")
        station = ev.get("StationName", "?")
        stype = ev.get("StationType", "?")
        print(f"  System: {system}")
        print(f"  Station: {station} ({stype})")
        print(f"  MarketID: {ev.get('MarketID', '?')}")
        print()

    loadout = read_loadout(journal)
    if loadout:
        print(f"Loadout:\n")
        print(f"  Ship: {loadout.get('Ship', '?')}")
        print(f"  ShipID: {loadout.get('ShipID', '?')}")
        print(f"  CargoCapacity: {loadout.get('CargoCapacity', '?')}")
        print(f"  UsedBays: {loadout.get('UsedBays', '?')}")
        for slot in loadout.get("Slots", []):
            print(f"  Slot: {slot}")
    else:
        print("BRAK eventu Loadout w pliku.")


if __name__ == "__main__":
    main()
