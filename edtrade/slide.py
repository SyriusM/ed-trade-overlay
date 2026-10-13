"""Wysuwane paski jak w TCE: pasek wjeżdża zza krawędzi ekranu i chowa się za nią.

Widoczność paska ma dwa niezależne powody, oba muszą pozwalać:
  - user — przełączany skrótem (Shift+Num8 / Shift+Num2),
  - auto — tryb "pasek tylko gdy gra ma fokus" (main._apply_bar_visibility).
"""

import tkinter as tk
from typing import Callable, Optional

STEPS = 8
STEP_MS = 15


class SlidingBar:
    """Animuje okno overrideredirect (pełna szerokość) od/do górnej albo dolnej krawędzi ekranu."""

    def __init__(self, window: tk.Misc, edge: str = "top", height_fn: Optional[Callable[[], int]] = None):
        """height_fn — docelowa wysokość paska (okno schowane podaje w geometry() 1×1, więc nie z okna)."""
        assert edge in ("top", "bottom")
        self.window = window
        self.height_fn = height_fn
        self.edge = edge
        self.user_visible = True
        self.auto_visible = True
        self._shown = False
        self._job = None

    @property
    def visible(self) -> bool:
        return self.user_visible and self.auto_visible

    def _shown_y(self, height: int) -> int:
        return 0 if self.edge == "top" else self.window.winfo_screenheight() - height

    def _hidden_y(self, height: int) -> int:
        return -height if self.edge == "top" else self.window.winfo_screenheight()

    def _height(self) -> int:
        return self.height_fn() if self.height_fn else self.window.winfo_reqheight()

    def _move(self, y: int) -> None:
        self.window.geometry(f"+0+{y}")

    def place(self) -> None:
        """Po zmianie wysokości (skala czcionki) — ustaw pasek przy krawędzi bez animacji."""
        if self._shown:
            self._move(self._shown_y(self._height()))

    def toggle_user(self) -> None:
        self.set_user(not self.user_visible)

    def set_user(self, visible: bool, animate: bool = True) -> None:
        self.user_visible = visible
        self.apply(animate)

    def set_auto(self, visible: bool, animate: bool = False) -> None:
        self.auto_visible = visible
        self.apply(animate)

    def apply(self, animate: bool = True) -> None:
        want = self.visible
        if want == self._shown and self._job is None:
            return
        if self._job is not None:
            self.window.after_cancel(self._job)
            self._job = None
        height = self._height()
        start, end = (self._hidden_y(height), self._shown_y(height)) if want else \
            (self._shown_y(height), self._hidden_y(height))
        if want:
            self._move(start)
            self.window.deiconify()
        self._shown = want
        if not animate:
            self._finish(end)
            return
        self._step(start, end, 1)

    def _step(self, start: int, end: int, n: int) -> None:
        self._move(round(start + (end - start) * n / STEPS))
        if n < STEPS:
            self._job = self.window.after(STEP_MS, self._step, start, end, n + 1)
        else:
            self._finish(end)

    def _finish(self, end: int) -> None:
        self._job = None
        self._move(end)
        if not self._shown:
            self.window.withdraw()
