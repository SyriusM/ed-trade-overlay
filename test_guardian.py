"""Strona Guardian — parser na prawdziwych rekordach Spansh (test_data/spansh_guardian_bodies.json)."""

import json
from pathlib import Path

from edtrade.guardian import RUINS, STRUCTURE, parse_body

RECORDS = json.loads((Path(__file__).parent / "test_data" / "spansh_guardian_bodies.json").read_text())["results"]


def test_ruins_body():
    body = parse_body(RECORDS[0])
    assert (body.system, body.body) == ("Synuefe XR-H d11-102", "Synuefe XR-H d11-102 1 b")
    assert body.kinds == {RUINS}
    assert body.features["wieża reliktu"] >= 1
    assert "Casket" in body.rewards and "blueprint" not in body.rewards
    assert body.matches(RUINS) and not body.matches(STRUCTURE) and not body.matches("weapon")
    assert "Codex" not in body.features_text


def test_structure_body_has_blueprint_kind():
    body = parse_body(RECORDS[1])
    assert STRUCTURE in body.kinds
    assert body.blueprints
    assert body.matches(STRUCTURE) and body.matches(next(iter(body.blueprints)))
    assert "Power Cell" in body.rewards and "blueprint" in body.rewards
    assert body.summary.startswith("Struktura")


def test_signal_without_codex_entries():
    body = parse_body(RECORDS[2])
    assert body.sites == [] and body.signals >= 1
    assert body.summary.startswith("sygnał Guardian")
    assert body.matches("all") and not body.matches(RUINS)


def test_duplicate_points_collapsed():
    record = {"system_name": "X", "name": "X 1", "landmarks": [
        {"type": "Guardian Ruin", "subtype": "Unknown", "latitude": 1.0, "longitude": 2.0},
        {"type": "Guardian Ruin", "subtype": "Unknown", "latitude": 1.001, "longitude": 2.001},
        {"type": "Guardian Structure", "subtype": "Lacrosse", "latitude": -5.0, "longitude": 7.0}]}
    body = parse_body(record)
    assert len(body.sites) == 2
    assert body.summary == "Ruiny · Struktura Lacrosse"
    assert body.rewards_short == "artefakty + dane · blueprint broni"
    assert body.matches("weapon")
