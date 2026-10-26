"""Dolny pasek: teksty stron i rotacja cel → okolica → ładunek."""

import os
import unittest

from edtrade.bottom_bar import cargo_lines, nearby_lines


def test_nearby_lines_top_three():
    items = [("= OPTIMAL", f"Gold{i}", "Abe", "Sol", 1000 * i, 2.5e6) for i in range(1, 5)]
    line1, line2 = nearby_lines(items)
    assert "Gold1" in line1 and "Gold2" in line1 and "Gold3" in line2
    assert "Gold4" not in line1 + line2
    assert "+1,000/T · 2.5M/H" in line1


def test_cargo_lines_split():
    line1, line2 = cargo_lines([("■ HOLD", "Gold", 10, ""), ("▲ SELL THERE", "Silver", 5, "Abe"),
                                ("= SELL HERE", "Tea", 3, "tutaj")])
    assert line1 == "■ HOLD Gold ×10     ▲ SELL THERE Silver ×5 → Abe"
    assert line2 == "= SELL HERE Tea ×3 → tutaj"


@unittest.skipUnless(os.environ.get("DISPLAY"), "potrzebny X (Xvfb)")
class RotationTest(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from edtrade import tce_theme as tce
        from edtrade.bottom_bar import BottomBar
        self.root = tk.Tk()
        self.bar = BottomBar(self.root, tce.Fonts(self.root))

    def tearDown(self):
        self.root.destroy()

    def test_rotation_and_clear(self):
        bar = self.bar
        self.assertIn("BRAK CELU", bar.name_label.cget("text"))
        bar.set_page("okolica", "OKAZJE W OKOLICY", "gold → abe")
        self.assertEqual(bar.tab_label.cget("text"), "OKAZJE W OKOLICY")
        bar.set_page("ladunek", "TWÓJ ŁADUNEK", "hold gold")
        self.assertEqual(bar._current, "okolica")       # nowa strona czeka na swoją kolej
        bar._tick()
        self.assertEqual(bar._current, "ladunek")
        bar._tick()
        self.assertEqual(bar._current, "okolica")
        bar.clear_page("okolica")
        self.assertEqual(bar._current, "ladunek")
        bar.clear_page("ladunek")
        self.assertIn("BRAK CELU", bar.name_label.cget("text"))
