"""Schowek systemowy, który działa także, gdy okno nakładki nie ma fokusu (gra jest na wierzchu).

Sam schowek Tk to selekcja X11 — na KDE/Wayland trafia do schowka systemu niepewnie, gdy okno nie ma
fokusu. Dlatego kopiujemy też narzędziami systemu: `wl-copy` (Wayland, pakiet wl-clipboard) i `xclip`/
`xsel` (X11/XWayland — gra przez Proton). Tk zostaje jako zapas.
"""

import logging
import os
import shutil
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)
_warned = False


def _run(cmd: list[str], text: str) -> bool:
    try:
        # Narzędzia zostają w tle jako właściciel schowka — nie czekamy na nie
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        proc.stdin.write(text.encode("utf-8"))
        proc.stdin.close()
        return True
    except OSError as e:
        logger.debug("Schowek: %s nie zadziałał (%s)", cmd[0], e)
        return False


def copy(text: str, widget=None) -> list[str]:
    """Skopiuj tekst wszystkimi dostępnymi sposobami; zwraca listę użytych ("wl-copy", "xclip", "tk")."""
    global _warned
    used = []
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        if _run(["wl-copy", "-n"], text):
            used.append("wl-copy")
    if os.environ.get("DISPLAY"):
        if shutil.which("xclip") and _run(["xclip", "-selection", "clipboard"], text):
            used.append("xclip")
        elif shutil.which("xsel") and _run(["xsel", "--clipboard", "--input"], text):
            used.append("xsel")
    if widget is not None:
        try:
            widget.clipboard_clear()
            widget.clipboard_append(text)
            used.append("tk")
        except Exception as e:
            logger.debug("Schowek Tk: %s", e)
    if used == ["tk"] and not _warned:
        _warned = True
        logger.warning("Schowek tylko przez Tk — w grze może nie działać. Zainstaluj wl-clipboard (Wayland) "
                       "i/lub xclip: sudo pacman -S wl-clipboard xclip")
    return used
