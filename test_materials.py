"""Testy trackera materiałów — bez sieci (dane wstrzyknięte, próbka eventu z prawdziwego journala)."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from edtrade import materials as M

SAMPLES = Path(__file__).parent / "test_data" / "journal_samples.jsonl"

MATERIAL_CSV = """id,symbol,rarity,type,category,name
1,Phosphorus,1,Raw,2,Phosphorus
2,DataminedWake,5,Encoded,Wake Scans,Datamined Wake Exceptions
3,FedCoreComposites,5,Manufactured,Composite,Core Dynamics Composites
4,ShieldDensityReports,3,Encoded,Shield Data,Untypical Shield Scans
"""

BLUEPRINTS_JSON = json.dumps({
    "FSD_LongRange": {
        "fdname": "FSD_LongRange", "name": "Increased range", "modulename": ["Frame shift drive", "FSD"],
        "grades": {
            "1": {"components": {"Phosphorus": 1}},
            "2": {"components": {"Phosphorus": 1, "Datamined Wake Exceptions": 1}},
            "3": {"components": {"Untypical Shield Scans": 2, "Mystery Part": 1}},
        },
    }
})


def sample_event(name: str) -> dict:
    for line in SAMPLES.read_text(encoding="utf-8").splitlines():
        ev = json.loads(line)
        if ev["event"] == name:
            return ev
    raise KeyError(name)


class TestParsing(unittest.TestCase):
    def test_material_table_maps_symbol_not_display_name(self):
        table = M.parse_material_table(MATERIAL_CSV)
        self.assertEqual(table["fedcorecomposites"].name, "Core Dynamics Composites")
        self.assertEqual(table["shielddensityreports"].name, "Untypical Shield Scans")  # spacja na końcu w CSV
        self.assertEqual(table["dataminedwake"].cap, 100)
        self.assertEqual(table["phosphorus"].cap, 300)

    def test_real_materials_event(self):
        inv = M.parse_materials_event(sample_event("Materials"))
        self.assertEqual(len(inv), 115)
        self.assertEqual(inv["carbon"], 300)
        self.assertEqual(inv["fedcorecomposites"], 12)
        self.assertEqual(inv["dataminedwake"], 1)

    def test_blueprints(self):
        bp = M.parse_blueprints(BLUEPRINTS_JSON)["FSD_LongRange"]
        self.assertEqual(bp.label, "Frame shift drive: Increased range")
        self.assertEqual(M.requirements(bp, 1, 2, 3), {"Phosphorus": 6, "Datamined Wake Exceptions": 3})


class TestMissing(unittest.TestCase):
    def test_missing_sorted_and_unknown_material(self):
        table = M.parse_material_table(MATERIAL_CSV)
        bp = M.parse_blueprints(BLUEPRINTS_JSON)["FSD_LongRange"]
        inv = M.parse_materials_event(sample_event("Materials"))
        needs = {n.name: n for n in M.missing_for(bp, 1, 3, 2, inv, table)}
        self.assertEqual(needs["Datamined Wake Exceptions"].missing, 1)   # 2 potrzeba, 1 masz
        self.assertEqual(needs["Phosphorus"].missing, 0)
        self.assertEqual(needs["Untypical Shield Scans"].have, 181)
        self.assertEqual(needs["Mystery Part"].type, "?")                  # brak w tabeli → nie wywala
        order = [n.name for n in M.missing_for(bp, 1, 3, 2, inv, table)]
        self.assertEqual(order[0], "Mystery Part")                         # największy brak pierwszy


class TestCache(unittest.TestCase):
    def test_network_error_falls_back_to_stale_cache(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "material.csv"
            path.write_text(MATERIAL_CSV, encoding="utf-8")
            old = time.time() - M.CACHE_MAX_AGE_S - 10
            os.utime(path, (old, old))
            with mock.patch.object(M.requests, "get", side_effect=OSError("offline")):
                table = M.load_material_table(Path(d))
            self.assertIn("dataminedwake", table)

    def test_no_network_no_cache(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(M.requests, "get", side_effect=OSError("offline")):
                self.assertEqual(M.load_blueprints(Path(d)), {})


if __name__ == "__main__":
    unittest.main()
