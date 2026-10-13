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
