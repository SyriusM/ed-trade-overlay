# Zadanie (JEDEN mały krok, krok A): NOWY plik edtrade/window_watch.py — NIC innego nie zmieniaj
Nie edytuj istniejących plików (panel.py, main.py, overlay.py, trade.py, config.py, SPEC.md). Bez researchu, bez przeglądarki.

## Cel
Funkcja zwracająca klasę i tytuł aktualnie aktywnego okna na KDE Plasma 6 przez narzędzie `kdotool`.

## Utwórz plik ~/Projekty/ed-trade-overlay/edtrade/window_watch.py o DOKŁADNEJ treści:

"""Odczyt aktywnego okna (KDE Plasma 6) przez kdotool — do wykrywania, czy gra ma fokus."""

import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

KDOTOOL = "kdotool"


def _run(args: list[str]) -> Optional[str]:
    try:
        out = subprocess.run(
            [KDOTOOL, *args],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.debug("kdotool %s failed: %s", args, e)
        return None
    if out.returncode != 0:
        logger.debug("kdotool %s rc=%s stderr=%s", args, out.returncode, out.stderr.strip())
        return None
    return out.stdout.strip()


def get_active_window() -> Optional[tuple[str, str]]:
    """Zwróć (classname, title) aktywnego okna albo None, gdy kdotool niedostępny/błąd."""
    win_id = _run(["getactivewindow"])
    if not win_id:
        return None
    window_class = _run(["getwindowclassname", win_id])
    if window_class is None:
        return None
    title = _run(["getwindowname", win_id]) or ""
    return window_class, title

## Test (max 60 s). Powłoka NIE ma zmiennych sesji KDE — ustaw je DOSŁOWNIE tak (bez nich kdotool zwraca "Unsupported KDE version"):
PID=$(pgrep -x plasmashell | head -1); for v in KDE_SESSION_VERSION XDG_CURRENT_DESKTOP DBUS_SESSION_BUS_ADDRESS KDE_FULL_SESSION; do export "$v=$(tr '\0' '\n' < /proc/$PID/environ | grep "^$v=" | cut -d= -f2-)"; done; export DISPLAY=:0 WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000
a) cd ~/Projekty/ed-trade-overlay && python3 -m py_compile edtrade/window_watch.py
b) python3 -c "from edtrade.window_watch import get_active_window; print(get_active_window())"
   Oczekiwane: krotka (str, str) z niepustą klasą, np. ('org.wezfurlong.wezterm', '...').
c) Test bez środowiska KDE: env -i PATH="$PATH" python3 -c "from edtrade.window_watch import get_active_window; print(get_active_window())"
   Oczekiwane: None albo krotka, ale BEZ wyjątku/Traceback.
Na końcu krótko: wyniki a/b/c (wypisz dosłownie, co zwróciło b i c).
