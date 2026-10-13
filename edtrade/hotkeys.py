"""Skróty klawiszowe jak w TCE: modyfikator + klawisz numeryczny = pasek albo strona panelu.

Pozycja klawisza na klawiaturze numerycznej to miejsce na ekranie (7 = lewy górny róg, 5 = środek,
3 = prawy dolny). Domyślnie Shift+Num8 chowa/pokazuje górny pasek, Shift+Num2 dolny, Shift+Num5 otwiera
główną stronę panelu (TRASA) na środku, pozostałe cyfry otwierają inne strony w swoich miejscach.
Ten sam skrót drugi raz chowa to, co otworzył.

Skąd przychodzą naciśnięcia (wszystkie trafiają do HotkeyManager.trigger w wątku Tk):
  1. Tk — gdy fokus ma okno aplikacji (panel).
  2. Gniazdo lokalne — `python -m edtrade.hotkeys <cel>` z dowolnego miejsca, np. ze skrótu globalnego
     KDE (Ustawienia systemowe → Skróty → Dodaj polecenie). Działa na Waylandzie nad grą.
  3. pynput (opcjonalnie, jeśli zainstalowany) — globalny nasłuch X11; gra chodzi przez XWayland,
     więc widzi klawisze, gdy fokus ma gra. Brak pynput albo X = po prostu pomijane.

Config: hotkey_modifier ("Shift"/"Control"/"Alt"/"Control+Shift"/"" = bez modyfikatora),
numpad_slots {"1".."9": cel}, cel = "top_bar" / "bottom_bar" / nazwa strony panelu (PANEL_PAGES) / "".
"""

import logging
import os
import socket
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

BAR_TARGETS = ("top_bar", "bottom_bar")
ACTION_TARGETS = ("copy_target",)  # kopiuj cel do schowka (drugi raz w kilka sekund: stacja ↔ system)
PANEL_PAGES = ("route", "nearby", "system", "materials", "mining", "commodity", "market", "journey",
               "engineering", "settings")
TARGETS = BAR_TARGETS + ACTION_TARGETS + PANEL_PAGES

DEFAULT_MODIFIER = "Shift"
DEFAULT_SLOTS: dict[str, str] = {
    "7": "system", "8": "top_bar", "9": "market",
    "4": "nearby", "5": "route", "6": "commodity",
    "1": "copy_target", "2": "bottom_bar", "3": "journey",
}
MODIFIERS = ("Shift", "Control", "Alt", "Control+Shift", "")

# Z NumLockiem Shift zamienia cyfrę na funkcję (Shift+KP_5 → KP_Begin) — sprowadzamy to do cyfry
_KEYPAD_ALIASES = {
    "kp_end": "1", "kp_down": "2", "kp_next": "3", "kp_page_down": "3",
    "kp_left": "4", "kp_begin": "5", "kp_right": "6",
    "kp_home": "7", "kp_up": "8", "kp_prior": "9", "kp_page_up": "9",
}
# Stan Tk: bity modyfikatorów w event.state
_TK_SHIFT, _TK_CONTROL, _TK_ALT = 0x1, 0x4, 0x8


def keypad_digit(keysym: str) -> Optional[str]:
    """'KP_5' / 'KP_Begin' / 'kp5' → '5'; inny klawisz → None."""
    key = keysym.strip().lower()
    if key in _KEYPAD_ALIASES:
        return _KEYPAD_ALIASES[key]
    if key.startswith("kp_") or key.startswith("kp"):
        digit = key[3:] if key.startswith("kp_") else key[2:]
        if len(digit) == 1 and digit in "123456789":
            return digit
    return None


def parse_modifier(text: str) -> frozenset[str]:
    """'Control+Shift' → {'control', 'shift'}; 'Ctrl' = 'Control'."""
    names = {"ctrl": "control", "control": "control", "shift": "shift", "alt": "alt"}
    return frozenset(names[p] for p in (x.strip().lower() for x in text.split("+")) if p in names)


def slot_geometry(slot: str, screen_w: int, screen_h: int, win_w: int, win_h: int,
                  top_margin: int = 0, bottom_margin: int = 0) -> tuple[int, int]:
    """Lewy górny róg okna w miejscu ekranu odpowiadającym cyfrze (układ klawiatury numerycznej)."""
    index = int(slot) - 1
    col, row = index % 3, 2 - index // 3  # 7-8-9 to górny rząd
    usable_h = max(win_h, screen_h - top_margin - bottom_margin)
    x = (0, (screen_w - win_w) // 2, screen_w - win_w)[col]
    y = top_margin + (0, (usable_h - win_h) // 2, usable_h - win_h)[row]
    return max(0, x), max(0, y)


def slots_from_config(config: dict) -> dict[str, str]:
    """Mapa cyfra → cel z configu, z odrzuceniem nieznanych celów (literówka w JSON nie wywraca aplikacji)."""
    raw = config.get("numpad_slots")
    slots = dict(DEFAULT_SLOTS) if not isinstance(raw, dict) else {}
    if isinstance(raw, dict):
        for digit, target in raw.items():
            digit = str(digit)
            if digit in "123456789" and len(digit) == 1:
                slots[digit] = target if target in TARGETS else ""
    return slots


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/edtrade-{os.getuid()}"
    return Path(runtime) / "ed-trade-overlay.sock"


class HotkeyManager:
    """Łączy naciśnięcia z akcjami. Wszystko poza wątkiem Tk przechodzi przez master.after(0, …)."""

    def __init__(self, master, config: dict, actions: dict[str, Callable[[Optional[str]], None]]):
        """actions: cel → funkcja(slot) — slot to cyfra klawisza (pozycja ekranu) albo None (z gniazda/CLI)."""
        self.master = master
        self.config = config
        self.actions = actions
        self._server: Optional[socket.socket] = None
        self._listener = None

    # --- dopasowanie ---
    def target_for(self, digit: str) -> str:
        return slots_from_config(self.config).get(digit, "")

    def slot_of(self, target: str) -> Optional[str]:
        return next((d for d, t in sorted(slots_from_config(self.config).items()) if t == target), None)

    def matches_modifier(self, pressed: frozenset[str]) -> bool:
        return pressed == parse_modifier(str(self.config.get("hotkey_modifier", DEFAULT_MODIFIER)))

    def trigger(self, target: str, slot: Optional[str] = None) -> bool:
        """Wykonaj akcję celu (wątek Tk). Zwraca False dla nieznanego celu."""
        action = self.actions.get(target)
        if action is None:
            logger.warning("Skrót: nieznany cel %r", target)
            return False
        logger.info("Skrót: %s (pozycja %s)", target, slot or "domyślna")
        action(slot if slot is not None else self.slot_of(target))
        return True

    def on_key(self, digit: Optional[str], pressed: frozenset[str]) -> bool:
        if digit is None or not self.matches_modifier(pressed):
            return False
        target = self.target_for(digit)
        return bool(target) and self.trigger(target, digit)

    # --- źródło 1: Tk ---
    def bind_tk(self, widget) -> None:
        widget.bind("<KeyPress>", self._on_tk_key, add="+")

    def _on_tk_key(self, event) -> Optional[str]:
        pressed = {name for bit, name in ((_TK_SHIFT, "shift"), (_TK_CONTROL, "control"), (_TK_ALT, "alt"))
                   if event.state & bit}
        return "break" if self.on_key(keypad_digit(event.keysym), frozenset(pressed)) else None

    # --- źródło 2: gniazdo lokalne (CLI / skróty globalne KDE) ---
    def start_socket(self, path: Optional[Path] = None) -> Optional[Path]:
        path = path or socket_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                path.unlink()
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(path))
            os.chmod(path, 0o600)
            server.listen(4)
        except OSError as e:
            logger.warning("Skróty: gniazdo %s niedostępne (%s) — tylko skróty w oknach aplikacji", path, e)
            return None
        self._server = server
        threading.Thread(target=self._serve, daemon=True, name="hotkey-socket").start()
        logger.info("Skróty: gniazdo %s (python -m edtrade.hotkeys <cel>)", path)
        return path

    def _serve(self) -> None:
        while self._server is not None:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            with conn:
                try:
                    command = conn.recv(256).decode("utf-8", "replace").strip()
                except OSError:
                    continue
                reply = self._handle_command(command)
                try:
                    conn.sendall(reply.encode())
                except OSError:
                    pass

    def _handle_command(self, command: str) -> str:
        """'top_bar' / 'route' / 'key 5' (cyfra jak z klawiatury, z mapą slotów)."""
        parts = command.split()
        if len(parts) == 2 and parts[0] == "key" and parts[1] in "123456789" and len(parts[1]) == 1:
            target, slot = self.target_for(parts[1]), parts[1]
        elif len(parts) == 1 and parts[0] in TARGETS:
            target, slot = parts[0], None
        else:
            return "error: unknown command\n"
        if not target:
            return "error: empty slot\n"
        self.master.after(0, self.trigger, target, slot)
        return "ok\n"

    # --- źródło 3: pynput (opcjonalny globalny nasłuch X11) ---
    def start_global_listener(self) -> bool:
        if str(self.config.get("global_hotkeys", "auto")) == "off":
            return False
        try:
            from pynput import keyboard
        except Exception as e:  # brak modułu albo brak X — to nie błąd aplikacji
            logger.info("Skróty: globalny nasłuch pynput niedostępny (%s)", e)
            return False
        pressed: set[str] = set()
        mod_keys = {keyboard.Key.shift: "shift", keyboard.Key.shift_r: "shift", keyboard.Key.ctrl: "control",
                    keyboard.Key.ctrl_l: "control", keyboard.Key.ctrl_r: "control", keyboard.Key.alt: "alt",
                    keyboard.Key.alt_l: "alt", keyboard.Key.alt_gr: "alt"}

        def on_press(key):
            if key in mod_keys:
                pressed.add(mod_keys[key])
                return
            digit = _pynput_keypad_digit(key)
            if digit is not None and self.matches_modifier(frozenset(pressed)) and self.target_for(digit):
                self.master.after(0, self.trigger, self.target_for(digit), digit)

        def on_release(key):
            if key in mod_keys:
                pressed.discard(mod_keys[key])

        try:
            self._listener = keyboard.Listener(on_press=on_press, on_release=on_release, daemon=True)
            self._listener.start()
        except Exception as e:
            logger.info("Skróty: nie udało się uruchomić pynput (%s)", e)
            return False
        logger.info("Skróty: globalny nasłuch pynput aktywny")
        return True

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            try:
                path = server.getsockname()
                server.close()
                if path:
                    Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        if self._listener is not None:
            self._listener.stop()


# Kody X11 klawiszy numerycznych (NumLock wł.: KP_1..KP_9 = 0xffb1..0xffb9, wył.: KP_End… = 0xff9c…)
_X11_KEYPAD = {0xffb0 + n: str(n) for n in range(1, 10)}
_X11_KEYPAD.update({0xff9c: "1", 0xff99: "2", 0xff9b: "3", 0xff96: "4", 0xff9d: "5", 0xff98: "6",
                    0xff95: "7", 0xff97: "8", 0xff9a: "9"})


def _pynput_keypad_digit(key) -> Optional[str]:
    vk = getattr(key, "vk", None)
    if vk is None and hasattr(key, "value"):
        vk = getattr(key.value, "vk", None)
    return _X11_KEYPAD.get(vk) if vk is not None else None


def send(command: str, path: Optional[Path] = None) -> str:
    """Wyślij polecenie do działającej aplikacji (CLI, skrót globalny KDE)."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(str(path or socket_path()))
        client.sendall(command.encode())
        return client.recv(256).decode().strip()


def main(argv: Optional[list[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] in ("-h", "--help", "--list"):
        print("Użycie: python -m edtrade.hotkeys <cel> | key <1-9>")
        print("Cele: " + ", ".join(TARGETS))
        from .config import load_user_config
        config = load_user_config()
        mod = config.get("hotkey_modifier", DEFAULT_MODIFIER)
        print("Twoje skróty (do skrótów globalnych KDE: polecenie = python -m edtrade.hotkeys key <cyfra>):")
        for digit, target in sorted(slots_from_config(config).items()):
            print(f"  {(mod + '+') if mod else ''}Num{digit}: {target or '—'}")
        return 0
    try:
        reply = send(" ".join(args))
    except OSError as e:
        print(f"Aplikacja nie działa albo gniazdo niedostępne ({socket_path()}): {e}", file=sys.stderr)
        return 1
    print(reply)
    return 0 if reply == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
