"""Testy skrótów (klawiatura numeryczna → pasek/strona w miejscu ekranu), wysuwanych pasków i karty stacji docelowej."""

import os
import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from edtrade import hotkeys
from edtrade.bottom_bar import card_fields, card_warning, format_age
from edtrade.destination import DestinationInfo, parse_spansh_system, to_timestamp

# Wycinek prawdziwego rekordu Spansh /api/system/10477373803 (Sol, 2026-10-13) + stan Lockdown dopisany do testu
SOL = {
    "name": "Sol", "security": "High",
    "minor_faction_presences": [
        {"name": "Mother Gaia", "state": "Expansion", "active_states": ["Expansion", "Lockdown"]},
        {"name": "Federal Congress", "state": "Civil Liberty", "active_states": ["Civil Liberty"]},
    ],
    "stations": [
        {"name": "Columbus", "type": "Ocellus Starport", "distance_to_arrival": 2614.460809,
         "has_large_pad": True, "large_pads": 6, "medium_pads": 12, "small_pads": 7,
         "controlling_minor_faction": "Mother Gaia", "controlling_minor_faction_state": "Expansion",
         "services": ["Dock", "Market", "Refuel", "Repair", "Restock", "Outfitting", "Shipyard", "Tuning"]},
        {"name": "Walz Depot", "type": "Outpost", "distance_to_arrival": 1200.0, "has_large_pad": False,
         "medium_pads": 2, "small_pads": 1, "controlling_minor_faction": "Federal Congress",
         "services": ["Dock", "Market", "Refuel", "Black Market"]},
    ],
}


class KeyParsingTest(unittest.TestCase):
    def test_keypad_digits_with_and_without_numlock(self):
        self.assertEqual(hotkeys.keypad_digit("KP_5"), "5")
        self.assertEqual(hotkeys.keypad_digit("KP_Begin"), "5")   # Shift+Num5 przy włączonym NumLocku
        self.assertEqual(hotkeys.keypad_digit("KP_Up"), "8")
        self.assertEqual(hotkeys.keypad_digit("KP_Next"), "3")
        self.assertEqual(hotkeys.keypad_digit("KP_Home"), "7")
        self.assertIsNone(hotkeys.keypad_digit("5"))
        self.assertIsNone(hotkeys.keypad_digit("KP_Add"))
        self.assertIsNone(hotkeys.keypad_digit("KP_0"))

    def test_modifier(self):
        self.assertEqual(hotkeys.parse_modifier("Shift"), {"shift"})
        self.assertEqual(hotkeys.parse_modifier("Ctrl+Shift"), {"control", "shift"})
        self.assertEqual(hotkeys.parse_modifier(""), frozenset())

    def test_slots_from_config(self):
        self.assertEqual(hotkeys.slots_from_config({}), hotkeys.DEFAULT_SLOTS)
        self.assertEqual(hotkeys.DEFAULT_SLOTS["5"], "route")
        slots = hotkeys.slots_from_config({"numpad_slots": {"5": "market", "1": "nonsense", "0": "route"}})
        self.assertEqual(slots, {"5": "market", "1": ""})

    def test_slot_geometry_follows_numpad_layout(self):
        args = (1920, 1080, 1100, 700)
        self.assertEqual(hotkeys.slot_geometry("7", *args), (0, 0))
        self.assertEqual(hotkeys.slot_geometry("5", *args), (410, 190))
        self.assertEqual(hotkeys.slot_geometry("3", *args), (820, 380))
        # paski zabierają miejsce u góry i u dołu
        self.assertEqual(hotkeys.slot_geometry("8", *args, top_margin=84, bottom_margin=52), (410, 84))
        self.assertEqual(hotkeys.slot_geometry("2", *args, top_margin=84, bottom_margin=52), (410, 328))


class _FakeMaster:
    def after(self, _ms, func, *args):
        func(*args)


class ManagerTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        actions = {t: (lambda slot, t=t: self.calls.append((t, slot))) for t in hotkeys.TARGETS}
        self.config = {"hotkey_modifier": "Shift", "numpad_slots": dict(hotkeys.DEFAULT_SLOTS)}
        self.manager = hotkeys.HotkeyManager(_FakeMaster(), self.config, actions)

    def test_key_needs_configured_modifier(self):
        self.assertFalse(self.manager.on_key("5", frozenset()))
        self.assertTrue(self.manager.on_key("5", frozenset({"shift"})))
        self.assertTrue(self.manager.on_key("8", frozenset({"shift"})))
        self.assertEqual(self.calls, [("route", "5"), ("top_bar", "8")])

    def test_config_change_applies_without_restart(self):
        self.config["hotkey_modifier"] = "Control"
        self.config["numpad_slots"]["5"] = "market"
        self.assertFalse(self.manager.on_key("5", frozenset({"shift"})))
        self.assertTrue(self.manager.on_key("5", frozenset({"control"})))
        self.assertEqual(self.calls, [("market", "5")])

    def test_empty_slot_does_nothing(self):
        self.config["numpad_slots"]["1"] = ""
        self.assertFalse(self.manager.on_key("1", frozenset({"shift"})))

    def test_socket_commands(self):
        path = Path(tempfile.mkdtemp()) / "edto.sock"
        self.assertEqual(self.manager.start_socket(path), path)
        try:
            self.assertEqual(hotkeys.send("bottom_bar", path), "ok")
            self.assertEqual(hotkeys.send("key 9", path), "ok")
            self.assertEqual(hotkeys.send("rm -rf", path), "error: unknown command")
            self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")
        finally:
            self.manager.stop()
        # cel z CLI → pozycja z mapy klawiszy; "key N" → pozycja N
        self.assertEqual(self.calls, [("bottom_bar", "2"), ("market", "9")])
        self.assertFalse(path.exists())


class DestinationTest(unittest.TestCase):
    def test_parse_station_card(self):
        info = parse_spansh_system(SOL, "columbus")
        self.assertEqual((info.station, info.station_type, info.pad), ("Columbus", "Ocellus Starport", "L"))
        self.assertAlmostEqual(info.distance_ls, 2614.46, places=1)
        self.assertEqual(info.faction, "Mother Gaia")
        self.assertEqual(info.faction_states, ["Expansion", "Lockdown"])
        self.assertTrue(info.lockdown)
        self.assertEqual(info.security, "High")
        self.assertEqual(info.services, ["paliwo", "naprawa", "amunicja", "outfitting", "stocznia"])

    def test_outpost_medium_pad(self):
        info = parse_spansh_system(SOL, "Walz Depot")
        self.assertEqual(info.pad, "M")
        self.assertEqual(info.faction_states, ["Civil Liberty"])
        self.assertFalse(info.lockdown)
        self.assertEqual(info.services, ["paliwo", "czarny rynek"])

    def test_missing_station(self):
        self.assertTrue(parse_spansh_system(SOL, "Nowhere").error)

    def test_card_text_and_warning(self):
        now = 1_800_000_000
        info = parse_spansh_system(SOL, "Columbus")
        info.distance_ly, info.market_updated_ts = 12.34, now - 3 * 3600
        fields = dict(card_fields(info, now))
        self.assertEqual(fields["PAD"], "L")
        self.assertEqual(fields["OD GWIAZDY"], "2,614 ls")
        self.assertEqual(fields["ODL."], "12.3 ly")
        self.assertEqual(fields["DANE RYNKU"], "3h temu")
        self.assertEqual(fields["FRAKCJA"], "Mother Gaia (Expansion, Lockdown)")
        text, _color = card_warning(info)
        self.assertIn("LOCKDOWN", text)
        info.faction_states = ["War"]
        self.assertIn("WAR", card_warning(info)[0])
        self.assertEqual(card_warning(DestinationInfo())[0], "")

    def test_age_and_timestamps(self):
        self.assertEqual(format_age(0), "?")
        self.assertEqual(format_age(100, now=130), "30s temu")
        self.assertEqual(format_age(0 + 1, now=1 + 5 * 86400), "5d temu")
        self.assertEqual(to_timestamp("2026-10-13T10:00:00Z"), 1791885600.0)
        self.assertEqual(to_timestamp(1791885600), 1791885600.0)
        self.assertEqual(to_timestamp(None), 0.0)


@unittest.skipUnless(os.environ.get("DISPLAY"), "potrzebny X (Xvfb)")
class GuiTest(unittest.TestCase):
    """Na prawdziwym Tk: wysuwanie pasków, strona panelu w miejscu klawisza, skrót z klawiatury w panelu."""

    def setUp(self):
        from edtrade.bottom_bar import BottomBar
        from edtrade.overlay import TradeOverlay
        from edtrade.panel import TradePanel
        self.config_path = Path(tempfile.mkdtemp()) / "config.json"
        self.overlay = TradeOverlay()
        self.bottom = BottomBar(self.overlay.master, self.overlay.fonts)
        self.panel = TradePanel(self.overlay.master, config_path=self.config_path,
                                bar_margins=lambda: (84, 52))
        self.root = self.overlay.master

    def tearDown(self):
        self.root.destroy()

    def pump(self, seconds=0.4):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            time.sleep(0.01)

    def test_bars_slide_in_and_out(self):
        self.overlay.slider.apply(animate=True)
        self.bottom.slider.apply(animate=True)
        self.pump()
        screen_h = self.root.winfo_screenheight()
        self.assertTrue(self.root.winfo_ismapped())
        self.assertEqual(self.root.winfo_y(), 0)
        self.assertEqual(self.bottom.window.winfo_y() + self.bottom.window.winfo_height(), screen_h)
        self.bottom.slider.toggle_user()
        self.pump()
        self.assertFalse(self.bottom.window.winfo_ismapped())
        # tryb "tylko przy grze" nie przywraca paska schowanego skrótem
        self.bottom.slider.set_auto(False)
        self.bottom.slider.set_auto(True)
        self.pump()
        self.assertFalse(self.bottom.window.winfo_ismapped())
        self.bottom.slider.toggle_user()
        self.pump()
        self.assertTrue(self.bottom.window.winfo_ismapped())
        self.assertEqual(self.bottom.window.winfo_y() + self.bottom.window.winfo_height(), screen_h)
        self.overlay.slider.toggle_user()
        self.pump()
        self.assertFalse(self.root.winfo_ismapped())

    def test_page_opens_at_numpad_position_and_toggles(self):
        self.pump(0.2)
        self.assertTrue(self.panel.toggle_page("market", "9"))
        self.pump()
        self.assertEqual(self.panel.current_page(), "market")
        self.assertEqual(self.panel.window.winfo_rootx() + self.panel.window.winfo_width(),
                         self.panel.window.winfo_screenwidth())
        self.assertTrue(self.panel.toggle_page("route", "5"))
        self.pump()
        self.assertEqual(self.panel.current_page(), "route")
        self.assertFalse(self.panel.toggle_page("route", "5"))
        self.pump()
        self.assertEqual(self.panel.window.state(), "withdrawn")

    def test_shift_numpad_in_panel_window(self):
        calls = []
        config = {"hotkey_modifier": "Shift", "numpad_slots": dict(hotkeys.DEFAULT_SLOTS)}
        manager = hotkeys.HotkeyManager(self.root, config, {"route": lambda slot: calls.append(slot)})
        manager.bind_tk(self.panel.window)
        self.panel.show()
        self.pump()
        self.panel.window.focus_force()
        self.pump(0.2)
        self.panel.window.event_generate("<KeyPress>", keysym="KP_Begin", state=0x1)
        self.panel.window.event_generate("<KeyPress>", keysym="KP_5", state=0x0)
        self.pump(0.2)
        self.assertEqual(calls, ["5"])

    def test_settings_grid_saves_slots(self):
        self.panel.slot_vars["5"].set(self.panel._target_labels["market"])
        self.panel.hotkey_modifier_var.set("Control")
        self.panel.save_settings()
        self.assertEqual(self.panel.user_config["numpad_slots"]["5"], "market")
        self.assertEqual(self.panel.user_config["numpad_slots"]["8"], "top_bar")
        self.assertEqual(self.panel.user_config["hotkey_modifier"], "Control")
        self.panel.show()
        self.panel.nav.select_frame(self.panel.tab_settings)
        self.pump()
        for var in self.panel.slot_vars.values():
            self.assertTrue(var.get())


if __name__ == "__main__":
    unittest.main()
