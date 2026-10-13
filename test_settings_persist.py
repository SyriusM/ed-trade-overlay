"""Ustawienia zapisują się same po zmianie i wracają po restarcie (bez klikania ZAPISZ)."""

import json
import tempfile
import unittest
from pathlib import Path

try:
    import tkinter as tk
except ImportError:
    tk = None

from edtrade.config import load_user_config, save_user_config


class TestSaveUserConfig(unittest.TestCase):
    def test_roundtrip_and_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, 'sub', 'config.json')
            save_user_config({'panel_font_scale': 0.8, 'new_key': 'x'}, path)
            cfg = load_user_config(path)
            self.assertEqual(cfg['panel_font_scale'], 0.8)
            self.assertEqual(cfg['new_key'], 'x')
            self.assertEqual([p.name for p in path.parent.iterdir()], ['config.json'])


def _make_root():
    if tk is None:
        return None
    try:
        root = tk.Tk()
    except tk.TclError:
        return None
    root.withdraw()
    return root


class TestSettingsAutosave(unittest.TestCase):
    def setUp(self):
        self.root = _make_root()
        if self.root is None:
            self.skipTest('brak Tk/wyświetlacza')
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name, 'config.json')

    def tearDown(self):
        self.root.destroy()
        self.tmp.cleanup()

    def _panel(self):
        from edtrade.panel import TradePanel
        return TradePanel(self.root, user_config=load_user_config(self.path), config_path=self.path)

    def _flush(self, panel):
        """Odpal zaplanowany autozapis od razu (zamiast czekać na after())."""
        self.root.update()
        if panel._autosave_job is not None:
            panel.window.after_cancel(panel._autosave_job)
            panel._autosave()

    def test_slider_change_survives_restart(self):
        panel = self._panel()
        panel.panel_scale_var.set(0.85)
        panel.bar_scale_var.set(1.3)
        panel.bar_only_var.set(True)
        panel.game_window_class_var.set('steam_app_x')
        self._flush(panel)
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(saved['panel_font_scale'], 0.85)
        self.assertEqual(saved['bar_font_scale'], 1.3)
        self.assertTrue(saved['bar_only_when_game_focused'])
        self.assertEqual(saved['game_window_class'], 'steam_app_x')

        restarted = self._panel()
        self.assertAlmostEqual(restarted.panel_scale_var.get(), 0.85)
        self.assertEqual(restarted.game_window_class_var.get(), 'steam_app_x')

    def test_every_settings_field_is_watched(self):
        panel = self._panel()
        before = self.path.read_text(encoding='utf-8')
        panel.max_star_var.set('1200')
        self._flush(panel)
        self.assertNotEqual(before, self.path.read_text(encoding='utf-8'))
        self.assertEqual(load_user_config(self.path)['max_star_distance_ls'], 1200.0)


if __name__ == '__main__':
    unittest.main()
