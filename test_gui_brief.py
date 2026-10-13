#!/usr/bin/env python3
"""Test GUI z briefu settings_gwc.md"""
import os
import sys
import tkinter as tk
import json
from pathlib import Path

# Ustawienia DISPLAY
os.environ['DISPLAY'] = ':0'
os.environ['XDG_RUNTIME_DIR'] = '/run/user/1000'

# Pobierz XAUTHORITY z plasmashell
plasma_pid = None
for p in Path('/proc').glob('*/environ'):
    try:
        with open(p, 'r') as f:
            for line in f:
                if line.startswith('PID='):
                    # Sprawdź czy to plasmashell
                    pass
    except:
        pass

# Prostsze podejście: pobierz z /proc/$(pgrep -x plasmashell)/environ
try:
    plasma_proc = os.popen('pgrep -x plasmashell | head -1').read().strip()
    if plasma_proc:
        auth_file = Path(f'/proc/{plasma_proc}/environ')
        if auth_file.exists():
            with open(auth_file, 'r') as f:
                for line in f:
                    if 'XAUTHORITY' in line:
                        os.environ['XAUTHORITY'] = line.strip().split('=', 1)[1]
                        break
except Exception as e:
    print(f"Ostrzeżenie: nie udało się pobrać XAUTHORITY: {e}")

# Import i konfiguracja
sys.path.insert(0, str(Path.home() / 'Projekty' / 'ed-trade-overlay'))
from edtrade.panel import TradePanel

# Config testowy
cfg = {
    'journey_target_system': 'Colonia',
    'ship_range_ly': 32.5,
    'material_kind': 'Raw',
    'mining_mineral': 'Platinum',
    'game_window_class': 'steam_app_359320',
    'bar_only_when_game_focused': False
}

print("=== TEST GUI ===")
print(f"Config: {cfg}")

# Utwórz tymczasową ścieżkę configu
tmp_config_path = Path('/tmp/test_settings_config6.json')
if tmp_config_path.exists():
    tmp_config_path.unlink()

print(f"\nTworzę panel z config_path={tmp_config_path}")
panel = TradePanel(
    tk.Tk(),
    user_config=dict(cfg),
    config_path=tmp_config_path
)

# Ukryj okno
panel.window.withdraw()

# Sprawdź widżety w settings_frame
print("\n--- Widgety w settings_frame ---")
children = panel.settings_frame.winfo_children()
for i, child in enumerate(children):
    cls = child.__class__.__name__
    is_mapped = child.winfo_ismapped() if hasattr(child, 'winfo_ismapped') else 0
    width = child.winfo_width() if hasattr(child, 'winfo_width') else 0
    print(f"  [{i}] {cls}: ismapped={is_mapped}, width={width}")

# Sprawdź wartości zmiennych
print("\n--- Zmienne ---")
gw_class = panel.game_window_class_var.get()
bar_only = panel.bar_only_var.get()
print(f"game_window_class_var.get(): {gw_class}")
print(f"Expected: steam_app_359320")
print(f"bar_only_var.get(): {bar_only}")
print(f"Expected: False")

# Zmień wartości i zapisz
print("\n--- Test zapisu ---")
panel.game_window_class_var.set('Elite-Dangerous')
panel.bar_only_var.set(True)
panel.save_settings()

print(f"cfg['game_window_class'] po zapisie: {cfg['game_window_class']}")
print(f"cfg['bar_only_when_game_focused'] po zapisie: {cfg['bar_only_when_game_focused']}")

# Sprawdź plik configu
if tmp_config_path.exists():
    with open(tmp_config_path, 'r') as f:
        saved_cfg = json.load(f)
    print(f"\nPlik /tmp/test_settings_config6.json:")
    print(json.dumps(saved_cfg, indent=2))
    print(f"\nSprawdzenie:")
    print(f"  game_window_class = {saved_cfg.get('game_window_class')}")
    print(f"  bar_only_when_game_focused = {saved_cfg.get('bar_only_when_game_focused')}")
    print(f"  ship_range_ly niezmienione: {saved_cfg.get('ship_range_ly')} == 32.5 ? {saved_cfg.get('ship_range_ly') == 32.5}")

# Test walidacji ship_range
print("\n--- Test walidacji ship_range (abc) ---")
panel.ship_range_var.set('abc')
panel.save_settings()
print(f"Status po niepoprawnym ship_range: {panel.settings_status_var.get()}")
print(f"ship_range_ly nadal 32.5: {cfg.get('ship_range_ly')} == 32.5 ? {cfg.get('ship_range_ly') == 32.5}")

# Zamknij panel
panel.window.destroy()

print("\n=== KONIEC TESTU ===")
