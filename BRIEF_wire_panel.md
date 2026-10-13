# Zadanie: IMPLEMENTACJA ONLY — podpięcie TradePanel w edtrade/main.py (UI krok 1)
Bez researchu, bez przeglądarki. Zmieniasz TYLKO edtrade/main.py (nie ruszaj panel.py, overlay.py, trade.py). Nie edytuj SPEC.md.
Kontekst: `edtrade/panel.py` ma gotową klasę `TradePanel(master: tk.Tk)` (okno Toplevel z zakładkami, metody `show()`/`hide()`), ale nikt jej nie tworzy. Overlay (`TradeOverlay`, `self.overlay`) ma `self.overlay.master` = główny obiekt tk.Tk, a jego `mainloop` startuje w `self.overlay.show()` wewnątrz `EDTradeOverlayApp.run()`.

## Zmiany (trzy, małe)
1. W `parse_args()` dodaj argument, w tym samym stylu co istniejący `--no-overlay`:
   parser.add_argument("--no-panel", action="store_true", help="Nie otwieraj panelu TCE (osobne okno z zakładkami)")
2. Na górze pliku dodaj import: `from .panel import TradePanel` (obok istniejących importów z pakietu).
3. W `EDTradeOverlayApp.__init__`, BEZPOŚREDNIO po linii `self.overlay = TradeOverlay() if self._show_overlay else None` dodaj:
   self.panel = None
   if self.overlay is not None and not args.no_panel:
       try:
           self.panel = TradePanel(self.overlay.master)
           logger.info("TradePanel utworzony (zakładki: System/Materiały/Mining/Journey)")
       except Exception:
           logger.exception("Nie udało się utworzyć TradePanel")
   (Panel tworzy się w głównym wątku, przed startem mainloop — tak ma być. Okno jest widoczne od razu; nie wołaj nic więcej.)

## Test (max 60 s) z katalogu ~/Projekty/ed-trade-overlay
a) python3 -m py_compile edtrade/main.py
b) python3 -m edtrade.main --help  → ma pokazać `--no-panel`
c) timeout 12 python3 -m edtrade.main --log-level INFO > /tmp/panelwire_test.log 2>&1 ; grep -c "TradePanel utworzony" /tmp/panelwire_test.log  → oczekiwane 1; wypisz też ewentualne linie z "Traceback" lub "ERROR".
Na końcu krótko: co zrobione + wyniki a/b/c.
