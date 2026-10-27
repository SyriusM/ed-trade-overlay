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

# Werdykty oceny okazji (edtrade/assess.py): każda klasa ma gradient (start → koniec), shade 0–1 wybiera kolor.
# OPTIMAL limonka → oliwka (NOT OPTIMAL); SAFE zielony → ciemnozielony (VERY SAFE); RISKY czerwony (wysoki zysk)
# → ciemnoczerwony (VERY RISKY: okazji pewnie już nie ma); HOLD żółty → bursztynowy.
LIME = "#b8ff2e"
VERDICT_GRADIENTS = {
    "optimal": (LIME, "#8fa82a"),  # limonka → oliwka (NOT OPTIMAL)
    "safe": ("#4cff4c", "#1e9a32"),
    "risky": ("#ff3b30", "#b01a1a"),
    "hold": ("#ffd23f", "#d08a00"),
}
VERDICT_COLORS = {k: v[0] for k, v in VERDICT_GRADIENTS.items()}
VERDICT_LEVELS = 6


def _mix(c1: str, c2: str, t: float) -> str:
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def _level(shade: float) -> int:
    return min(VERDICT_LEVELS - 1, int(max(0.0, min(1.0, shade)) * VERDICT_LEVELS))


def verdict_color(verdict: str, shade: float) -> str:
    """Kolor z gradientu klasy (skwantowany do VERDICT_LEVELS, tak jak tagi tabel)."""
    start, end = VERDICT_GRADIENTS[verdict]
    return _mix(start, end, _level(shade) / (VERDICT_LEVELS - 1))


def verdict_tag(verdict: str, shade: float) -> str:
    return f"v_{verdict}_{_level(shade)}"


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
    BASE_SIZES = {"tab": 10, "title": 13, "section": 11, "body": 10, "body_bold": 10, "big": 15}
    BOLD = {"tab", "title", "section", "body_bold", "big"}

    def __init__(self, root: tk.Misc, scale: float = 1.0):
        self.family = pick_font_family(root)
        self.scale = scale
        for name, size in self.BASE_SIZES.items():
            setattr(self, name, tkfont.Font(root, family=self.family, size=round(size * scale),
                                            weight="bold" if name in self.BOLD else "normal"))

    def set_scale(self, scale: float) -> None:
        """Zmiana na żywo — widgety używające tych obiektów Font przerysowują się same."""
        self.scale = scale
        for name, size in self.BASE_SIZES.items():
            getattr(self, name).configure(size=max(6, round(size * scale)))


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
    style.configure("Horizontal.TScale", background=ORANGE, troughcolor=ROW_BG, bordercolor=ORANGE_DIM,
                    lightcolor=ORANGE, darkcolor=ORANGE)
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


def set_table_row_height(root: tk.Misc, fonts: Fonts) -> None:
    ttk.Style(root).configure("Treeview", rowheight=fonts.body.metrics("linespace") + 8)


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

    def add_tab(self, text: str, fonts: Fonts, command: Callable[[], None]) -> tk.Label:
        """Dodatkowa zakładka po prawej, obok [HIDE] (np. [REFRESH])."""
        tab = _tab(self, text, fonts, command=command)
        tab.pack(side=tk.RIGHT, padx=(0, 4), before=self.title)
        return tab


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
        for verdict in VERDICT_GRADIENTS:
            for level in range(VERDICT_LEVELS):
                self.tree.tag_configure(f"v_{verdict}_{level}",
                                        foreground=verdict_color(verdict, (level + 0.5) / VERDICT_LEVELS))
        self._sort_values: dict[str, dict] = {}
        self._payloads: dict = {}

    def _fit_columns(self, event: tk.Event) -> None:
        total = sum(self._base_widths.values())
        for key, width in self._base_widths.items():
            self.tree.column(key, width=max(20, int(width * event.width / total)))

    def set_rows(self, rows: Sequence[Sequence], sort_values: Optional[Sequence[dict]] = None,
                 tags: Optional[Sequence[str]] = None, payloads: Optional[Sequence] = None) -> None:
        """rows: wartości wyświetlane; sort_values: surowe wartości do sortowania; payloads: obiekt za wierszem."""
        self.tree.delete(*self.tree.get_children())
        self._sort_values = {}
        self._payloads = {}
        for i, row in enumerate(rows):
            iid = self.tree.insert("", tk.END, values=[str(v).upper() for v in row],
                                   tags=(tags[i],) if tags and tags[i] else ())
            if sort_values:
                self._sort_values[iid] = sort_values[i]
            if payloads:
                self._payloads[iid] = payloads[i]

    def selected_payload(self):
        selection = self.tree.selection()
        return self._payloads.get(selection[0]) if selection else None

    def on_activate(self, callback) -> None:
        """Dwuklik / Enter na wierszu → callback(payload) — jak PREVIEW w Route Finder TCE."""
        handler = lambda _e: (self.selected_payload() is not None) and callback(self.selected_payload())
        self.tree.bind("<Double-1>", handler)
        self.tree.bind("<Return>", handler)

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


class GroupedNavBar(tk.Frame):
    """Nawigacja w dwóch poziomach: grupy wg celu (HANDEL / NAWIGACJA / …) i strony w grupie.

    Zamiast jednego rzędu wszystkich stron (TCE ma płaskie menu, łatwo się zgubić).
    """

    def __init__(self, parent: tk.Misc, notebook: ttk.Notebook, fonts: Fonts,
                 groups: Sequence[tuple[str, Sequence[tk.Misc]]], on_change: Optional[Callable[[str], None]] = None):
        super().__init__(parent, bg=BG)
        self.notebook = notebook
        self._on_change = on_change
        self._pages = {title: [str(f) for f in frames] for title, frames in groups}
        self._group_of = {page: title for title, pages in self._pages.items() for page in pages}
        self._last_page = {title: pages[0] for title, pages in self._pages.items()}
        first = groups[0][0]
        self.groups = SegmentedButtons(self, [(t, t) for t, _ in groups], fonts, command=self._select_group, initial=first)
        self.groups.pack(fill=tk.X)
        self._sub_holder = tk.Frame(self, bg=BG)
        self._sub_holder.pack(fill=tk.X, pady=(4, 0))
        self._subs: dict[str, SegmentedButtons] = {}
        for title, pages in self._pages.items():
            if len(pages) > 1:
                self._subs[title] = SegmentedButtons(
                    self._sub_holder, [(pid, notebook.tab(pid, "text")) for pid in pages], fonts,
                    command=self._select_page, initial=pages[0])
        self._show_group(first)
        self._show(self._last_page[first])

    def _show_group(self, title: str) -> None:
        for name, sub in self._subs.items():
            if name == title:
                sub.pack(fill=tk.X, padx=(24, 0))
            else:
                sub.pack_forget()

    def _select_group(self, title: str) -> None:
        self._show_group(title)
        self._show(self._last_page[title])

    def _select_page(self, page_id: str) -> None:
        self._last_page[self._group_of[page_id]] = page_id
        self._show(page_id)

    def _show(self, page_id: str) -> None:
        self.notebook.select(page_id)
        if self._on_change:
            self._on_change(self.notebook.tab(page_id, "text"))

    def select_frame(self, frame: tk.Misc) -> None:
        page_id = str(frame)
        title = self._group_of[page_id]
        self.groups.select(title, notify=False)
        self._show_group(title)
        if title in self._subs:
            self._subs[title].select(page_id, notify=False)
        self._last_page[title] = page_id
        self._show(page_id)


class SuggestEntry(ttk.Entry):
    """Pole z podpowiedziami: po kilku literach lista pasujących nazw pod polem (bez zabierania fokusu).

    source(tekst) → lista nazw; remote=True: źródło sieciowe — w wątku, z opóźnieniem po ostatnim klawiszu.
    ↓/↑ wybór, Enter/Tab/klik akceptuje (on_select), Esc zamyka. ↓ w pustym polu pokazuje całą listę.
    """

    NAV_KEYS = {"Up", "Down", "Return", "KP_Enter", "Escape", "Tab", "ISO_Left_Tab", "Shift_L", "Shift_R",
                "Control_L", "Control_R", "Alt_L", "Alt_R", "Left", "Right", "Home", "End"}

    def __init__(self, parent: tk.Misc, source: Callable[[str], list], textvariable: tk.StringVar,
                 fonts: "Fonts", remote: bool = False, on_select: Optional[Callable[[str], None]] = None,
                 delay_ms: int = 300, **kw):
        super().__init__(parent, textvariable=textvariable, **kw)
        self.var = textvariable
        self.source = source
        self.remote = remote
        self.on_select = on_select
        self.delay_ms = delay_ms
        self._job = None
        self._generation = 0
        self.popup = tk.Toplevel(self)
        self.popup.withdraw()
        self.popup.overrideredirect(True)
        try:
            self.popup.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        self.listbox = tk.Listbox(self.popup, bg=ROW_BG, fg=ORANGE, selectbackground=ORANGE,
                                  selectforeground=TEXT_ON_ORANGE, font=fonts.body_bold, activestyle="none",
                                  highlightthickness=1, highlightbackground=ORANGE, bd=0, exportselection=False)
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.listbox.bind("<ButtonRelease-1>", lambda _e: self._accept())
        self.bind("<KeyRelease>", self._on_key, add="+")
        self.bind("<Down>", lambda _e: self._move(1), add="+")
        self.bind("<Up>", lambda _e: self._move(-1), add="+")
        self.bind("<Return>", self._on_return, add="+")
        self.bind("<KP_Enter>", self._on_return, add="+")
        self.bind("<Tab>", self._on_tab, add="+")
        self.bind("<Escape>", lambda _e: self.hide(), add="+")
        self.bind("<FocusOut>", lambda _e: self.after(200, self._hide_unless_focused), add="+")

    # --- wyszukiwanie ---
    def _on_key(self, event) -> None:
        if event.keysym in self.NAV_KEYS:
            return
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(self.delay_ms if self.remote else 0, self.refresh)

    def refresh(self, show_all: bool = False) -> None:
        """Przelicz podpowiedzi dla bieżącego tekstu (źródło sieciowe — w wątku)."""
        self._job = None
        self._generation += 1
        generation, typed = self._generation, self.var.get()
        if not typed.strip() and not show_all:
            self.hide()
            return
        if not self.remote:
            self.show(self._safe_source(typed))
            return
        import threading
        threading.Thread(target=lambda: self._deliver(generation, typed, self._safe_source(typed)),
                         daemon=True).start()

    def _safe_source(self, typed: str) -> list:
        try:
            return list(self.source(typed))
        except Exception:
            return []

    def _deliver(self, generation: int, typed: str, items: list) -> None:
        try:
            self.after(0, lambda: generation == self._generation and self.var.get() == typed and self.show(items))
        except (tk.TclError, RuntimeError):
            pass

    # --- lista ---
    def show(self, items: list) -> None:
        typed = self.var.get().strip().lower()
        if not items or (len(items) == 1 and items[0].lower() == typed) or self.focus_get() is not self:
            self.hide()
            return
        self.listbox.delete(0, tk.END)
        for item in items:
            self.listbox.insert(tk.END, item)
        self.listbox.configure(height=min(len(items), 10))
        self.update_idletasks()
        width = max(self.winfo_width(), max(self.listbox.winfo_reqwidth(), 120))
        self.popup.geometry(f"{width}x{self.listbox.winfo_reqheight()}"
                            f"+{self.winfo_rootx()}+{self.winfo_rooty() + self.winfo_height()}")
        self.popup.deiconify()
        self.popup.lift()

    def visible(self) -> bool:
        return bool(self.popup.winfo_ismapped())

    def hide(self) -> None:
        self.popup.withdraw()

    def _hide_unless_focused(self) -> None:
        if self.focus_get() is not self:
            self.hide()

    def _move(self, step: int) -> str:
        if not self.visible():
            self.refresh(show_all=True)
            return "break"
        size = self.listbox.size()
        if size:
            current = self.listbox.curselection()
            index = (current[0] + step) % size if current else (0 if step > 0 else size - 1)
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(index)
            self.listbox.see(index)
        return "break"

    def _accept(self) -> None:
        current = self.listbox.curselection()
        if current:
            self.var.set(self.listbox.get(current[0]))
            self.icursor(tk.END)
        self.hide()
        self.focus_set()
        if self.on_select is not None:
            self.on_select(self.var.get())

    def _on_return(self, _event) -> str:
        if self.visible() and self.listbox.curselection():
            self._accept()
        else:
            self.hide()
            if self.on_select is not None and self.var.get().strip():
                self.on_select(self.var.get())
        return "break"

    def _on_tab(self, _event) -> Optional[str]:
        if self.visible() and self.listbox.size():
            if not self.listbox.curselection():
                self.listbox.selection_set(0)
            self._accept()
            return "break"
        return None
