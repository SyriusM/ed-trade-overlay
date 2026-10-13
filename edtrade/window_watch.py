"""Odczyt aktywnego okna (KDE Plasma 6) przez kdotool — do wykrywania, czy gra ma fokus."""

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

KDOTOOL = "kdotool"

# Bez tych zmiennych kdotool zwraca "Unsupported KDE version" (np. gdy overlay startuje ze skryptu/terminala bez sesji KDE)
KDE_SESSION_VARS = ("KDE_SESSION_VERSION", "KDE_FULL_SESSION", "XDG_CURRENT_DESKTOP", "DBUS_SESSION_BUS_ADDRESS",
                    "XDG_RUNTIME_DIR", "WAYLAND_DISPLAY", "DISPLAY")

_kde_env: Optional[dict[str, str]] = None


def _plasmashell_environ() -> dict[str, str]:
    """Zmienne sesji z procesu plasmashell tego samego użytkownika (pusty słownik, gdy nie znaleziono)."""
    uid = os.getuid()
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            if proc.stat().st_uid != uid or (proc / "comm").read_text().strip() != "plasmashell":
                continue
            raw = (proc / "environ").read_bytes()
        except OSError:
            continue
        return dict(item.split("=", 1) for item in raw.decode(errors="replace").split("\0") if "=" in item)
    return {}


def _kdotool_env() -> dict[str, str]:
    """Środowisko dla kdotool: własne + brakujące zmienne sesji KDE wzięte z plasmashell (liczone raz)."""
    global _kde_env
    if _kde_env is None:
        env = dict(os.environ)
        missing = [v for v in KDE_SESSION_VARS if not env.get(v)]
        if missing:
            session = _plasmashell_environ()
            filled = {v: session[v] for v in missing if session.get(v)}
            env.update(filled)
            logger.info("kdotool: brak zmiennych sesji KDE %s, uzupełniono z plasmashell: %s",
                        missing, sorted(filled) or "nic")
        _kde_env = env
    return _kde_env


def _run(args: list[str]) -> Optional[str]:
    try:
        out = subprocess.run(
            [KDOTOOL, *args],
            capture_output=True,
            text=True,
            timeout=3,
            env=_kdotool_env(),
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
