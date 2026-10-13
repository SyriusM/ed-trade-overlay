"""Schowek: narzędzia systemowe (wl-copy / xclip) obok Tk — działa bez fokusu okna nakładki."""

from unittest import mock

from edtrade import clipboard


class FakeWidget:
    def __init__(self):
        self.text = None

    def clipboard_clear(self):
        self.text = ""

    def clipboard_append(self, text):
        self.text = text


def test_uses_wl_copy_and_xclip_when_available(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("DISPLAY", ":0")
    calls = []
    with mock.patch.object(clipboard.shutil, "which", side_effect=lambda n: f"/usr/bin/{n}"), \
            mock.patch.object(clipboard, "_run", side_effect=lambda cmd, text: calls.append((cmd[0], text)) or True):
        w = FakeWidget()
        used = clipboard.copy("Cooper City", w)
    assert used == ["wl-copy", "xclip", "tk"] and w.text == "Cooper City"
    assert calls == [("wl-copy", "Cooper City"), ("xclip", "Cooper City")]


def test_falls_back_to_tk_only(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    with mock.patch.object(clipboard.shutil, "which", return_value=None):
        w = FakeWidget()
        assert clipboard.copy("61 Cygni", w) == ["tk"] and w.text == "61 Cygni"
