"""Podpowiedzi w polach: dopasowanie nazw, katalog towarów z FDevIDs, stacje systemu."""

import os
import unittest

from edtrade.suggest import StationNames, filter_names, merge_remote, parse_catalog, recent_first

CSV = ("id,symbol,category,name\n1,Platinum,Metals,Platinum\n2,LowTemperatureDiamond,Minerals,Low Temperature Diamonds\n"
       "3,Tritium,Chemicals,Tritium\n4,Gold,Metals,Gold\n5,Painite,Minerals,Painite\n6,Biowaste,Waste,Biowaste\n"
       "7,Drones,NonMarketable,Limpet\n")


def test_prefix_then_word_then_fragment():
    names = ["Low Temperature Diamonds", "Diamond", "Gold", "Indite", "Indium"]
    assert filter_names(names, "di") == ["Diamond", "Low Temperature Diamonds", "Indite", "Indium"]
    assert filter_names(names, "ind") == ["Indite", "Indium"]
    assert filter_names(names, "TEMP") == ["Low Temperature Diamonds"]
    assert filter_names(names, "ol") == ["Gold"]                # fragment w środku
    assert filter_names(names, "") == sorted(names, key=str.lower)
    assert len(filter_names([f"S{i}" for i in range(50)], "s", limit=5)) == 5


def test_catalog_minerals_and_commodities():
    commodities, minerals = parse_catalog(CSV)
    assert "Biowaste" in commodities and "Limpet" not in commodities
    assert minerals == ["Gold", "Low Temperature Diamonds", "Painite", "Platinum", "Tritium"]


def test_station_names_cached_per_system():
    calls = []

    class S:
        def __init__(self, name):
            self.name = name

    def fetch(system):
        calls.append(system)
        return [S("Abraham Lincoln"), S("Daedalus"), S("Galileo")]

    stations = StationNames(fetch)
    assert stations("Sol", "da") == ["Daedalus"]
    assert stations("sol", "") == ["Abraham Lincoln", "Daedalus", "Galileo"]
    assert calls == ["Sol"]
    assert stations("", "da") == []


def test_remote_results_kept_after_text_matches():
    assert merge_remote(["Synuefe WC-A a96-12", "Synuefe EN-H d11-5", "Synuefe WC-A a96-12"], "synuefe e") == \
        ["Synuefe EN-H d11-5", "Synuefe WC-A a96-12"]


def test_recent_first():
    assert recent_first(["Synuefe XR-H d11-102"], ["Synuefai AA-A a1", "Synuefe XR-H d11-102"], "synue") == \
        ["Synuefe XR-H d11-102", "Synuefai AA-A a1"]


@unittest.skipUnless(os.environ.get("DISPLAY"), "potrzebny X (Xvfb)")
class SuggestEntryTest(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from edtrade import tce_theme as tce
        self.root = tk.Tk()
        self.var = tk.StringVar()
        self.selected = []
        self.entry = tce.SuggestEntry(self.root, lambda t: filter_names(["Gold", "Gallite", "Silver"], t),
                                      self.var, tce.Fonts(self.root), on_select=self.selected.append)
        self.entry.pack()
        self.root.update()
        self.entry.focus_force()
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def type(self, text):
        self.var.set(text)
        self.entry.refresh()
        self.root.update()

    def test_typing_shows_list_and_enter_accepts(self):
        self.type("g")
        self.assertTrue(self.entry.visible())
        self.assertEqual(self.entry.listbox.get(0, "end"), ("Gallite", "Gold"))
        self.entry._move(1)
        self.entry._move(1)
        self.entry._on_return(None)
        self.assertEqual(self.var.get(), "Gold")
        self.assertEqual(self.selected, ["Gold"])
        self.assertFalse(self.entry.visible())

    def test_exact_match_hides_and_escape(self):
        self.type("silver")
        self.assertFalse(self.entry.visible())
        self.type("s")
        self.assertTrue(self.entry.visible())
        self.entry.hide()
        self.assertFalse(self.entry.visible())

    def test_down_on_empty_shows_all(self):
        self.entry._move(1)
        self.root.update()
        self.assertEqual(self.entry.listbox.size(), 3)
