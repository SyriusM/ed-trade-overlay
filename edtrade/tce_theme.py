"""Wygląd w stylu TCE Mk.II: czarne tło, pomarańczowe paski nagłówków, wiersze w brązie, WIELKIE LITERY.

Kolory zmierzone na zrzutach TCE (wiki): nagłówki #FF8000, wiersze #401F0C / #1F1000.
Tylko wygląd i układ — żadnych grafik ani logo TCE.
"""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import Callable, Optional, Sequence

BG = "#000000"
ORANGE = "#ff8000"
ORANGE_DIM = "#7a3d00"
ROW_BG = "#401f0c"
ROW_BG_DARK = "#1f1000"
TEXT_WHITE = "#ffffff"
TEXT_ON_ORANGE = "#000000"
GREEN = "#4cff4c"
RED = "#ff3b30"
BLUE = "#5ab4ff"

# Pierwsza dostępna — TCE używa wąskiego, "technicznego" kroju
FONT_CANDIDATES = (
    "Eurostile", "Euro Caps", "Michroma", "Orbitron", "Rajdhani", "Saira Semi Condensed",
    "Barlow Semi Condensed", "Exo 2", "Inter", "DejaVu Sans Condensed", "DejaVu Sans", "Liberation Sans",
)


def pick_font_family(root: tk.Misc) -> str:
    available = {f.lower(): f for f in tkfont.families(root)}
    for name in FONT_CANDIDATES:
        if name.lower() in available:
            return available[name.lower()]
    return "TkDefaultFont"


class Fonts:
    def __init__(self, root: tk.Misc, scale: float = 1.0):
        family = pick_font_family(root)
        self.family = family
        self.tab = tkfont.Font(root, family=family, size=round(10 * scale), weight="bold")
        self.title = tkfont.Font(root, family=family, size=round(13 * scale), weight="bold")
        self.section = tkfont.Font(root, family=family, size=round(11 * scale), weight="bold")
        self.body = tkfont.Font(root, family=family, size=round(10 * scale))
        self.body_bold = tkfont.Font(root, family=family, size=round(10 * scale), weight="bold")
        self.big = tkfont.Font(root, family=family, size=round(15 * scale), weight="bold")


def apply_ttk_theme(root: tk.Misc, fonts: Fonts) -> None:
    """Globalny styl ttk — istniejące ttk.Entry/Combobox/Button/Checkbutton dostają wygląd TCE bez zmian w kodzie."""
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=ORANGE, font=fonts.body, bordercolor=ORANGE_DIM,
                    focuscolor=ORANGE, troughcolor=BG, fieldbackground=ROW_BG, selectbackground=ORANGE,
                    selectforeground=TEXT_ON_ORANGE, insertcolor=ORANGE)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=ORANGE, font=fonts.body_bold)
    style.configure("TButton", background=BG, foreground=TEXT_WHITE, bordercolor=ORANGE, lightcolor=BG,
                    darkcolor=BG, font=fonts.tab, padding=(10, 3))
    style.map("TButton", background=[("disabled", BG), ("pressed", ORANGE), ("active", ROW_BG)],
              foreground=[("disabled", ORANGE_DIM), ("pressed", TEXT_ON_ORANGE)])
    style.configure("TEntry", fieldbackground=ROW_BG, foreground=ORANGE, bordercolor=ORANGE_DIM,
                    lightcolor=ROW_BG, darkcolor=ROW_BG, insertcolor=ORANGE, padding=3)
    style.configure("TCombobox", fieldbackground=ROW_BG, foreground=ORANGE, background=ORANGE,
                    arrowcolor=TEXT_ON_ORANGE, bordercolor=ORANGE_DIM, lightcolor=ROW_BG, darkcolor=ROW_BG, padding=3)
    style.map("TCombobox", fieldbackground=[("readonly", ROW_BG)], foreground=[("readonly", ORANGE)],
              selectbackground=[("readonly", ROW_BG)], selectforeground=[("readonly", ORANGE)])
    root.option_add("*TCombobox*Listbox.background", ROW_BG)
    root.option_add("*TCombobox*Listbox.foreground", ORANGE)
    root.option_add("*TCombobox*Listbox.selectBackground", ORANGE)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT_ON_ORANGE)
    style.configure("TCheckbutton", background=BG, foreground=ORANGE, indicatorbackground=ROW_BG,
                    indicatorforeground=ORANGE, font=fonts.body_bold)
    style.map("TCheckbutton", background=[("active", BG)], indicatorbackground=[("selected", ORANGE)])
    style.configure("Vertical.TScrollbar", background=ORANGE_DIM, troughcolor=BG, bordercolor=BG,
                    arrowcolor=TEXT_ON_ORANGE, lightcolor=ORANGE_DIM, darkcolor=ORANGE_DIM, gripcount=0)
    style.map("Vertical.TScrollbar", background=[("active", ORANGE), ("pressed", ORANGE)])
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.configure("Treeview", background=ROW_BG, fieldbackground=BG, foreground=ORANGE, font=fonts.body_bold,
                    rowheight=fonts.body.metrics("linespace") + 8, bordercolor=BG, borderwidth=0)
    style.map("Treeview", background=[("selected", ORANGE)], foreground=[("selected", TEXT_ON_ORANGE)])
    style.configure("Treeview.Heading", background=ORANGE, foreground=TEXT_ON_ORANGE, font=fonts.tab,
                    relief="flat", bordercolor=BG, lightcolor=ORANGE, darkcolor=ORANGE, padding=(4, 2))
    style.map("Treeview.Heading", background=[("active", ORANGE)])
    # Zakładki notebooka ukryte — nawigacja przyciskami TCE (NavBar)
    style.configure("TCE.TNotebook", background=BG, borderwidth=1, tabmargins=0, bordercolor=ORANGE_DIM,
                    lightcolor=BG, darkcolor=BG)
    style.layout("TCE.TNotebook.Tab", [])


def uppercase_static_texts(widget: tk.Misc) -> None:
    """TCE pisze wszystko WIELKIMI — etykiety/przyciski ze stałym tekstem (bez textvariable)."""
    for child in widget.winfo_children():
        if isinstance(child, (ttk.Label, ttk.Button, ttk.Checkbutton)) and not str(child.cget("textvariable")):
            child.configure(text=str(child.cget("text")).upper())
        uppercase_static_texts(child)


def style_text(widget: tk.Text, fonts: Fonts) -> None:
    widget.configure(bg=BG, fg=ORANGE, insertbackground=ORANGE, selectbackground=ORANGE,
                     selectforeground=TEXT_ON_ORANGE, font=fonts.body_bold, relief=tk.FLAT,
                     highlightthickness=1, highlightbackground=ORANGE_DIM, highlightcolor=ORANGE, padx=8, pady=6)


def _tab(parent: tk.Misc, text: str, fonts: Fonts, bg: str = ORANGE, fg: str = TEXT_ON_ORANGE,
         command: Optional[Callable[[], None]] = None) -> tk.Label:
    label = tk.Label(parent, text=text.upper(), bg=bg, fg=fg, font=fonts.tab, padx=14, pady=1)
    if command:
        label.configure(cursor="hand2")
        label.bind("<Button-1>", lambda _e: command())
    return label


class TitleBar(tk.Frame):
    """Pasek każdego panelu TCE: [CONTROL] po lewej, nazwa na środku, [HIDE] po prawej."""

    def __init__(self, parent: tk.Misc, title: str, fonts: Fonts,
                 on_control: Optional[Callable[[], None]] = None, on_hide: Optional[Callable[[], None]] = None):
        super().__init__(parent, bg=BG, highlightthickness=0)
        self.control = _tab(self, "CONTROL", fonts, command=on_control)
        self.control.pack(side=tk.LEFT)
        self.hide = _tab(self, "HIDE", fonts, command=on_hide)
        self.hide.pack(side=tk.RIGHT)
        self.title = _tab(self, title, fonts)
        self.title.configure(padx=40)
        self.title.pack(side=tk.TOP)
        tk.Frame(self, bg=ORANGE, height=1).pack(side=tk.BOTTOM, fill=tk.X)

    def set_title(self, title: str) -> None:
        self.title.configure(text=title.upper())


class SectionHeader(tk.Frame):
    """Biały nagłówek sekcji z pomarańczową linią pod spodem (np. "TRADE ROUTE LISTING")."""

    def __init__(self, parent: tk.Misc, text: str, fonts: Fonts, right_text: str = ""):
        super().__init__(parent, bg=BG)
        row = tk.Frame(self, bg=BG)
        row.pack(fill=tk.X)
        self.label = tk.Label(row, text=text.upper(), bg=BG, fg=TEXT_WHITE, font=fonts.section, anchor="w")
        self.label.pack(side=tk.LEFT)
        self.right = tk.Label(row, text=right_text.upper(), bg=BG, fg=TEXT_WHITE, font=fonts.section, anchor="e")
        self.right.pack(side=tk.RIGHT)
        tk.Frame(self, bg=ORANGE, height=2).pack(fill=tk.X, pady=(1, 0))

    def set(self, text: Optional[str] = None, right_text: Optional[str] = None) -> None:
        if text is not None:
            self.label.configure(text=text.upper())
        if right_text is not None:
            self.right.configure(text=right_text.upper())


class SegmentedButtons(tk.Frame):
    """Rząd przycisków-trybów (EXPORTS / IMPORTS / …): aktywny wypełniony na pomarańczowo."""

    def __init__(self, parent: tk.Misc, options: Sequence[tuple[str, str]], fonts: Fonts,
                 command: Callable[[str], None], initial: Optional[str] = None, variable: Optional[tk.StringVar] = None):
        super().__init__(parent, bg=BG)
        self._command = command
        self._variable = variable
        self.buttons: dict[str, tk.Label] = {}
        for key, text in options:
            btn = tk.Label(self, text=text.upper(), font=fonts.tab, padx=12, pady=3, cursor="hand2",
                           highlightthickness=1, highlightbackground=ORANGE)
            btn.pack(side=tk.LEFT, padx=(0, 6), fill=tk.X, expand=True)
            btn.bind("<Button-1>", lambda _e, k=key: self.select(k))
            self.buttons[key] = btn
        self.current = initial or (variable.get() if variable else options[0][0])
        self._paint()

    def _paint(self) -> None:
        for key, btn in self.buttons.items():
            active = key == self.current
            btn.configure(bg=ORANGE if active else BG, fg=TEXT_ON_ORANGE if active else TEXT_WHITE)

    def select(self, key: str, notify: bool = True) -> None:
        self.current = key
        if self._variable is not None:
            self._variable.set(key)
        self._paint()
        if notify:
            self._command(key)


class DataTable(tk.Frame):
    """Tabela TCE: pomarańczowe nagłówki (klik = sortowanie), brązowe wiersze, przewijanie."""

    def __init__(self, parent: tk.Misc, columns: Sequence[tuple[str, str, int, str]], height: int = 10):
        """columns: (klucz, tytuł, szerokość px, anchor 'w'/'e'/'center')."""
        super().__init__(parent, bg=BG, highlightthickness=1, highlightbackground=ORANGE_DIM)
        keys = [c[0] for c in columns]
        self.tree = ttk.Treeview(self, columns=keys, show="headings", height=height, selectmode="browse")
        self._sort_desc: dict[str, bool] = {}
        for key, title, width, anchor in columns:
            self.tree.heading(key, text=title.upper(), anchor=anchor, command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=width, minwidth=20, anchor=anchor, stretch=False)
        self._base_widths = {c[0]: c[2] for c in columns}
        # Treeview sam nie zwęża kolumn poniżej zadanej szerokości — przy 2 tabelach obok siebie wypadały poza krawędź
        self.tree.bind("<Configure>", self._fit_columns)
        scroll = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0), pady=4)
        scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=2, pady=4)
        self.tree.tag_configure("dim", foreground=ORANGE_DIM)
        self.tree.tag_configure("good", foreground=GREEN)
        self.tree.tag_configure("bad", foreground=RED)
        self._sort_values: dict[str, dict] = {}

    def _fit_columns(self, event: tk.Event) -> None:
        total = sum(self._base_widths.values())
        for key, width in self._base_widths.items():
            self.tree.column(key, width=max(20, int(width * event.width / total)))

    def set_rows(self, rows: Sequence[Sequence], sort_values: Optional[Sequence[dict]] = None,
                 tags: Optional[Sequence[str]] = None) -> None:
        """rows: wartości wyświetlane; sort_values: opcjonalne surowe wartości do sortowania (klucz kolumny → liczba)."""
        self.tree.delete(*self.tree.get_children())
        self._sort_values = {}
        for i, row in enumerate(rows):
            iid = self.tree.insert("", tk.END, values=[str(v).upper() for v in row],
                                   tags=(tags[i],) if tags and tags[i] else ())
            if sort_values:
                self._sort_values[iid] = sort_values[i]

    def rows(self) -> list[tuple]:
        return [tuple(self.tree.item(i, "values")) for i in self.tree.get_children()]

    def sort_by(self, key: str) -> None:
        desc = not self._sort_desc.get(key, False)
        self._sort_desc[key] = desc

        def value(iid: str):
            raw = self._sort_values.get(iid, {}).get(key)
            return raw if raw is not None else self.tree.set(iid, key)

        items = sorted(self.tree.get_children(), key=value, reverse=desc)
        for index, iid in enumerate(items):
            self.tree.move(iid, "", index)
        for k in self.tree["columns"]:
            title = self.tree.heading(k, "text").rstrip(" ▲▼")
            self.tree.heading(k, text=title + ((" ▼" if desc else " ▲") if k == key else ""))


class KeyValueGrid(tk.Frame):
    """Lista "ETYKIETA  [wartość w brązowym polu]" jak w Trade Overview (STAR SYSTEM / ECONOMY / …)."""

    def __init__(self, parent: tk.Misc, keys: Sequence[tuple[str, str]], fonts: Fonts):
        super().__init__(parent, bg=BG)
        self.columnconfigure(1, weight=1)
        self.values: dict[str, tk.Label] = {}
        for row, (key, title) in enumerate(keys):
            tk.Label(self, text=title.upper(), bg=BG, fg=ORANGE, font=fonts.body_bold, anchor="w").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=1)
            value = tk.Label(self, text="", bg=ROW_BG, fg=ORANGE, font=fonts.body_bold, anchor="w", padx=6)
            value.grid(row=row, column=1, sticky="ew", pady=1)
            self.values[key] = value

    def set(self, **values: str) -> None:
        for key, text in values.items():
            if key in self.values:
                self.values[key].configure(text=str(text).upper())


class NavBar(tk.Frame):
    """Rząd przycisków stron panelu (zamiast zakładek notebooka) — wygląd jak DISPLAY MODE w TCE."""

    def __init__(self, parent: tk.Misc, notebook: ttk.Notebook, fonts: Fonts,
                 on_change: Optional[Callable[[str], None]] = None):
        super().__init__(parent, bg=BG)
        self.notebook = notebook
        self._on_change = on_change
        pages = [(str(tab), notebook.tab(tab, "text")) for tab in notebook.tabs()]
        self.segments = SegmentedButtons(self, pages, fonts, command=self._select, initial=pages[0][0])
        self.segments.pack(fill=tk.X)

    def _select(self, tab_id: str) -> None:
        self.notebook.select(tab_id)
        if self._on_change:
            self._on_change(self.notebook.tab(tab_id, "text"))

    def select_frame(self, frame: tk.Misc) -> None:
        self.segments.select(str(frame))
