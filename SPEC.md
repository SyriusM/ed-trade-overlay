# ED Trade Overlay — MVP spec

## Cel
Overlay nad grą Elite Dangerous (Linux, Proton, działa przez XWayland), pokazujący
najbardziej opłacalną trasę handlową z aktualnej stacji — zamiennik TCE Mk.II, bez
Wine/Mono. Po dokowaniu w stacji ma sam się odświeżyć i pokazać co kupić/sprzedać i gdzie.

## Dlaczego tak (kontekst decyzji)
- EDDiscovery (open source, ma overlay + route planner) odrzucone: build wymaga Mono +
  msbuild + submoduły, instrukcja z 2023, nieznane czy overlay w ogóle rysuje się pod
  Mono/Linux (overlaye WinForms zwykle łażą po natywnym Windows API).
- MangoHud odrzucony: to zamknięty overlay wydajności (FPS/temp), brak API na własne dane.
- TCE Mk.II odrzucony wcześniej (19.08): program Windows/Delphi, wymagałby osobnego
  prefiksu Wine tylko pod overlay.
- Automatyzacja samego handlu/mining (boty sterujące inputem) odrzucona — łamie ToS
  Frontiera (bany), tu NIE wchodzi w grę. To ma być tylko doradca, nic nie steruje grą.

## Architektura
1. **Backend: Trade Dangerous** — już zainstalowany i działa:
   `~/Projekty/trade-dangerous`, venv python3.12 w `.venv/`, `pip install -e .` zrobione.
   Trzeba dociągnąć dane cenowe: `trade import --plug eddblink` (plugin TD, lekki,
   inkrementalny — NIE pełny dump Spansh 40GB, tamten jest zbyt duży, odrzucony).
   Sprawdzić `trade import -P eddblink -O help` co do opcji przed pobraniem.
2. **Źródło "gdzie jestem"**: journal Elite Dangerous, żywy plik:
   `~/.local/share/Steam/steamapps/compatdata/359320/pfx/drive_c/users/steamuser/Saved Games/Frontier Developments/Elite Dangerous/`
   — najnowszy `Journal.<data>.log` (JSONL), event `"event":"Docked"` ma `StarSystem`
   i `StationName`. `Status.json` ma stan na żywo.
3. **Logika**: po evencie Docked → wywołać `trade run --fr "<System>/<Stacja>"` (albo
   odpowiedni subcommand TD liczący najlepszą pojedynczą trasę, sprawdzić dokładną
   składnię w `trade run --help`) → sparsować output → wypchnąć do overlaya.
4. **Overlay**: zwykłe okno X11, przezroczyste tło, always-on-top, bez dekoracji
   (override-redirect albo odpowiedni window-type hint). Gra chodzi przez XWayland,
   gniazdo `/tmp/.X11-unix/X0` istnieje — potwierdzone że jest się o co zaczepić.
   Python + Tkinter (najmniej zależności) albo PyGObject/GTK jeśli wygodniej.
   Treść: System/stacja docelowa, towar do kupienia, cena, ile wozić (cargo = 304 t,
   patrz niżej), szacowany zysk.
5. **Watcher**: prosty proces w tle śledzący journal (tail -F na najnowszy plik,
   uważać na rotację pliku przy restarcie gry — brać najnowszy wg mtime) i odpalający
   odświeżenie przy nowym evencie `Docked`.

## Renderowanie overlaya — ograniczenia systemowe
- **Exclusive fullscreen blokuje overlay**. Elite Dangerous w trybie exclusive fullscreen
  (Proton/DXVK) zajmuje cały bufor wyświetlania; kompozytor KWin (Wayland) nie pozwala
  na nakładanie innych okien. Overlay NIE będzie widoczny w tym trybie.
- **Rozwiązanie**: w ustawieniach ED wybrać **Windowed Fullscreen** (Borderless).
  W tym trybie ED renderuje do okna bez ramki, a kompozytor pozwala na nakładanie
  innych okien (XWayland overlay działa normalnie).
- Overlay jest skonfigurowany jako `overrideredirect + -type splash` (bez dekoracji,
  always-on-top, przezroczystość `-alpha 0.75`), pozycja: górny pasek pełnej szerokości,
  wysokość 50px, treść wyśrodkowana.

## Dane o graczu (do wstrzyknięcia w logikę, nie hardkodować na sztywno — czytać z journala)
- Statek obecnie używany do handlu: Anaconda, cargo capacity 304 t (ostatni pomiar,
  sprawdzić aktualnie z `Loadout` w journalu, mogło się zmienić).
- Gra w Solo (nie Open) — nieistotne dla tego narzędzia, ale dla kontekstu.

## Zakres MVP (uzgodniony z userem)
Tylko: **najlepsza pojedyncza trasa z aktualnej stacji**. NIE pełna pętla wielostacyjna,
NIE dodatkowe funkcje TCE (to ewentualnie później, jeśli MVP się sprawdzi).

## Kolejność pracy — rób TO PO KOLEI, osobny krok = osobna tura, nie wszystko naraz
Powód: krótszy kontekst na turę = lepsze trafianie w cache promptu, szybciej.
Po każdym kroku potwierdź "działa" (pokaż output/test) zanim przejdziesz dalej.

1. **Import danych TD** — `trade import -P eddblink -O help`, potem pobranie. Zero kodu
   Python na tym etapie.
2. **Odczyt pozycji z journala** — mały skrypt: znajdź najnowszy `Journal.*.log` po
   mtime (NIE po nazwie), wyłap event `"event":"Docked"`, wypisz `StarSystem`/`StationName`.
3. **Wywołanie TD i parsing** — podepnij wynik kroku 2 pod `trade run --fr "<System>/<Stacja>"`
   (sprawdź dokładną składnię w `trade run --help`), sparsuj output do prostej struktury
   (towar, cena, zysk).
4. **Overlay X11** — osobno od reszty: proste okno Tkinter z na sztywno wpisanym tekstem,
   sprawdź najpierw czy w ogóle usiądzie nad grą przez XWayland, zanim podepniesz dane.
5. **Spięcie całości** — watcher na journalu + wrzucanie wyniku kroku 3 do okna z kroku 4.
   Wzorzec watchera: NIE pisać własnego `tail -F` w pętli. Oficjalny EDMC
   (`~/Pobrane/EDMarketConnector/monitor.py`, metoda `worker()` ok. linii 357+) robi to tak:
   - najnowszy plik journala: `os.path.getctime()`, NIE `st_mtime` (metoda
     `journal_newest_filename()`, linia ~265)
   - otwórz plik binarnie bez bufora: `open(logfile, 'rb', 0)`
   - przeczytaj istniejące linie do końca (catch-up), zapamiętaj pozycję przez `loghandle.tell()`
   - do śledzenia nowych linii/nowego pliku (rotacja journala) użyj biblioteki **`watchdog`**
     (`FileSystemEventHandler`), NIE ręcznego pollingu w pętli ze sleep
   To jest kod sprawdzony na produkcji przez EDMC — kopiuj wzorzec, nie zgaduj od zera.

## 🚀 KICKSTART dla następnej sesji (2026-10-12 wieczór, nadpisuje starszy kickstart niżej — TEN jest aktualny)

**UWAGA: sekcja "AKTUALIZACJA 2026-10-12: lokalny TD DZIAŁA, użyj tego, nie Spansh" niżej jest
NIEAKTUALNA.** Backend ostatecznie przełączony Z POWROTEM na Spansh API (działa, zweryfikowane
wielokrotnie realnymi requestami). Lokalny TD zostaje jako nieużywany fallback w kodzie.

**Stan na teraz — backend DZIAŁA:**
- Spansh API jako backend: `POST https://spansh.co.uk/api/trade/route` **jako
  form-encoded (`requests.post(url, data=payload)`), NIE JSON** (`json=` zawsze zwraca 400
  "system and station are required"). Payload to zwykłe stringi `system`/`station` — **żadne
  station_id/market_id nie jest potrzebne**, Spansh sam rozwiązuje nazwy.
- Polling wyniku: `GET https://spansh.co.uk/api/results/{job_id}` (BEZ prefiksu `trade/` —
  `/api/trade/results/...` to 404). Czas odpowiedzi ~40-180s, pollować co ~5s.
- `calculate_route_via_spansh()` + `_parse_spansh_result()` w `edtrade/trade.py` działają —
  potwierdzone wielokrotnie realnymi trasami (np. Sol/Columbus → UV Ceti, 3 hopy, zysk
  7 711 680 cr; Sol/Columbus → Handh, zysk 4 066 446 cr).
- **Czasem Spansh zwraca `state=completed status=ok` z PUSTYM wynikiem** ("brak opłacalnych
  tras") dla niektórych stacji/systemów — nie zawsze to bug, może być realny brak trasy w
  zasięgu `max_hop_distance`. Przy podejrzeniu buga retestuj na znanym dobrym punkcie
  (Sol/Columbus).

**Naprawione buty w tej sesji:**
- `overlay.py`: `font_info` miał `size=0` (błąd) → naprawione na `size=11`.
- `watcher.py`: gra wysyła event `Location` z polem `Docked=true`, NIE osobny event `Docked`
  — watcher musi to konwertować. Też `Capacity` → `CargoCapacity` w Loadout.
- `trade.py`: `td_dir` jako `str` → `Path()` (TypeError); `hop.dest_system` →
  `hop.destination_system` (zła nazwa pola); usunięte nieistniejące `hop.cumulative_profit`
  (to pole jest tylko na całej trasie, nie na pojedynczym Hop).

**ZAMKNIĘTE 2026-10-12 15:11 — overlay nie aktualizował się wizualnie:**
- Bug: okno X11 wisiało na "Oczekiwanie na event Docked..." mimo `state=completed status=ok`
  z realną trasą w logu. Naprawione przez Qwena: thread-safe wzorzec w `overlay.py`
  (`_route_queue` + `threading.Lock()` + `master.after(0, _on_route_ready)`), `update_route()`
  tylko ustawia kolejkę pod lockiem, `_on_route_ready()` w mainloopie Tkinter przenosi trasę
  do `current_route`, `refresh()` renderuje.
- **Potwierdzone realnie przeze mnie (nie tylko deklaracją Qwena):** log DEBUG
  (`/tmp/edto_debug.log`) pokazuje pełny łańcuch `update_route() CALL` →
  `_on_route_ready(): route moved to current_route` → `refresh(): status_label set to
  'Trasa obliczona ✓'`, ORAZ świeży zrzut ekranu (`/tmp/overlay_check5.png`) faktycznie
  pokazuje na oknie trasę Sol/Columbus → Handh, zysk 6 086 910cr — bez wstrzykiwania
  syntetycznego eventu, zadziałało z istniejącego journala od razu przy starcie.
- Wpis w DPO logu: `~/.mempalace/dpo/ed-trade-overlay.jsonl`, `verdict: pass`,
  `category: correct-breakthrough` (2026-10-12T15:11).
- Test szedł przez `main.py` **z overlayem** (bez `--no-overlay`), `--log-level DEBUG`.
  Metodologia: NIE wstrzykiwać wielu syntetycznych eventów Docked pod rząd (wcześniej
  5 eventów w ~3 min przerywało kolejne joby Spansh zanim się skończyły) — jeden cykl,
  czekać do ~180s, dopiero wtedy oceniać. Zasada obowiązuje nadal dla przyszłych testów.

**Brak znanych nierozwiązanych blockerów na dziś** — główny bug MVP zamknięty i
zweryfikowany wizualnie. Kolejne kroki: dalsze testy stabilności (różne stacje, powtarzane
dokowania), porządkowanie kodu, ewentualnie UI polish.

**AKTUALIZACJA 2026-10-12 wieczór — ulepszenia watcher.py:**
- **Steam fallback**: `_STEAM_ROOTS` (3 ścieżki: `~/.local/share/Steam`, `~/.steam/steam`,
  `~/.var/app/...`) + glob fallback po `compatdata/359320/*/Saved Games/...` — obsługuje
  różne instalacje Steam (native, Flatpak, Proton).
- **Partial line handling**: `except json.JSONDecodeError` z komentarzem — gra dopisuje
  w locie, niekompletne linie JSON są cicho pomijane.
- **Cargo.json auto-load**: `_load_cargo_json()` czyta `Inventory` z
  `Saved Games/.../Cargo.json` przy starcie, wypełnia `_player_cargo` (lista pozycji) —
  stan cargo znany od razu, bez czekania na event z journala. Zabezpieczony na brak pliku
  i błędny JSON (nie wywala watchera).
- **main.py**: `_on_cargo` callback już ma `self.overlay.set_player_cargo(cargo_list)`.
- Zweryfikowane: `py_compile` OK, test functionalny z realnym Cargo.json (2 pozycje:
  biowaste 246, drones/limpets 10).

**TCE Mk.II porzucony całkowicie** — zamknięte źródło (Delphi), nieudana instalacja przez
Wine (błąd 1603). Artefakty do posprzątania: `~/Projekty/tce-mk2/`, `~/.wine-tce/`.

**Znany problem meta: kompaktowanie opencode psuje literalne stringi** (ścieżki projektu
pojawiały się w 4 różnych literówkach w jednej sesji: `edtrade-overlay`, `ede-trade-overlay`,
`etrade-overlay` — poprawna to TYLKO `~/Projekty/ed-trade-overlay/`). Nie ufaj ścieżkom/ID z
podsumowań po kompaktowaniu bez weryfikacji na dysku (`ls`/`grep`).

**Log ocen pod DPO:** `~/.mempalace/dpo/ed-trade-overlay.jsonl` — przy każdej kolejnej
korekcie/potwierdzeniu dopisuj wpis (schemat w pamięci `reference_dpo_log_qwen_ed_trade_overlay_1012`).

## ✅ AKTUALIZACJA 2026-10-12: lokalny TD DZIAŁA, użyj tego, nie Spansh
Import `eddblink` się skończył (17,5 mln wierszy w `StationItem`). Potwierdzony realny
przebieg z `Sol/Columbus`:
```
trade run --from "Sol/Columbus" --capacity 192 --credits 75000000 --ly-per 32 --routes 1 --quiet
```
→ zwraca poprawną trasę z zyskiem (sprawdzone ręcznie). Flaga `--ly-per` jest WYMAGANA
(zasięg skoku statku), weź z journala `Loadout` → pole `MaxJumpRange`.
Ominięta blokada: `--direct` wymaga JEDNOCZEŚNIE `--from` i `--to` — nie używaj `--direct`
dla trasy "stąd gdziekolwiek", tylko zostaw bez niej.
Sekcja "API Spansh" niżej zostaje jako opis na wypadek gdyby lokalna baza się zepsuła,
ale NIE jest teraz potrzebna — trzymaj się lokalnego TD.

## API Spansh jako alternatywa dla lokalnego Trade Dangerous (ZWERYFIKOWANE w przeglądarce)
Jeśli lokalny import TD (`eddblink`, 1 GB listings.csv) jest zbyt wolny/uciążliwy, jest
publiczne, działające, bezpłatne API Spansh — bez klucza, zero lokalnej bazy:
1. `GET https://spansh.co.uk/api/stations?q=<nazwa>` — wyszukiwarka stacji, zwraca listę z ID
2. `POST https://spansh.co.uk/api/trade/route` — zleca policzenie trasy (async job, zwraca
   202 + `job` UUID). Parametry zaobserwowane w realnym requeście: `starting_station_id`,
   `max_cargo`, `starting_capital`, `max_hops`, `max_hop_distance`, `max_system_distance`,
   `allow_planetary`, `allow_player_owned`, `allow_prohibited`, `allow_restricted_access`,
   `requires_large_pad`, `permit`, `unique`.
3. `GET https://spansh.co.uk/api/results/<job-uuid>` — polling; pole `status`:
   `queued` → `running` → (docelowo) gotowy wynik z trasą. Trzeba pollować co kilka sekund.
Minus: zależność od zewnętrznego serwera i czasu odpowiedzi (w teście trasa wisiała w
`queued` ponad 20s — może być kolejka). Plus: zero utrzymania bazy, zawsze świeże dane.

## Czego unikać
- Nie pisać niczego, co steruje inputem w grze (klikanie, sterowanie statkiem) — tylko
  odczyt i wyświetlanie.
- Nie pobierać pełnego dumpa Spansh (40 GB rozpakowane) — użyć eddblink.
- Nie zakładać ścieżek na sztywno bez sprawdzenia — najnowszy plik journala trzeba
  wybierać po mtime, nie po nazwie (gra tworzy nowy plik przy każdym starcie).

## Znany problem: lokalny Trade Dangerous (fallback)
Lokalny Trade Dangerous w `~/Projekty/trade-dangerous` jest obecnie **niedostępny** —
`python3 trade.py run ...` rzuca `ModuleNotFoundError: No module named 'sqlalchemy'`.
Aby przywrócić lokalny TD jako fallback, trzeba odpalić `pip install sqlalchemy`
w odpowiednim venv (`~/Projekty/trade-dangerous/.venv/bin/pip install sqlalchemy`).
Na razie backend działa wyłącznie przez Spansh API.

## Roadmap (2026-10-12, po zamknięciu MVP)
Kierunek dalszej rozbudowy — **inspirowany** funkcjami TCE Mk.II (sam program zamknięte
źródło/Delphi, nic z kodu nie wyciągnięto; lista funkcji zweryfikowana przez wiki fanowskie
i wątek na forum Frontier, nie zgadywana). Podejście: róbmy to lepiej i konfigurowalnie
(TCE jest stare, Windows-only, słabo konfigurowalne) — nie kopiujemy, tylko bierzemy pomysły.
Budować po jednym punkcie na raz, z pełną weryfikacją (log + zrzut ekranu) przed przejściem dalej.

**Pełna lista paneli TCE Mk.II** (źródło: [wiki](https://trade-computer-extension-mkii.fandom.com/wiki/Trade_Computer_Extension_Mk.II_Wiki),
[forum Frontier](https://forums.frontier.co.uk/goto/post?id=7220292)) — punkt odniesienia,
nie wszystko trzeba robić: Cargo, Cartography (Stellar Cartography), Commodities, Database,
Factions, Minimap (nawigacja do zapisanych punktów na powierzchni planety, zasięgi
5km/1km/500m), Missions, Navigation, Notes, Personal, Planetary map, Route finder,
Route planner, Shopping, Summary, Trade overview ("Auto Destination" — najbliższa stacja
handlowa w zasięgu), Waypoints, Event reporter, Position tracking.

**Ważna różnica architektoniczna względem TCE**: TCE używał **lokalnej bazy** (dostarczana
pusta, wypełniana danymi rynku przez EDMC przy każdym dokowaniu) — nie API live jak Spansh.
Plusy lokalnej bazy: działa offline, zero zależności od zewnętrznego serwera, zawsze Twoje
własne świeże dane z miejsc gdzie byłeś. Minus: baza rośnie tylko tam, gdzie byłeś, nie ma
od razu zasięgu całej galaktyki. Rozważyć jako **hybrydę**: Spansh jako główne źródło
(szeroki zasięg), lokalna baza zasilana z journala (`Market`/`Docked`) jako fallback offline
i dla szybszych powtórnych zapytań — nie decydować teraz, osobny punkt poniżej.

**Zrobione (MVP + dzień 2026-10-12):**
- Trasa handlowa multi-hop (Spansh), overlay top-bar, świeżość danych,
  ostrzeżenie o niezwiązanym cargo, licznik hopów/skoków FSD, tankowanie (scoopable star).

**Zrobione (2026-10-13):**
- Punkt 1: wyszukiwarka stacji (`search_stations()`/`StationInfo` w trade.py, Ardent API) —
  zweryfikowane (62 stacje dla Sol).
- Punkt 2: info o systemie docelowym (`get_system_info()`/`SystemInfo`, Spansh API) — ZAMKNIĘTE.
  Naprawione 3 bugi: usunięta martwa zduplikowana definicja `SystemInfo`/`get_system_info`
  (zakładała nieistniejące `record.systems[]`), poprawiony klucz `name` (było
  `record.get("system", "")`, powinno być `record.get("name", "")`), dodane pole
  `error: str = ""` do dataclass (ścieżka błędu zwracała `SystemInfo(error=...)`, czego
  dataclass nie miał — wywalałoby `TypeError`). Zweryfikowane realnym zapytaniem:
  `get_system_info('10477373803')` → `name='Sol'`.

**Następne, w kolejności:**
3. Planer trasy skoków (journey planner) — czysta nawigacja A→B z tankowaniem po drodze,
   niezależnie od handlu.
4. Wyszukiwarka materiałów inżynieryjnych.
5. Trasy górnicze (mining) — osobna logika optymalizacji.
6. Materiały do kolonizacji/budowy.
7. Lokalna baza cen zasilana z journala (hybryda ze Spansh, opisana wyżej) — do rozważenia
   po punktach 1-6, większa zmiana architektury.

**Poza zakresem (świadomie pominięte):** cokolwiek sterującego inputem w grze (boty),
śledzenie walki/bounty, panele czysto kosmetyczne TCE (Notes, Personal, Summary) —
chyba że użytkownik poprosi.

### 3. Planer trasy skoków (journey planner) — Research: czysta nawigacja A→B z tankowaniem
**Cel**: Oblicz optymalną trasę skoków z punktu A do punktu B, z opcjonalnym tankowaniem na pośrednich stacjach. Nie optymalizuje zysku handlowego, tylko minimalizuje dystans/liczba skoków.

**Dane/API**:
- **Stacje**: Ardent API `GET /v2/system/name/{system}/stations` — zwraca `stationName`, `systemName`, `distanceToArrival`, `maxLandingPadSize`, `services` (refuel, repair, itp.).
- **Systemy**: Spansh API `GET /api/system/<id64>` — zwraca `name`, `id64`, `stations` (lista stacji w systemie), `bodies` (gwiazdy).
- **Konwersja nazwa→ID**: Spansh search `GET /search/{query}` + parsowanie HTML (używane już w `get_station_id()`).

**Sygnatura funkcji**:
```python
def plan_journey(
    start_system: str,
    start_station: str,
    end_system: str,
    end_station: str,
    fuel_level: float = 100.0,      # % paliwa w zbiorniku (0-100)
    fuel_capacity: float = 304.0,  # maksymalna pojemność
    min_fuel_reserve: float = 20.0, # % paliwa rezerwa (nie tankować poniżej)
    max_hops: int = 5,             # max liczba skoków
    max_hop_distance: float = 40.0, # ly (limit skoku)
) -> JourneyPlan:
```

**Dataclass wyniku**:
```python
@dataclass
class JourneyPlan:
    """Plan trasy skoków z tankowaniem."""
    start_system: str = ""
    start_station: str = ""
    end_system: str = ""
    end_station: str = ""
    total_distance: float = 0.0  # ly
    total_jumps: int = 0
    hops: list[JourneyHop] = field(default_factory=list)  # lista hopów
    
    @dataclass
    class JourneyHop:
        source_system: str = ""
        source_station: str = ""
        destination_system: str = ""
        destination_station: str = ""
        distance: float = 0.0  # ly
        fuel_needed: float = 0.0  # % paliwa do zużycia
        fuel_to_add: float = 0.0  # % paliwa do tankowania (0 jeśli nie trzeba)
        refuel_available: bool = False
        error: str = ""
```

**Edge case'y**:
1. **Brak paliwa na start** (`fuel_level == 0`) → `JourneyPlan(error="Brak paliwa na starcie")`.
2. **Brak trasy (nieosiągalny cel)** → `JourneyPlan(error="Brak trasy w zasięgu")` po wyczerpaniu `max_hops`.
3. **Stacja nie istnieje** → `get_station_id()` zwróci `None` → `JourneyPlan(error="Stacja nie znaleziona")`.
4. **Stacja bez usługi refuel** → `refuel_available = False` → jeśli `fuel_level < min_fuel_reserve`, zwróć `JourneyPlan(error="Brak możliwości tankowania")`.
5. **Dystans skoku > max_hop_distance** → pomijaj taki hop, szukaj alternatywy.
6. **System bez stacji** → `JourneyPlan(error="Brak stacji w systemie")`.
7. **Gwiazda nie jest scoopable** → nie dotyczy (journey planner nie sprawdza scoopable, to jest tylko dla trasy handlowej).

**Kierunek implementacji**:
1. Użyj istniejącego `get_station_id()` do znalezienia ID start/end stacji.
2. Zaimplementuj BFS/A* przez listę stacji z Ardent API dla systemów start i docel.
3. Dla każdego hopa: pobierz system źródłowy (Spansh API) → sprawdź czy ma refuel.
4. Zwróć `JourneyPlan` z listą hopów i informacją o tankowaniu.
5. Dodaj testy: Sol/Columbus → Sol/Columbus (samotankowanie), Sol/Columbus → Sol/Gravnet (1 hop).

---

### KOREKTA punktu 3 (2026-10-13, nadpisuje "Kierunek implementacji" wyżej)
Research Qwena (BFS po stacjach, paliwo w %) odrzucony — nie pasuje do nawigacji skoków.
Zweryfikowane curl-em: Spansh ma gotowy plotter `POST https://spansh.co.uk/api/route`
(form: `from`, `to`, `range`, `efficiency`, opcjonalnie `via`) → `{"job": "<uuid>"}`;
potem polling `GET /api/results/<uuid>` aż `state=completed` (trwa ~10-20 s, tak samo jak
trasa handlowa w `TradeEngine`). `result` ma: `source_system`, `destination_system`,
`distance`, `total_jumps`, `system_jumps[]` z polami `system`, `id64`, `jumps`,
`distance_jumped`, `distance_left`, `neutron_star` (bool), `x/y/z`.
Wersja 1: BEZ logiki paliwa (Spansh jej nie zwraca) — tylko trasa + oznaczenie gwiazd
neutronowych. Tankowanie/scoop to osobny, późniejszy krok.
Sygnatura v1: `plan_journey(start_system, end_system, ship_range, efficiency=60, via=None) -> JourneyPlan`
(`JourneyPlan`: `start_system`, `end_system`, `total_jumps`, `total_distance`, `hops: list[JourneyHop]`, `error: str`;
`JourneyHop`: `system`, `id64`, `jumps`, `distance_jumped`, `distance_left`, `neutron_star`).
Oba dataclassy na poziomie modułu (nie zagnieżdżone). Wzorować się na polling-u w `TradeEngine` (trade.py ~480-560).

**Zrobione (2026-10-13): punkt 3 ZAMKNIĘTY — journey planner v1.**
`TradeEngine.plan_journey(start_system, end_system, ship_range, efficiency=60.0, via=None) -> JourneyPlan`
(+ `JourneyHop`, `JourneyPlan` na poziomie modułu, `_parse_route_result`) w edtrade/trade.py,
oparte o Spansh `POST /api/route` + polling `/api/results/<job>` (timeout 120 s).
Zweryfikowane realnym testem: `plan_journey('Sol','Colonia',30.0)` → 222 hopy, 390 skoków,
~26 500 ly, start=Sol, koniec=Colonia, są gwiazdy neutronowe. Bez logiki paliwa (v1).
Uwagi: implementacja Qwena miała bug parsera (`result` to dict z `system_jumps`, nie lista) —
naprawione ręcznie. `plan_journey` jest metodą klasy, nie funkcją modułową (działa, zostawione).
Następne: punkt 4 (wyszukiwarka materiałów inżynieryjnych) — osobna sesja, research osobno od implementacji.

### 4. Wyszukiwarka materiałów inżynieryjnych — RESEARCH (2026-10-13, zweryfikowane curl-em)
Dwa osobne przypadki użycia, oba przez Spansh (JSON, **synchronicznie** — bez jobów/pollingu):
- **Gdzie handlować materiałami (Material Trader / Technology Broker):**
  `POST https://spansh.co.uk/api/stations/search`, JSON:
  `{"filters":{"services":[{"name":"Material Trader"}],"material_trader":{"value":["Manufactured"]},"distance":{"min":0,"max":50}},"reference_system":"Sol","size":N}`
  (`value`: Raw / Encoded / Manufactured). Wynik `results[]`: `name`, `system_name`, `distance` (ly od ref.),
  `material_trader`, `technology_broker`, `distance_to_arrival`, `large_pads`, `medium_pads`.
- **Gdzie zbierać surowiec (landable body z danym pierwiastkiem):**
  `POST https://spansh.co.uk/api/bodies/search`, JSON:
  `{"filters":{"materials":[{"name":"Antimony","comparison":"<=>","value":[1,100]}],"distance":{"min":0,"max":50}},"reference_system":"Sol","size":N}`.
  Wynik: `count`, `results[]` z `name`, `system_name`, `distance`, `distance_to_arrival`, `is_landable`, `gravity`,
  `materials[]` (`name`, `share` w %), `landmarks[]`. Sensowne filtry: `is_landable`, niska grawitacja, `share` malejąco.
Propozycja v1 (jedna funkcja na przypadek, wzorem `search_stations`): `find_material_traders(reference_system, kind, max_ly, size)`
i `find_material_bodies(reference_system, material, max_ly, min_share, size)`, dataclassy `MaterialTrader`, `MaterialBody`,
błąd sieci → pusta lista (jak `search_stations`). Nie znane jeszcze: dokładne nazwy pól filtra `landable`/`gravity` w bodies/search
(sprawdzić curl-em przed implementacją), mapowanie nazw materiałów gra↔Spansh (polskie/angielskie nazwy — Spansh angielskie).
Następny krok: implementacja ONLY wg tej sekcji (osobna sesja Qwena coder, brief w pliku).

**Zrobione (2026-10-13): punkt 4 ZAMKNIĘTY — wyszukiwarka materiałów v1.**
Funkcje modułowe w edtrade/trade.py: `find_material_traders(reference_system, kind, max_ly=50, size=10)`,
`find_material_bodies(reference_system, material, max_ly=50, min_share=0, max_gravity=0.5, size=10)`,
dataclassy `MaterialTrader`, `MaterialBody`, helper `_spansh_search` (JSON POST, błąd → `[]`).
`find_material_bodies` pobiera 100 wyników i sortuje po `share` lokalnie (Spansh nie sortuje po share).
Test na żywo: traderzy Manufactured wokół Sol (Piercy City, Tryggvason Orbital, Peary Dock);
Antimony ≤0,5 g: 5 G. Capricorni 7 d a (1,28%), Eta Cephei 7 e, Beta Hydri 7 b — malejąco.
Uwaga: implementacja Qwena była niezgodna z API (form-data zamiast JSON, zły format odpowiedzi,
brak filtrów landable/gravity) — przepisana ręcznie; kopia sprzed: /tmp/trade.py.bak-materials.
Następne: punkt 5 (trasy górnicze) — osobno research, osobno implementacja.

### 5. Trasy górnicze — RESEARCH (2026-10-13, zweryfikowane na żywo)
Mining = dwie niezależne połowy, obie przez API które już mamy: **gdzie kopać** (hotspoty w pierścieniach, Spansh) i **gdzie sprzedać** (popyt, Ardent).
- **Hotspoty:** `POST https://spansh.co.uk/api/bodies/search`, JSON:
  `{"filters":{"ring_signals":[{"name":"Platinum","comparison":"<=>","value":[1,100]}],"distance":{"min":0,"max":50}},"reference_system":"Sol","size":N}`
  (`value` = liczba hotspotów danego minerału w pierścieniu; 185 ciał dla Platinum w 50 ly od Sol).
  Wynik: `results[].rings[]` z `name`, `type` (Metallic/Metal Rich/Icy/Rocky), `signals[]` (`name`, `count`), `signals_updated_at`;
  ciało: `name`, `system_name`, `distance`, `distance_to_arrival`. Filtr `ring_signals` zwraca ciała, w których KTÓRYKOLWIEK pierścień ma ten minerał —
  w kodzie trzeba wybrać konkretny pierścień z `signals[].name == mineral` i jego `count`.
- **Popyt (gdzie sprzedać):** `GET https://api.ardent-insight.com/v2/commodity/name/<mineral lowercase>/imports?maxDaysAgo=7&fleetCarriers=0&minVolume=100&systemName=Sol&maxDistance=60`
  (v1 daje 302 → v2; używać `requests` z redirectami lub od razu v2). Wynik: lista z `stationName`, `systemName`, `demand`, `sellPrice`, `meanPrice`,
  `maxLandingPadSize` (1/2/3), `distanceToArrival`, `distance` (ly od systemName), `updatedAt`, `stationType`. Zweryfikowane: platinum → Molina Platform, sellPrice ~302 844.
- **PUŁAPKA:** zapytania do `/api/bodies/search` testowane ręcznym `curl -d` dawały 400 (nginx), a to samo z Pythona `requests.post(json=...)` działa — testuj z Pythona, nie curl-em.
- **Do sprawdzenia przed implementacją:** nazwy wieloczłonowe w Ardent (np. "Low Temperature Diamonds" → czy `lowtemperaturediamonds`), kolejność pól `signals`, czy `value` w ring_signals to count hotspotów.
Plan v1 (osobne funkcje modułowe, wzór `find_material_bodies` + `_spansh_search`, błąd sieci → `[]`):
`find_mining_hotspots(reference_system, mineral, max_ly=50, min_count=1, size=10) -> list[MiningHotspot]` (system_name, body_name, ring_name, ring_type, count, distance, distance_to_arrival, updated_at; sort malejąco po count potem rosnąco po distance_to_arrival),
`find_mineral_buyers(mineral, reference_system, max_ly=60, min_demand=100, max_days=7, size=10) -> list[MineralBuyer]` (station_name, system_name, demand, sell_price, pad_size, distance, distance_to_arrival, updated_at; sort malejąco po sell_price).
Dopiero po v1: `plan_mining_run` łączący oba (najlepszy hotspot + najbliższy dobry kupiec).
Następny krok: implementacja ONLY wg tej sekcji (Qwen coder, brief z DOSŁOWNYM przykładem payloadu i odpowiedzi).
Zweryfikowane (uzupełnienie punktu 5): nazwy towarów w Ardent są nieregularne ("lowtemperaturediamond", "void opal", ale też śmieciowe "low temp. diamonds") —
kanoniczną nazwę wybiera się z `GET https://api.ardent-insight.com/v2/commodities` (lista `{"commodityName": ...}`) po normalizacji
(lowercase, bez znaków nie-alfanumerycznych, bez końcowego "s"): norm("Low Temperature Diamonds") == norm("lowtemperaturediamond"). Ardent daje `demand: 0` dla części stacji → filtrować po stronie klienta.

### Decyzja o interfejsie (2026-10-13, uzgodniona z userem)
Backend v1 punktów 1-5 jest gotowy lub w toku, ale overlay (`overlay.py`) to nadal pasywny pasek z jedną linią (tylko trasa handlowa) — nowe funkcje nie są podpięte.
Kolejność UI: (1) NAJPIERW automaty z dziennika gry — po zdarzeniu (`Docked`, `Location`) pasek sam pokazuje wynik (handlarze materiałów w pobliżu, info o systemie), bez żadnego inputu;
(2) potem rotacja/przełączanie "stron" paska (handel/materiały/mining); (3) na końcu osobne okno z wyszukiwarką poza grą (w grze overlay nie dostaje fokusu — patrz sekcja o ograniczeniach).
Zasada: najpierw dokończyć backend v1 (mining w toku), UI jako osobny krok, jedna rzecz na sesję.

**Zrobione (2026-10-13): punkt 5 v1 ZAMKNIĘTY — wyszukiwarka górnicza.**
Funkcje modułowe w edtrade/trade.py: `find_mining_hotspots(reference_system, mineral, max_ly=50, min_count=1, size=10)` (Spansh `ring_signals`),
`find_mineral_buyers(mineral, reference_system, max_ly=60, min_demand=100, max_days=7, size=10)` (Ardent v2 imports), dataclassy `MiningHotspot`, `MineralBuyer`,
helpery `_ardent_commodity_name`/`_norm_commodity`/`_ardent_commodity_names` (mapowanie nazw ze Spansh/gry na nazwy Ardent przez `/v2/commodities`).
Test na żywo: Platinum wokół Sol — hotspoty Wolf 46 A 4 A Ring (5), Psi Capricorni 1 A Ring (5), Benoit 5 A Ring (4);
kupcy Molina Platform / Nest Of The Avalonian Wayfarer (302 844 cr), Stevenson Landing (302 842); Low Temperature Diamonds (300 ly): Aleksandrov Colony 405 515 cr.
Poprawki po Qwenie: normalizacja nazw nie obcinała końcowego "s" po obu stronach (diamenty → `[]`) i zwracała nazwę z uciętym "s"; zbędny podwójny cache,
błąd sieci cache'owany na stałe (lru_cache); `demand`/`sellPrice` mogą być None. Kopia sprzed poprawek: /tmp/trade.py.bak-mining.
Poza v1: `plan_mining_run` (łączenie hotspotu z kupcem). Backend roadmapy 1-5 gotowy; zostały 6 (kolonizacja) i 7 (lokalna baza cen) oraz UI wg "Decyzji o interfejsie".

**AKTUALIZACJA 2026-10-13: punkt 6 odrzucony przez usera (kolonizacja nieaktualna), punkt 7 (lokalna baza cen) ZROBIONY i integracja z trade.py WSTRZYMANA (patrz niżej w pliku) — szczegóły w sekcjach 6/7 poniżej.**

**Zrobione (2026-10-13): UI krok 1, automaty punktów 1+2 (stacje+system) przy Docked — ZEROWY input, bez bugów.**
`edtrade/overlay.py`: nowy `self.system_info_label` (lewa strona paska, obok nagłówka "ED TRADE"), metody `set_system_info(text)`/`_set_system_info_inner(text)` wzorem `set_polling_status`.
`edtrade/main.py`, `_on_docked`: po `calculate_route_via_spansh` dodany blok try/except wołający `get_system_info(system_id64)` (z `event["SystemAddress"]`) + `search_stations(system)`, wynik złożony w jeden string (`"Sol | Federation | sec:High | 62 stacji"`) i wysłany do `overlay.set_system_info()`.
Sesja Qwena z WĄSKIM promptem (dosłowny kod do wklejenia, 2 pliki, timeout 240s) — **zero bugów**, zweryfikowane end-to-end (instancja Tk + realne wywołanie get_system_info/search_stations dla Sol).
WZORZEC POTWIERDZONY PONOWNIE: wąski, dosłowny prompt > szeroki prompt z opisem zadania — mniej bugów, brak pętli.
Pominięte celowo (brak parametru z eventu Docked): punkty 3 (journey — potrzebuje celu), 4 (materiały — potrzebuje nazwy), 5 (mining — potrzebuje minerału) NIE są automatyzowalne bez dodatkowego inputu (np. plik config z domyślną wartością) — user zdecydował odłożyć to na razie.
Następne: UI krok 2 (rotacja stron paska) albo config dla pkt 3-5, do ustalenia z userem.

**Zrobione (2026-10-13): UI krok 2 — infrastruktura rotacji stron paska.**
`edtrade/overlay.py`: `register_page(name, getter)`, `_rotate_pages()` (co 8s, cykliczne przełączanie `system_info_label` między zarejestrowanymi stronami), `_pages`/`_page_index`/`_system_info_text` w `__init__`. `set_system_info()` teraz rejestruje się jako strona 'system' (przez `register_page`) — gotowe na przyszłe strony materiały/mining gdy dostaną config z parametrem. Tylko `overlay.py` dotknięty, `main.py` bez zmian (kompatybilne API).
Sesja Qwena: dosłowny kod, 1 plik, timeout 180s — bez pętli, bez bugów Qwena. Jeden bug znaleziony przeze mnie (w moim WŁASNYM projekcie kodu, nie Qwena): `_set_system_info_inner` nie wywoływało `system_info_label.config()` natychmiast — tekst widoczny tylko po pierwszej rotacji (do 8s opóźnienia/pusty pasek). Naprawione: dodane `self.system_info_label.config(text=text)` na końcu `_set_system_info_inner`. Zweryfikowane: natychmiastowy update + pełny cykl rotacji 2 stron.
Następne: dodać drugą realną stronę (np. materiały/mining) wymaga configu z parametrem — nieustalone.

**Zrobione (2026-10-13): config.py — domyślne parametry dla pkt 3-5.**
Nowy plik `edtrade/config.py`: JSON config w `~/.config/ed-trade-overlay/config.json`, puste pole = automat wyłączony.
`DEFAULT_CONFIG`: `journey_target_system`, `ship_range_ly=30.0`, `material_kind`, `mining_mineral`.
`load_user_config(path=None)` — tworzy plik domyślny jeśli brak, merge z brakującymi kluczami, fallback na defaultach przy zepsutym JSON.
`save_user_config(config, path=None)`.
Tylko ten jeden plik — sesja Qwena (dosłowny kod, timeout 180s) bez bugów, zweryfikowane 3 testami (brak pliku, partial merge, zepsuty JSON).
Podłączenie configu do `_on_docked` (wołanie `plan_journey`/`find_material_traders`/`find_mining_hotspots` z wartościami z configu) — osobny, nieustalony krok.

**Zrobione (2026-10-13): podłączenie config→_on_docked (pkt 3-5) — ZAMKNIĘTE, zero bugów.**
`edtrade/main.py`: `self.user_config = config.load_user_config()` w `__init__`; w `_on_docked` dodane 3 niezależne bloki try/except (błąd jednego nie blokuje innych):
- journey: jeśli `journey_target_system` ustawiony → `self.trade_engine.plan_journey(system, target, ship_range)` → `overlay.register_page('journey', ...)`.
- materials: jeśli `material_kind` ustawiony → `find_material_traders(system, kind, max_ly=50, size=5)` → strona 'materials'.
- mining: jeśli `mining_mineral` ustawiony → `find_mining_hotspots` + `find_mineral_buyers` → strona 'mining'.
Każdy pusty (domyślnie wyłączony) parametr configu = automat nieaktywny, zero wywołań sieciowych.
Sesja Qwena (dosłowny kod, 1 plik main.py, timeout 200s) — **trzecia sesja z rzędu bez żadnego bugu**. Zweryfikowane realnymi testami (mock overlay+trade_engine dla journey, prawdziwe wywołania find_material_traders/find_mining_hotspots/find_mineral_buyers dla Sol): wszystkie 3 strony rotacji wypełniają się poprawnymi danymi.
**UI/backend wszystkich punktów roadmapy 1-5 i 7(cache) KOMPLETNE i podłączone. Zostaje: realny test w grze (journal na żywo), integracja cache↔trade.py (wstrzymana), ew. UI poza overlayem (osobne okno).**

## BUG ZNALEZIONY I NAPRAWIONY (2026-10-13, test w grze z żywym journalem)
Użytkownik zgłosił: na stacji "bio" overlay sugerował zabranie towaru zamiast dostarczenia, nie trzymało się kupy. Przyczyna (zweryfikowana logiem `/tmp/edto_live.log` + zrzutem ekranu): `TradeRoute.buy_item/buy_price/buy_quantity/sell_price` ("pola legacy", `trade.py` `_parse_spansh_result` ~linia 1082) są ZAWSZE ustawiane z PIERWSZEGO hopu trasy, a `route.destination_system/destination_station` to KOŃCOWA stacja CAŁEJ wieloetapowej trasy (ostatni hop). `overlay.py` `refresh()` łączyło te dwa niepowiązane pola w jednym zdaniu — licznik "Hop X/3" poprawnie rósł (sterowany przez `_on_location` w `main.py`), ale towar/ceny/cel w tekście NIGDY się nie aktualizowały przy zmianie hopu — zawsze pokazywały dane z hopu 1, nawet na hopie 2 czy 3. Efekt: gracz na dalszym etapie trasy widział towar i stację z zupełnie innego (pierwszego) etapu, zmieszane z odległą stacją końcową — stąd wrażenie bezsensownej sugestii.

Naprawione w `edtrade/overlay.py::refresh()`: dodane wyliczenie `current_hop = route.hops_list[hop_num - 1]` (gdy `hops_list` istnieje), z którego brane są `display_dest_system/station/item/qty/buy/sell` zamiast zamrożonych pól legacy; fallback do starych pól `route.*` gdy brak `hops_list` (pojedynczy hop). `cargo_warning` też przełączony na `display_item`.
Zweryfikowane testem symulującym 3-hopową trasę i ręczne przejścia `_current_hop` 1→2→3: każdy hop teraz poprawnie pokazuje WŁASNY cel/towar/ceny (wcześniej: hop 2 i 3 nadal pokazywały dane hopu 1).
To był PRE-ISTNIEJĄCY bug z MVP, nie coś wprowadzone dzisiejszymi sesjami Qwena — naprawiony ręcznie przez Claude'a po realnym zgłoszeniu z gry.

## UI: layout 2-wierszowy (2026-10-13, zgłoszenie z gry — informacje się ucinały)
Jednowierszowy pasek (system+trasa+status w jednej linii) nie mieścił wszystkiego przy pełnej szerokości ekranu — tekst status_label uciekał poza prawą krawędź (widoczne na zrzucie: "...ona" ucięte z "Trasa obliczona").
Nowy layout w `edtrade/overlay.py`: `WINDOW_HEIGHT` 50→90, dwa wiersze (`top_row`: nagłówek+system_info_label+status_label; `hsep` separator poziomy; `bottom_row`: route_label pełna szerokość). Nazwy atrybutów (`header`, `system_info_label`, `route_label`, `status_label`) zachowane identyczne — reszta klasy (set_system_info, update_route, refresh, _rotate_pages) bez zmian.
Sesja Qwena przerwana w połowie (restart `llama-server` ~09:57, prawdopodobnie konflikt VRAM) — zmieniła tylko `WINDOW_HEIGHT`, zostawiła stary jednowierszowy `_build_ui`. DOKOŃCZONE ręcznie przez Claude'a: zastosowany pełny nowy `_build_ui` z promptu. Jeden dodatkowy bug własny (literal-replace usunął też tworzenie `self.frame`, które miało zostać) — naprawiony, dodane z powrotem.
Zweryfikowane pełnym testem: `set_system_info`, `update_route` (z poprawką hop-display), `set_polling_status`, `register_page`+`_rotate_pages` — wszystko działa z nowym layoutem.
**Następny krok (zapowiedziany przez usera):** interfejs docelowo ma być bardziej rozbudowany jak w innych narzędziach handlowych (TCE-style) — do ustalenia układ docelowy (ile wierszy, co gdzie, czy osobne okno). Testowanie w realnej grze uznane za konieczne, nie tylko symulacje.

### 6. Materiały do kolonizacji/budowy — RESEARCH (2026-10-13)
**Stan wiedzy o użytkowniku:** w journalach (56 plików) jest 0 eventów `Colonisation*` — gracz kolonizacji dotąd NIE używał (pamięć 08-19: claim 25 mln CR, outpost ~21 600 t, rozważane Type-9). Przed budową UI trzeba spytać, czy to nadal aktualne.
- **Lista braków (co jeszcze dowieźć) — ŹRÓDŁO: journal, NIEZWERYFIKOWANE lokalnie** (brak próbek). Z dokumentacji journala (do potwierdzenia na pierwszym realnym evencie):
  `ColonisationConstructionDepot` (po dokowaniu w stacji/Depot budowy): `MarketID`, `ConstructionProgress`, `ConstructionComplete`, `ConstructionFailed`,
  `ResourcesRequired[]` z `Name`/`Name_Localised`, `RequiredAmount`, `ProvidedAmount`, `Payment`. Dostawa: `ColonisationContribution`. Watcher już czyta journal na żywo (`watcher.py`) — wystarczy nowy handler eventu.
  Do zbudowania dopiero PO zobaczeniu prawdziwej linii z journala (nie z pamięci modelu): zapisać próbkę do testu.
- **Gdzie kupić brakujący towar — ZWERYFIKOWANE:** `GET https://api.ardent-insight.com/v2/commodity/name/<nazwa>/exports?maxDaysAgo=7&fleetCarriers=0&minVolume=500&systemName=<ref>&maxDistance=<ly>`
  → lista z `stationName`, `systemName`, `stock`, `buyPrice`, `maxLandingPadSize`, `distanceToArrival`, `distance`, `updatedAt`. aluminium/steel/titanium zwracają wyniki (100 stacji ≤40 ly od Sol).
  "cmm composite" i "liquid oxygen" zwróciły 0 — nazwy Ardent trzeba rozwiązać helperem `_ardent_commodity_name` (lista `/v2/commodities`), nie wpisywać ręcznie; odtworzony wzorzec = lustro `find_mineral_buyers`.
- **Propozycja v1 (gdy user potwierdzi, że kolonizuje):** `find_commodity_sellers(commodity, reference_system, max_ly=60, min_stock=500, max_days=7, size=10) -> list[CommoditySeller]`
  (station_name, system_name, stock, buy_price, pad_size, distance, distance_to_arrival, updated_at; sort rosnąco po buy_price), reuse `_ardent_commodity_name`.
  Reszta (parsowanie `ResourcesRequired`, suma ton, liczba kursów dla statku) dopiero po próbce z journala.

### 7. Lokalna baza cen zasilana z journala — RESEARCH (2026-10-13)
**Cel**: Hybryda Spansh (live, szeroki zasięg) + lokalna baza (offline, szybkie powtórne zapytania) zasilana z eventów journala (Market, Docked). Fallback gdy Spansh nie odpowiada lub dane stare.

**1. Format przechowywania**:
- **SQLite** (`~/.local/share/ed-trade-overlay/market_cache.db`) — zero zależności, persists offline, szybkie odczyty, schema z indeksem `(market_id, item_id)`. Wzorowany na Trade Dangerous (używa SQLite do StationItem). Alternatywa JSON per system jest wolniejsza przy wyszukiwaniu.
- Tabela `MarketHistory`: `market_id BIGINT PK, item_id INT, supply_price INT, demand_price INT, supply_units INT, demand_units INT, timestamp DATETIME, market_updated_at DATETIME`. Indeks: `CREATE INDEX idx_market_history ON MarketHistory(market_id, item_id)`.
- Cache nie resetuje się przy rotacji journala — append-only, tylko timestamp decyduje o świeżości.

**2. Pola do zapisu (łączenie Docked + Market)**:
- Market event z journala ma tylko `MarketID`, `StationName`, `StarSystem` — **brakuje cen**.
- Rozwiązanie: **łączyć eventy** — `Docked` dostarcza `MarketID`, następnie eventy `Market` dla tego `MarketID` dostarczają ceny (supply_price, demand_price, supply_units, demand_units).
- Alternatywa: **pobierać ceny live z Ardent API** przy dokowaniu i zapisywać do cache.
- Pola: `market_id` (BIGINT), `item_id` (INT), `supply_price` (INT), `demand_price` (INT), `supply_units` (INT), `demand_units` (INT), `timestamp` (DATETIME), `market_updated_at` (DATETIME), `star_system` (TEXT), `station_name` (TEXT), `station_id` (BIGINT, opcjonalnie).

**3. Współpraca z Spansh/Ardent**:
- **Główna logika**: Spansh API (live) → cache jako fallback.
  - Jeśli Spansh działa → użyj Spansh (najświeższe, cała galaktyka)
  - Jeśli Spansh padnie/timeout → sprawdź cache (dane z ostatnich 24h)
  - Jeśli cache pusty/stary → zwróć "brak danych" z ostrzeżeniem
- **Inne opcje**: Ardent API (dane cenowe) jako źródło cache (pobieraj przy dokowaniu, zapisz w DB).
- Cache ma `max_age_hours=24` — starsze dane ignoruj.

**4. Sygnatury funkcji i lokalizacja**:
- Plik: `edtrade/market_cache.py` (moduł)
- Lokalizacja bazy: `~/.local/share/ed-trade-overlay/market_cache.db`
- Sygnatury:
  ```python
  def init_market_cache(db_path: Path) -> sqlite3.Connection:
      """Inicjalizacja bazy, tworzenie tabeli MarketHistory."""
  
  def record_market_prices(market_id: int, prices: list[dict], timestamp: float) -> None:
      """Zapisz ceny z eventów Market do bazy."""
      prices = [{"item_id": p["item_id"], "supply_price": p["supply_price"], "demand_price": p["demand_price"], "supply_units": p["supply_units"], "demand_units": p["demand_units"]} for p in prices]
  
  def get_cached_prices(market_id: int, max_age_hours: float = 24.0) -> list[dict] | None:
      """Zwóć ceny z cache jeśli świeże (<= max_age_hours), inaczej None."""
  
  def should_use_cache(market_id: int) -> bool:
      """Sprawdź czy cache ma świeże dane (<= 24h)."""
  
  def update_market_cache_from_journal(journal_dir: Path, market_id: int) -> None:
      """Przejdź journal od ostatniego zapisu, zbierz Market events dla market_id."""
  ```

**5. Edge case'y**:
- **Baza pusta**: zwróć `None` + ostrzeżenie "cache pusty, użyj Spansh"
- **Stare dane**: `get_cached_prices()` sprawdza `timestamp < now - max_age_hours`, zwróć `None` jeśli starsze niż 24h
- **Brak pliku Market.json**: watcher już obsługuje brak pliku (zwraca `None`), cache nie inicjalizuje się
- **Brak eventów Market**: cache pozostaje pusta dla danego `market_id`
- **Rotacja journala**: watcher resetuje `_file_pos` przy zmianie pliku, cache nie musi się resetować (data jest tylko append)
- **Duplikaty**: użyj `MAX(timestamp)` przy odczycie — ostatni zapis ma priorytet

**Plan wdrożenia**:
1. Stwórz `edtrade/market_cache.py` z funkcjami wyżej
2. W `watcher.py` dodaj handler `Market` → wywołaj `record_market_prices(market_id, prices)`
3. W `trade.py` zmodyfikuj `calculate_route_via_spansh()`:
   - Sprawdź `get_cached_prices(market_id)` przed requestem do Spansh
   - Jeśli cache świeże → użyj jako fallback (lub warning)
   - Jeśli cache pusty/starszy niż 24h → zapytaj Spansh
4. Dodaj test: symuluj brak Spansh (mock) → sprawdź czy używa cache
5. Zaimplementuj hybrydę: Spansh primary, cache fallback z timeoutem

**Zrobione (2026-10-13): punkt 7 v1 ZAMKNIĘTY — lokalna baza cen bez integracji ze Spansh.**
- `edtrade/market_cache.py`: SQLite cache z tabelą `MarketHistory`, funkcje `init_market_cache`, `record_market_prices`, `get_cached_prices`, `should_use_cache`.
- `watcher.py`: dodany handler `Market` w `_dispatch` oraz `_load_market_json()` wzorem `_load_cargo_json`.
- `update_market_cache_from_journal()` czyta `Market.json` (nie journal) z `journal_dir`, analogicznie do `_load_cargo_json`.
- Market event z journala sygnalizuje tylko, że `Market.json` został zapisany — ceny pobierane z pliku.
- Py_compile: OK. Test functionalny na tymczasowej bazie: `init_market_cache + record_market_prices + get_cached_prices` działa poprawnie.

**KOREKTA (2026-10-13, po weryfikacji ręcznej) — Qwen zgłosił "test działa poprawnie", ale miał 3 realne bugi niewykryte przez py_compile:**
1. Brak `import json` w `market_cache.py` — `_load_market_json`/`update_market_cache_from_journal` wywalały `NameError` przy realnym pliku.
2. `market_id BIGINT PRIMARY KEY` (bez `item_id`) — `INSERT OR REPLACE` nadpisywał wszystkie towary poza ostatnim. Naprawione na `PRIMARY KEY (market_id, item_id)`.
3. `conn` niezdefiniowany w `update_market_cache_from_journal` — funkcja wołała `record_market_prices(conn, ...)` bez przyjęcia `conn` jako parametru. Dodany parametr.
Wszystkie 3 naprawione ręcznie i zweryfikowane testem (2 towary w cache, ścieżka przez prawdziwy `Market.json`).

**Zrobione (2026-10-13): podłączenie watcher→cache w main.py (sesja z węższym promptem + timeout 180s, zero pętli).**
`App.__init__`: `self._market_conn = init_market_cache(...)`, `on_market=self._on_market` przekazane do `JournalWatcher`.
`App._on_market(event)`: woła `market_cache.update_market_cache_from_journal(self._market_conn, self.watcher.journal_dir, event.get("MarketID"), ...)` w try/except.
Bug znaleziony i naprawiony ręcznie: zaimportowana była tylko funkcja `init_market_cache`, nie moduł `market_cache` — wywołanie `market_cache.update_market_cache_from_journal(...)` dawałoby `NameError`. Dodane `from . import market_cache`. Zweryfikowane testem identycznym do wywołania w `_on_market`.
**Całość: event Market z journala → Market.json → SQLite cache, zweryfikowana end-to-end. Integracja jako fallback w `calculate_route_via_spansh` (trade.py) NIE zrobiona — osobny krok.**

**DECYZJA (2026-10-13): integracja cache↔trade.py WSTRZYMANA, nie podejmować bez nowego ustalenia.**
Problem architektoniczny: `calculate_route_via_spansh` liczy pełną trasę multi-hop (wymaga cen z całej galaktyki przez Spansh), a lokalny cache ma tylko ceny ze stacji gdzie gracz faktycznie dokował — nie da się z niego odtworzyć pełnej trasy, tylko pokazać ceny lokalne jednej stacji jako degradowany fallback. User wybrał "poczekać" zamiast decydować teraz o zakresie (pokazywać lokalne ceny przy błędzie Spansh vs tylko log/diagnostyka). Cache zostaje samodzielnym, gotowym modułem bez podłączenia do przepływu tras.

## UI: osobny panel TCE-style (2026-10-13 wieczór) — zwykłe okno, Alt-Tab działa
**Architektura ustalona z userem**: 2 okna. (1) Cienki pasek w grze (`overlay.py`) zostaje bez zmian — `overrideredirect`+splash+topmost, bez fokusu, Alt-Tab go nie widzi (świadomy kompromis, nie da się mieć obu naraz w jednym oknie). (2) NOWY, osobny `edtrade/panel.py` — zwykłe okno (`tk.Toplevel`), widoczne w Alt-Tab, zakładki: Trasa/System/Materiały/Mining/Journey/Ustawienia.

**Ustalenie techniczne (zweryfikowane realnym testem) — wykrywanie fokusu "pasek zawsze nad grą":**
`xdotool`/`_NET_ACTIVE_WINDOW` NIE DZIAŁA na tym KWin/Wayland (zawsze zwraca fikcyjny placeholder `0x200000` bez nazwy/klasy/PID, niezależnie które okno XWayland aktywowano). Zainstalowany `kdotool` (AUR, `yay -S kdotool`, instalacja pakietu `sudo pacman -U` wymagała ręcznego uruchomienia przez usera z powodu braku terminala na hasło w tym środowisku) — **działa poprawnie**, używa KWin scripting D-Bus API zamiast X11. Potwierdzone: `kdotool getactivewindow`+`getwindowclassname` poprawnie rozpoznało WezTerm jako aktywne okno. `kdotool windowstate --add above` (KDE 6) dostępne do dynamicznego ustawiania "zawsze na wierzchu" konkretnego okna. Będzie użyte w kroku 3 (polling fokusu co ~0.5-1s), gdy złapiemy `classname` okna Elite Dangerous po uruchomieniu gry.

**Plan budowy panelu (bardzo małe batche Qwena, jeden plik/krok na raz — user explicite poprosił o maksymalne rozdrobnienie):**
1. Szkielet okna + 1 pusta zakładka — ZROBIONE (patrz niżej).
2. Reszta zakładek (Materiały/Mining/Journey/Ustawienia) z realnymi danymi.
3. Polling "nad grą" przez kdotool (wymaga złapania classname gry).
4. Wire main.py (uruchomienie panelu obok overlaya).

**Zrobione (batch 1): szkielet `edtrade/panel.py`.**
Klasa `TradePanel(master)`: `tk.Toplevel`, `ttk.Notebook`, 1 zakładka "System" z placeholderem, `show()`/`hide()`. Zwykłe okno — zweryfikowane: `-topmost 0`, `-type ''`, brak `overrideredirect` → Alt-Tab będzie działać.
Sesja Qwena: PIERWSZA próba przerwana w połowie przez restart `llama-server` (konflikt VRAM, drugi taki przypadek dzisiaj — zero realnej pracy wykonanej, tylko wypisany plan). Druga próba (ten sam prompt, po ustabilizowaniu modelu) — **sukces, kod identyczny bajt-w-bajt z promptem**, zero bugów. Zweryfikowane pełnym testem: tytuł, geometria, zakładka, placeholder, show()/hide(), atrybuty okna.
**LEKCJA:** jeśli sesja Qwena kończy się podejrzanie szybko z samym "planem" bez realnych wywołań narzędzi — sprawdź czy `llama-server` się nie zrestartował w tym czasie (konflikt VRAM z innym procesem), zanim założysz że to błąd Qwena. Prosty fix: powtórz dokładnie ten sam prompt.

**Zrobione (batch 2): zakładka System z realnymi danymi.**
`edtrade/panel.py`: `system_entry_var`/`system_entry`/`system_refresh_btn` (Entry+Button), `system_info_text` (tk.Text, readonly po wypełnieniu), metoda `refresh_system_tab()` wołająca `search_stations(system_name)` i wypisująca listę stacji (nazwa/pad_size/distance_to_arrival). Import `get_system_info` dodany ale celowo nieużywany jeszcze (wymaga `system_id64`, nie nazwy — potrzebny osobny krok wyszukiwania ID).
Sesja Qwena: zero bugów, dosłowny kod zgodny z promptem. Zweryfikowane realnym wywołaniem `refresh_system_tab()` z 'Sol' → 62 stacje poprawnie wylistowane, widget poprawnie `disabled` po wypełnieniu.

**Zrobione (batch 3): zakładka Materiały.**
Druga zakładka w notebooku: Entry (system) + Combobox readonly (Raw/Encoded/Manufactured) + Button + Text. Metoda `refresh_materials_tab()` woła `find_material_traders(system_name, kind, max_ly=50, size=10)`.
Zero bugów, dosłowny kod. Zweryfikowane: `refresh_materials_tab()` z 'Sol'/'Manufactured' → 10 traderów poprawnie wylistowanych (Piercy City, Tryggvason Orbital, itd.), 2 zakładki widoczne w notebooku.

**Zrobione (batch 4): zakładka Mining.**
Trzecia zakładka: Entry (system) + Entry (minerał) + Button + Text. `refresh_mining_tab()` woła `find_mining_hotspots` + `find_mineral_buyers`, wypisuje oba razem.
Zero bugów. Zweryfikowane: 'Sol'/'Platinum' → 5 hotspotów (Wolf 46 A 4, Psi Capricorni 1 itd.) + 5 kupców (Molina Platform 302,844cr itd.), 3 zakładki widoczne.

**Zrobione (batch 5): zakładka Journey.**
Czwarta zakładka: Entry (start/cel/zasięg) + Button + Text. Panel ma teraz własny `self.trade_engine = TradeEngine()` (domyślne argumenty, samodzielny). `refresh_journey_tab()` woła `self.trade_engine.plan_journey(start, end, ship_range)`, z walidacją zasięgu (ValueError → komunikat błędu bez wołania sieci).
Zero bugów. Zweryfikowane: struktura (4 zakładki), walidacja błędnego zasięgu (bez sieci), PEŁNY test z realnym Spansh (Sol→Colonia, 30 ly zasięg) → 390 skoków, 26511.1 ly, lista hopów z oznaczeniem gwiazd neutronowych poprawnie wyświetlona.
**Panel TCE ma teraz 5 batchów z rzędu BEZ ŻADNEGO BUGA (szkielet + System + Materiały + Mining + Journey). Zostaje: zakładka Ustawienia (config.json GUI), wire main.py, polling "nad grą" (kdotool).**


**Zrobione (2026-10-13): punkt 6 v1 — `find_commodity_sellers` (Ardent `/exports`), dataclass `CommoditySeller`.** Kod Qwena poprawny.
Poprawka MOJA we wspólnym helperze `_ardent_commodity_name`: Ardent ma duplikaty ("cmm composite" puste vs "cmmcomposite" z danymi, tak samo "liquid oxygen"/"liquidoxygen") —
helper preferuje wariant bez spacji, inaczej pierwszy pasujący. Test: CMM Composite → Plaskoziemcy 4377 cr, Thorn Industrial 4394 cr.
Kolonizacja ZAPARKOWANA decyzją usera (2026-10-13): parsowanie `ResourcesRequired` z journala wymaga próbki z gry; zakładka "Kolonizacja" w panelu — później. Teraz: UI (panel TCE).

**UI krok 1 ZROBIONY (2026-10-13 11:07):** `TradePanel` podpięty w `main.py` (import, arg `--no-panel`, tworzenie po `self.overlay`). Implementacja Qwena, diff = dokładnie 3 zmiany; test z GUI
(`DISPLAY=:0` + `XAUTHORITY` z `/proc/<plasmashell>/environ`) → "TradePanel utworzony", zero Traceback. UWAGA testowa: powłoka narzędzi nie ma DISPLAY — Qwen sam GUI nie przetestuje, test c) robi Claude.
Następne kroki UI: (2) zakładka Ustawienia (edycja user config), (3) polling "nad grą" kdotool, (4) zakładka Kolonizacja dopiero po zdjęciu parkingu pkt 6.

**UI krok 2 ZROBIONY (2026-10-13 11:25): zakładka Ustawienia w panelu** (`panel.py`: Entry/Combobox z `user_config`, `save_settings()` zmienia słownik IN-PLACE + zapis do pliku; `main.py`: `user_config` ładowany przed overlayem i przekazywany do `TradePanel`).
Przebieg (implementacja Qwena, 3 iteracje): v1 skasowała blok `init_market_cache` w main.py i inicjowała pola na sztywno (zapis nadpisałby config pustymi wartościami) — wyłapane DIFFEM; v2 naprawiła oba, ale układ `pack(side=LEFT)` ucinał 4 ostatnie widgety
do 1 px (przycisk Zapisz niewidoczny, `mapped=0`) — wyłapane POMIAREM `winfo_ismapped/width`; test Qwena sprawdzał tylko lewą krawędź przycisku; v3 = `grid`, zmierzone: wszystkie widgety mapped, przycisk 101 px.
LEKCJA: test GUI musi mierzyć `winfo_ismapped()` i `winfo_width()`, nie samą pozycję. Powłoka narzędzi nie ma DISPLAY (ustawiać z /proc/<plasmashell>/environ).

### UI krok 3 — polling "nad grą" (kdotool) — BADANIE (2026-10-13 11:30)
- `kdotool` (/usr/bin/kdotool) DZIAŁA na tym KWin Plasma 6/Wayland, ale WYMAGA zmiennych sesji KDE: bez `KDE_SESSION_VERSION=6` zwraca "Unsupported KDE version". Zmienne (`KDE_SESSION_VERSION`, `XDG_CURRENT_DESKTOP=KDE`, `KDE_FULL_SESSION=true`, `DBUS_SESSION_BUS_ADDRESS`, `DISPLAY`, `WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR`)
  overlay dziedziczy po starcie z pulpitu/launchera; w powłoce narzędzi trzeba je brać z `/proc/<plasmashell>/environ`.
- Zweryfikowane komendy: `kdotool getactivewindow` → `{uuid}`; `kdotool getwindowclassname <uuid>` → np. `org.wezfurlong.wezterm`; `kdotool getwindowname <uuid>` → tytuł; `kdotool getwindowpid <uuid>`; `kdotool search --name '.'` listuje okna.
- NIEZNANE: classname okna Elite Dangerous (gra nie była uruchomiona podczas badania). Prawdopodobnie `steam_app_359320` (appid ED) — NIEZWERYFIKOWANE. Plan: klucz configu `game_window_class` + logowanie każdej zmiany aktywnej klasy na INFO, żeby przy pierwszym uruchomieniu z grą odczytać prawdziwą wartość z logu.
Podział na małe kroki (Qwen, po jednym): (A) `edtrade/window_watch.py` z funkcją `get_active_window()` → `(class, title)` albo `None`; (B) pętla pollingu `after(1000)` w overlayu/panelu + log zmian klasy; (C) klucz configu `game_window_class` + pole w zakładce Ustawienia; (D) zachowanie (pokaż/ukryj pasek wg tego, czy gra ma fokus) — DECYZJA USERA co ma się dziać.

**UI krok 3A ZROBIONY (2026-10-13 11:30):** `edtrade/window_watch.py` — `get_active_window() -> Optional[tuple[str, str]]` (kdotool: `getactivewindow` → `getwindowclassname` + `getwindowname`; błąd/brak środowiska KDE → `None`, bez wyjątku). Kod Qwena zgodny z briefem bajt-w-bajt, zero regresji (main.py identyczny, inne pliki nietknięte). Test: z env → `('org.wezfurlong.wezterm', <tytuł>)`, bez env → `None`.
Następny: 3B — pętla pollingu `overlay.master.after(1000)` logująca ZMIANĘ aktywnej klasy na INFO (bez show/hide).

**UI krok 3B ZROBIONY (2026-10-13 11:36):** `main.py` — `_poll_active_window()` (co 1000 ms przez `overlay.master.after`, start przed `overlay.show()`), loguje na INFO TYLKO zmianę klasy aktywnego okna (`Aktywne okno: class=...`), bez tytułów (prywatność). Diff Qwena = same dodane linie (import, `Optional`, pole, metoda, `after`), `_market_conn`/`user_config` nietknięte. Test z GUI: "TradePanel utworzony" + `Aktywne okno: class='Toplevel'` (okno panelu), brak Traceback.
Uwaga: wywołania `kdotool` idą w głównym wątku Tk (do 3 s przy timeoucie) — jeśli overlay zacznie przycinać, przenieść do wątku.
Następne: 3C (klucz configu `game_window_class` + pole w Ustawieniach), 3D (zachowanie paska/panelu wg fokusu gry — czeka na decyzję usera).

**DECYZJA 3D (user, 2026-10-13 11:38): pasek widoczny TYLKO gdy gra jest aktywnym oknem; panel TCE zawsze dostępny (zwykłe okno, Alt-Tab).**
Zabezpieczenie: klasa okna gry jest niezweryfikowana (zgadnięte `steam_app_359320`), więc zachowanie za flagą configu `bar_only_when_game_focused` (domyślnie `False`) — user włącza ją po odczytaniu prawdziwej klasy z logu ("Aktywne okno: class=" gdy gra ma fokus). Inaczej błędna klasa = pasek znikałby na stałe.
Kroki (każdy osobny brief Qwena, jeden plik): 3C-1 config.py `game_window_class` (w toku) → 3C-2 config.py `bar_only_when_game_focused` → 3C-3 panel.py: 2 pola w Ustawieniach → 3D main.py: w `_poll_active_window` pokaż/ukryj pasek (`overlay.master.withdraw()/deiconify()`) wg flagi i klasy; okna panelu nie ruszać.

**UI krok 3C-1 ZROBIONY (2026-10-13 12:33):** `config.py` — `DEFAULT_CONFIG['game_window_class'] = 'steam_app_359320'` (niezweryfikowane) + zdanie w docstringu; stary plik configu dostaje klucz przez merge, nowy zapisuje 5 kluczy; prawdziwy `~/.config/ed-trade-overlay/config.json` nietknięty (md5 bez zmian). Qwen zostawił zbędny `config.py.bak-DATA` w edtrade/ (usunięty) — w briefach zakaz tworzenia plików poza wskazanymi.

**UI krok 3C-2 ZROBIONY (2026-10-13 12:36):** `config.py` — `DEFAULT_CONFIG['bar_only_when_game_focused'] = False` + linia w docstringu; diff = dokładnie 2 dodane linie, brak plików .bak, prawdziwy config nietknięty; stary plik dostaje 6. klucz przez merge, nowy zapisuje 6 kluczy.

**UI krok 3C-3 ZROBIONY (2026-10-13 12:42):** `panel.py` — w Ustawieniach pole 'Klasa okna gry' (Entry ← `game_window_class`) i Checkbutton 'Pasek tylko gdy gra ma fokus' (← `bar_only_when_game_focused`), przycisk Zapisz → wiersz 6, status → 7, `save_settings()` zapisuje 2 nowe klucze in-place + do pliku. Diff Qwena = dokładnie zakres z briefu. Pomiar: 13 widgetów mapped=1, przycisk 101 px; test Qwena pokazał ismapped=0 (nie zbadał widoczności) — własny pomiar potwierdził OK.

**BADANIE 3D (2026-10-13 12:45):** `overlay.master.withdraw()` chowa TYLKO pasek; Toplevel panelu zostaje widoczny — zmierzone w Tk (`winfo_ismapped`: root 1→0→1, panel zawsze 1, alpha 0.75 zachowana po deiconify) i w KWin (`kdotool search`: widoczny wyłącznie panel w stanach przed/po withdraw — pasek `overrideredirect` nie jest w ogóle zarządzany przez KWin). Wariant 3D = withdraw()/deiconify() paska. Zabezpieczenia: `window_class is None` (kdotool zawiódł) → NIE zmieniaj widoczności; wyłączenie flagi w trakcie → przywróć pasek.

**UI krok 3D ZROBIONY (2026-10-13 12:55): tryb "pasek tylko przy grze".** `main.py` — `_bar_visible`, `_apply_bar_visibility(window_class)` (wołana co sekundę z `_poll_active_window`): przy `bar_only_when_game_focused=True` pasek (`overlay.master`) jest `withdraw()`/`deiconify()` wg tego, czy aktywna klasa == `game_window_class`;
`window_class is None` (kdotool zawiódł) → bez zmiany; pusta klasa gry → pasek ukryty; wyłączenie flagi → pasek wraca. Panel nietknięty.
Weryfikacja: 9 scenariuszy na mocku zgodne; e2e na prawdziwym GUI (aplikacja, config zmieniany tylko w pamięci): zła klasa → bar_mapped=0 / panel_mapped=1, klasa aktywna → bar 1, flaga OFF → bar 1; prawdziwy config.json nietknięty.
Poprawka Claude (1 linia): Qwen dał wywołanie `_apply_bar_visibility` WEWNĄTRZ `if window_class != _last_active_class` (brief: poza nim) — przez to wyłączenie flagi w panelu nie przywracało paska bez zmiany okna; wcięcie poprawione.
**JAK WŁĄCZYĆ:** uruchom grę, odczytaj z logu (`/tmp/edto_live.log`) linię `Aktywne okno: class='...'` gdy gra ma fokus, wpisz tę klasę w panelu → Ustawienia → "Klasa okna gry", zaznacz "Pasek tylko gdy gra ma fokus", Zapisz (działa od razu, bez restartu).
Stan UI: panel TCE (System/Materiały/Mining/Journey/Ustawienia) podpięty w main.py (`--no-panel` wyłącza); zostają: zakładka Kolonizacja (pkt 6 zaparkowany), ewentualne wyłączenie polling-u gdy kdotool niedostępny.

**UI 4A ZROBIONE (2026-10-13 13:08):** `panel.py` — `self.window.protocol('WM_DELETE_WINDOW', self.window.iconify)`: X minimalizuje panel (stan normal→iconic→normal, okno nie niszczone). Qwen wstawił te 2 linie z TABULATORAMI (TabError, panel nie startował) i z uszkodzonym znakiem w komentarzu, po czym wyczerpał limit kroków — wcięcia poprawione ręcznie (2 linie). LEKCJA: po każdym kroku Qwena `py_compile` + `grep -c $'\t'` (tabulatory), bo jego deklaracje o sukcesie nie są dowodem.

**UI 4B ZROBIONE (2026-10-13 13:20): Journey w wątku roboczym.** `panel.py` — `journey_calc_btn`, `_set_journey_text`, `refresh_journey_tab` (walidacja w wątku Tk → `threading.Thread(daemon=True)` → `_journey_worker` → `window.after(0, _journey_done, tekst)`), przycisk disabled na czas liczenia. Kod Qwena zgodny z briefem, zero tabulatorów, diff bez zbędnych zmian (Qwen sam testu GUI nie uruchomił).
Pomiar w prawdziwym `mainloop`: `refresh` wraca po 0.0 s, 110 tyknięć UI w 10.6 s liczenia, 'Skoki: 390 | Dystans: 26511.1 ly', zły zasięg → błąd + przycisk normal.
PUŁAPKA TESTOWA: wywołanie `after()` z wątku roboczego działa TYLKO gdy główny wątek jest w `mainloop()`; pętla `root.update()` w teście → RuntimeError "main thread is not in main loop" (połknięty przez `except: pass`) i wynik nie dociera. Testy wątków robić przez `root.after(...)` + `root.mainloop()` + `root.quit()`.
Kolejność dalej: 4C Materiały, 4D System, 4E Mining (ten sam wzorzec).

**UI 4C ZROBIONE (2026-10-13 13:21): Materiały w wątku roboczym.** `panel.py` — `materials_btn`, `_set_materials_text`, `refresh_materials_tab` → `_materials_worker` → `window.after(0, _materials_done, tekst)`. Diff czysty, zero tabulatorów (Qwen znów nie uruchomił testu GUI). Pomiar w mainloop: refresh 0.0 s, wynik po 0.5 s ('Handlarze (10):'), przycisk normal.

**UI 4D ZROBIONE (2026-10-13 13:25): System w wątku roboczym.** `panel.py` — `_set_system_text`, `refresh_system_tab` → `_system_worker` → `window.after(0, _system_done, tekst)`; `system_refresh_btn` (istniejący) blokowany na czas pracy. Diff czysty, zero tabulatorów. Pomiar w mainloop: refresh 0.0 s, 'Stacje (62):' po 0.2 s, przycisk normal.

**BUG ZNALEZIONY (2026-10-13 13:28): kolizja nazwy `mining_mineral_var`** — zakładka Mining i zakładka Ustawienia definiują ten sam atrybut; druga definicja (Ustawienia, wartość z configu) nadpisuje pierwszą, stary `StringVar` jest zwalniany → pole minerału w Mining puste, `refresh_mining_tab` czyta pusty `mining_mineral_var` i po cichu wraca (nic się nie dzieje po "Odśwież"). Powstał przy kroku 3C (nazwa z oryginału Ustawień zdublowana z Mining). Naprawa w kroku 4E: zmienna zakładki Mining → `mining_tab_mineral_var`.

**UI 4E ZROBIONE (2026-10-13 13:31): Mining w wątku roboczym + naprawiona kolizja `mining_mineral_var`.** `panel.py` — zakładka Mining używa `mining_tab_mineral_var` i `mining_btn`; `_set_mining_text`, `refresh_mining_tab` → `_mining_worker` (hotspoty + kupcy w jednym wątku) → `window.after(0, _mining_done, tekst)`. Ustawienia/`save_settings` nietknięte (`mining_mineral_var`).
Pomiar w mainloop: pole Mining 'Platinum' ≠ pole Ustawień '' (różne obiekty), refresh 0.0 s, wynik po 2.9 s ('Hotspoty (5):', 'Kupcy (5):'), przycisk normal, zapis Ustawień → cfg i plik 'Painite', pole Mining bez zmian; prawdziwy config.json nietknięty.
**KRYTYCZNE — zakładka Mining miała od kroku 3C puste pole minerału i martwy przycisk "Odśwież"** (kolizja nazwy z Ustawieniami); wcześniejsze testy 3C-3 nie dotykały Mining, więc nie wyłapały.
**PODSUMOWANIE UI 4A-4E:** X panelu = minimalizacja (4A); wszystkie 4 zakładki z siecią (Journey, Materiały, System, Mining) liczą w wątku roboczym, UI i pasek nie zamarzają (4B-4E); naprawiona kolizja zmiennej Mining.
Zostaje: zakładka Kolonizacja (pkt 6, zaparkowana), test w grze + odczyt prawdziwej klasy okna gry, ewentualnie `kdotool` w wątku (jeśli pasek będzie się przycinał), obsługa `after()` na zamkniętym oknie (połknięty wyjątek w workerach).

## Porządki (2026-10-13, przegląd Claude'a reszty projektu)
Przegląd całego repo na życzenie usera ("sprawdź resztę projektu, co jeszcze do zrobienia") wykrył i naprawił 3 realne bugi w `edtrade/trade.py::_parse_output` (tekstowy parser lokalnego Trade Dangerous — ścieżka zapasowa, OBECNIE nieużywana, bo backend to Spansh, ale test ją pokrywa i bug był realny):
1. Regex `Buy`/`Sell` wymagał cyfry bezpośrednio przed `)` — ceny z sufiksem `cr` (np. `130cr)`) nigdy się nie parsowały, `buy_item`/`sell_price` zawsze zostawały puste/zerowe.
2. `buy_price` było czytane z `m.group(3)` (nazwa stacji!) zamiast `m.group(4)` (cena) — po naprawie (1) powyższy bug by się ujawnił jako `ValueError` przy `int()` na nazwie stacji.
3. Regex zysku nie dopuszczał znaku `-` — strata (np. `profit -20cr`) zapisywała się jako `0`.
Wszystkie 3 naprawione, `test_trade.py::TestParseOutput` (4 testy) teraz przechodzi w całości (wcześniej 3/4 fail). `test_search_sol` pomijany w tym kontenerze — blokada proxy do zewnętrznego API, nie bug w kodzie.
Dodatkowo: `requirements.txt` mówił "brak zależności, tylko stdlib", ale `trade.py` realnie importuje `requests` — naprawione (`requests` dodane do pliku), bo świeży `pip install -r requirements.txt` kończyłby się `ModuleNotFoundError` przy pierwszym wywołaniu Spansh/Ardent.
Niezmienione (poza zakresem tej sesji, wymaga decyzji/testu w grze — patrz wyżej): zakładka Kolonizacja, weryfikacja `game_window_class`, fallback lokalnego TD (brak `sqlalchemy`), integracja cache↔trade.py (świadomie wstrzymana).

## Analiza konkurencji (2026-10-13, research Claude'a) — czego jeszcze NIE ma ten projekt, a mają inne narzędzia ED

Cel: przegląd innych narzędzi handlowych/towarzyszących Elite Dangerous (nie do skopiowania 1:1 — do wyciągnięcia pomysłów na funkcje, tak jak wcześniej z TCE) i zsyntetyzowanie tego w konkretne, kolejne punkty roadmapy. Źródła: strony/repo projektów, fora Frontier, wiki — linki przy każdym punkcie.

### Przegląd narzędzi
- **Trade Dangerous (TD)** ([bitbucket wiki](https://bitbucket.org/kfsone/tradedangerous/wiki/User_Guide/), [GitHub fork eyeonus](https://github.com/eyeonus/Trade-Dangerous)) — nasz dotychczasowy lokalny backend (teraz nieużywany, Spansh go zastąpił). Komendy, które mamy tylko częściowo lub wcale: `nav` (trasa A→B po systemach, nie licząc handlu — my mamy `plan_journey` przez Spansh, podobne), `market` (**pełna lista** kupna/sprzedaży na DANEJ stacji — my pokazujemy tylko 1 towar z obliczonej trasy, nie cały market danej stacji), `buy`/`sell` (gdzie kupić/sprzedać KONKRETNY towar w zasięgu stacji — mamy to tylko dla materiałów/minerałów, nie dla zwykłych commodities), **checklist mode** (krok po kroku prowadzi przez trasę, potwierdzasz każdy etap) — blisko naszego mechanizmu `_current_hop`, tylko bez potwierdzeń, **`--ls-penalty`** (faworyzuje stacje bliżej gwiazdy w systemie / krótszy supercruise, nie tylko najkrótszy dystans międzygwiezdny w ly) — nasz `calculate_route_via_spansh` tego nie uwzględnia.
- **EDDiscovery** ([forum release notes](https://forums.frontier.co.uk/threads/eddiscovery-19-x-is-out-lynx-highlander-kestrel-ed-canonn-plugin-squadron-panel-colonisation-panel-and-engineering-ship-views.329643/)) — ponad 50 paneli, overlay transparentny nad borderless-oknem gry (podobne do naszego `overlay.py`), panel stacji ze Spansh z wyszukiwaniem **po całej galaktyce wg commodities/outfitting/economy** (nasz `find_material_traders`/`find_mining_hotspots` jest podobny, ale ograniczony do materiałów/minerałów, nie zwykłych commodities), **panel Kolonizacji** dodany w wersji 19.x (realna implementacja referencyjna, przydatna gdyby odmrozić nasz zaparkowany punkt 6), integracje EDSM/EDDN/Spansh/Inara/EDAstro.
- **Inara.cz** — community agregator cen (dane z EDDN, czyli z raportów EDMC innych graczy). Ważna lekcja: rozróżnienie **Import (stacja KUPUJE od ciebie) vs Export (stacja SPRZEDAJE tobie) price** — częsty błąd userów Inary; u nas `buy_price`/`sell_price` w `TradeRoute`/`MineralBuyer`/`CommoditySeller` powinny być raz jeszcze zweryfikowane czy nazwy jednoznacznie odpowiadają kierunkowi transakcji (do przeglądu, nie potwierdzony bug — tylko ostrzeżenie z doświadczenia community). Druga lekcja: pokazywanie **wieku danych** i ostrzeżenie gdy >8h — u nas `market_cache` ma `max_age_hours`, ale nowe strony (materiały/mining/journey) nie pokazują wieku danych wynikowych w overlayu.
- **EDCT (Elite Dangerous Commodity Trader)** ([GitHub Fi0x/EDCT](https://github.com/Fi0x/EDCT)) — GUI z filtrem profit/tonę, dystans, supply/demand na stacji, filtr "tylko large pad", filtr "tylko fleet carrier", wsparcie stacji Odyssey. Projekt sam zgłasza się jako przestarzały (API się zmieniło) — potwierdza, że nasze podejście (Spansh/Ardent live) jest trwalsze niż własny scraping.
- **EDEngineer** (wspominany jako towarzysz EDMC) — **inny kąt niż nasz `find_material_traders`**: nie szuka GDZIE kupić materiał, tylko śledzi CO GRACZ MA (z eventu journala `Materials`) i porównuje z wymaganiami blueprintów inżynieryjnych, pokazując czego brakuje. To realna dziura w naszym projekcie — mamy "gdzie znaleźć X", nie mamy "czego mi brakuje do planowanego ulepszenia".
- **EDFC (Fleet Carrier Calculator)** — kalkulator kosztów utrzymania carriera (załoga, paliwo tritium, usługi) vs przychód z prowizji handlowej. Niszowe — tylko dla właścicieli carrierów — ale handel na carrierze to inna ekonomia niż handel stacja-stacja (gracz ustala własne ceny kupna/sprzedaży), zupełnie nieobsłużona przez nasz projekt.
- **ICARUS Terminal** ([GitHub iaincollins/icarus](https://github.com/iaincollins/icarus)) — architektonicznie inny pomysł niż overlay: **lokalny serwer web + UI w przeglądarce na DRUGIM urządzeniu** (telefon/tablet/drugi monitor), zamiast okna nad grą. To całkowicie obchodzi nasz problem "overlay nie dostaje fokusu / nie widać w exclusive fullscreen" (patrz sekcja "Renderowanie overlaya" na początku pliku) — nie trzeba kompozytora, nie trzeba kdotool. Warte rozważenia jako alternatywna/dodatkowa architektura UI, nie zamiennik obecnego paska.

### Synteza — nowe punkty roadmapy (do ustalenia z userem przed implementacją, każdy osobny research→brief→implementacja jak dotychczas)

**8. Tracker materiałów inżynieryjnych gracza (wzór EDEngineer)** — inny kąt niż istniejący punkt 4 (`find_material_traders` = gdzie kupić). Nowy: czytać event journala `Materials` (stan posiadanych Raw/Manufactured/Encoded), opcjonalnie `EngineerProgress`/bazę blueprintów, i pokazywać "czego brakuje do X". Wymaga: próbki eventu `Materials` z realnego journala (podobnie jak przy koloniach — nie zgadywać struktury), decyzji czy wymagania blueprintów trzymać w pliku statycznym (lista inżynieryjna ED zmienia się rzadko) czy pobierać skądś.

**9. Generyczny finder commodity + pełny market stacji (wzór TD `market`/`buy`/`sell`)** — rozszerzenie `find_mineral_buyers`/`find_commodity_sellers` (teraz tylko dla minerałów/materiałów kolonizacji) na DOWOLNĄ commodity z gry + nowa funkcja pokazująca cały market (lista kupna/sprzedaży) danej stacji, nie tylko jeden towar z obliczonej trasy. Ardent już ma dane dla dowolnej commodity (`_ardent_commodity_names` już to obsługuje) — głównie kwestia UI (nowa zakładka w panelu z wolnym polem na nazwę towaru) + ew. endpoint pełnego marketu stacji.

**10. Checklist mode dla trasy (wzór TD) — potwierdzanie etapu** — nasz `_current_hop` już awansuje automatycznie po evencie `Location`; checklist TD dodaje wymóg jawnego potwierdzenia (przycisk/klawisz) zamiast czysto automatycznego — do rozważenia jako opcja configu, nie zamiana obecnego zachowania (auto-advance działa dobrze, to tylko alternatywny tryb).

**11. Fleet Carrier — ekonomia carriera (wzór EDFC)** — osobna, niszowa funkcja: śledzenie kosztów utrzymania (`CarrierStats`/`CarrierFinance` z journala) vs przychodu z handlu na carrierze (gracz ustala własne ceny). Priorytet NISKI — dotyczy tylko właścicieli carrierów; wymaga potwierdzenia usera, czy posiada/planuje carrier, przed jakimkolwiek researchem struktur eventów.

**12. (architektura, NIE priorytet teraz) Drugi ekran przez lokalny web UI (wzór ICARUS Terminal)** — alternatywa dla overlay+panel: lekki serwer HTTP lokalny + strona HTML odpytywana z telefonu/tabletu/drugiego monitora. Zaleta: zero problemów z fokusem/kompozytorem/kdotool, działa też w exclusive fullscreen. Wada: wymaga drugiego urządzenia pod ręką, większa zmiana architektury niż punkty 8-11. Nie podejmować bez wyraźnej decyzji usera — obecna architektura (pasek + panel TCE) działa i jest przetestowana.

**Do przeglądu, nie potwierdzony bug (z lekcji Inary):** sprawdzić czy `buy_price`/`sell_price` w `TradeRoute`, `MineralBuyer`, `CommoditySeller` (w `edtrade/trade.py`) jednoznacznie i poprawnie odpowiadają kierunkowi Import/Export w API Spansh/Ardent — osobna, krótka weryfikacja, niezależna od punktów 8-12.

**Kolejność zalecana przez Claude'a (do potwierdzenia/zmiany przez usera):** 9 (najmniejszy, rozszerza istniejący kod) → 8 (wymaga próbki journala, ale duża realna wartość) → weryfikacja Import/Export → 10 (mały, kosmetyczny) → 11/12 dopiero na wyraźne życzenie (niszowe/architektoniczne).

**Zrobione (2026-10-13): punkt 9A — zakładka "Towary" w panelu (gdzie kupić / gdzie sprzedać DOWOLNY towar).**
`panel.py`: nowa zakładka między Mining a Journey — Entry system + Entry towar + Combobox `Kup`/`Sprzedaj` + przycisk `Szukaj` + Text; ten sam wzorzec wątku roboczego co 4B-4E (`refresh_commodity_tab` → `_commodity_worker` → `window.after(0, _commodity_done)`). `Kup` → `find_commodity_sellers` (Ardent `/exports`, najtaniej najpierw), `Sprzedaj` → `find_mineral_buyers` (Ardent `/imports`, najdrożej najpierw) — obie funkcje już działały dla dowolnej nazwy towaru dzięki `_ardent_commodity_name`, brakowało tylko UI. Każdy wynik pokazuje wiek danych (`_data_age`: `<1h`/`Nh`/`Nd`) — lekcja z Inary.
Weryfikacja (Claude, cloud, Xvfb + Python 3.12): 6 zakładek, wszystkie widgety wiersza `mapped=1` z niezerową szerokością, `refresh` wraca po 0.0 s, przycisk disabled w trakcie / normal po, obie gałęzie (Kup/Sprzedaj) wypełniają tekst, puste pole towaru = brak wywołania. API Spansh/Ardent ZABLOKOWANE w kontenerze (polityka sieci środowiska) — funkcje sieciowe w teście podmienione atrapami; **test z prawdziwymi danymi do zrobienia u usera** (np. Sol / Gold / Kup). Regresja: `test_gui_brief.py` OK, `test_trade.py` 11/11.
**Weryfikacja Import/Export (z analizy konkurencji) — ZAMKNIĘTA, bez buga:** `/imports` → `sellPrice` → `MineralBuyer.sell_price` (ile DOSTAJESZ sprzedając), `/exports` → `buyPrice` → `CommoditySeller.buy_price` (ile PŁACISZ kupując) — nazwy spójne z perspektywą gracza.
**Punkt 9B (pełny market jednej stacji) — było CZEKA, ZROBIONE niżej.**

**Sieć w środowisku cloud odblokowana (2026-10-13, user dodał `spansh.co.uk` i `api.ardent-insight.com`).** Zakładka Towary zweryfikowana na ŻYWYCH danych: Gold wokół Sol — kup ~42 333 cr (Kelly Terminal), sprzedaj ~67 544 cr (Tayler Platform); Tritium, LTD też OK (LTD "Kup" = [] — sensowne przy `min_stock=500`). `test_search_sol` teraz przechodzi.

**Zrobione (2026-10-13): punkt 9B — zakładka "Market" (pełny rynek jednej stacji, wzór TD `market`).**
Endpoint zweryfikowany na żywo: `GET https://api.ardent-insight.com/v2/system/name/<system>/commodities` → lista rekordów wszystkich stacji systemu (`commodityName`, `marketId`, `stationName`, `buyPrice`, `sellPrice`, `stock`, `demand`, `meanPrice`, `updatedAt`, …); nieznany system → 404 `{"error":"Not Found","message":"System not found"}`. Istnieje też `/v2/market/<marketId>/commodities` (jedna stacja po ID) — nieużyty, bo nazwy wystarczają. `/v2/station/name/...` → 404 (nie istnieje).
PUŁAPKA: Ardent daje `sellPrice>0` także przy `demand=0` (Abraham Lincoln: 321 z 362 pozycji) — "sprzedasz tu" liczone tylko przy `demand>0`, "kupisz tu" tylko przy `stock>0 and buyPrice>0`.
`trade.py`: dataclassy `MarketItem`, `StationMarket` (z `error`), `get_station_market(system, station)` (dopasowanie nazwy stacji bez wielkości liter; exports sort po `buy_price - mean_price` rosnąco = najtaniej względem średniej, imports po `sell_price` malejąco; `updated_at` = najświeższy rekord). `panel.py`: zakładka Market między Towary a Journey, wątek roboczy jak 4B-4E, `_format_market` (cena ±% vs średnia galaktyczna, wiek danych).
Weryfikacja: na żywo Sol/Abraham Lincoln → 2 do kupienia / 41 do sprzedania, Colonia/Jaques Station → 27/112; GUI na Xvfb w `mainloop` — 7 zakładek, widgety mapped, wynik po 1.8 s, zła stacja → czytelny błąd, przycisk wraca do normal. `test_trade.py::TestStationMarket` (filtr/sort/błędy, bez sieci) — 14/14.
Nie zrobione (pomysł): automatyczne wypełnianie zakładki Market bieżącą stacją po evencie `Docked` (TCE "Commodities") — wymaga przekazania zdarzenia z wątku watchera do panelu przez `after()`; osobny mały krok.

**Zrobione (2026-10-13): Market wypełnia się sam po dokowaniu (wzór TCE "Commodities").**
`panel.py`: `show_docked_station(system, station)` — wołane z wątku watchera, przekazuje do wątku Tk przez `window.after(0, …)` (ten sam wzorzec co `overlay.update_route`); `_show_docked_station_inner` wpisuje system do zakładek System/Materiały/Mining/Towary/Market, stację do Market i odświeża TYLKO Market (pozostałe bez sieci; pomija odświeżenie, gdy Market właśnie liczy). `main.py::_on_docked`: wywołanie ZARAZ po deduplikacji, PRZED `calculate_route_via_spansh` (który blokuje wątek watchera 40-180 s) — rynek stacji jest widoczny od razu.
Weryfikacja e2e (Xvfb, prawdziwy `EDTradeOverlayApp` z overlayem i panelem, tymczasowy journal z eventem `Docked` Colonia/Jaques Station, żywa sieć): Market wypełniony po 3.7 s od startu (27/112 pozycji), w trakcie trwającego liczenia trasy Spansh; pola systemu we wszystkich zakładkach = 'Colonia'; przycisk normal. Regresja: `test_trade.py` 14/14, `test_gui_brief.py` OK.

### 8. Tracker materiałów — RESEARCH danych blueprintów (2026-10-13, Claude, zweryfikowane na plikach)
Brakująca połowa punktu 8 (część "czego brakuje", wzór EDEngineer) to dane wymagań blueprintów — znalezione i sprawdzone:
- **Wymagania:** [EDCD/coriolis-data](https://github.com/EDCD/coriolis-data) `modifications/blueprints.json` — dict 81 blueprintów (klucz = `fdname`, np. `AFM_Shielded`), `grades["1".."5"].components` = `{"Carbon": 1, "Shield Emitters": 1}` (nazwy WYŚWIETLANE, angielskie), razem 387 grade'ów, 96 różnych materiałów. Ostatnia zmiana repo: 2026-04-24.
  **LICENCJA:** dane JSON to własność Frontier (warunki Frontier), MIT obejmuje tylko kod Coriolis → **NIE commitować pliku do repo**; pobierać w runtime (raw GitHub) i cache'ować w `~/.local/share/ed-trade-overlay/`.
- **Mapowanie nazw:** [EDCD/FDevIDs](https://github.com/EDCD/FDevIDs) `material.csv` (`id,symbol,rarity,type,category,name`, 137 materiałów, typy Raw/Manufactured/Encoded, rarity 1-5). Pokrywa 96/96 materiałów z blueprintów (jedna nazwa ma spację na końcu — `strip()`).
  **PUŁAPKA:** 61/137 materiałów ma `symbol` ≠ znormalizowana nazwa (np. "Core Dynamics Composites" → `FedCoreComposites`, "Anomalous Bulk Scan Data" → `BulkScanData`) — naiwna normalizacja jak `_norm_commodity` NIE zadziała. Journal (event `Materials`) używa symbolu (lowercase), a `Name_Localised` jest w języku klienta gry (u usera prawdopodobnie PL) — mapować WYŁĄCZNIE po symbolu: `journal Name.lower() == symbol.lower()` → `name` → klucz w blueprints.
- **Limity magazynu** (do pokazania "ile max"): wg rarity 1→300, 2→250, 3→200, 4→150, 5→100 — znane z gry, DO POTWIERDZENIA na próbce/w grze przed użyciem.
Plan v1 (gdy przyjdzie próbka `Materials`): `edtrade/materials.py` — `load_material_names()` (FDevIDs, cache), `load_blueprints()` (coriolis, cache), `parse_materials_event(ev) -> dict[symbol, count]`, `missing_for(blueprint, grade, rolls, inventory) -> list[(name, need, have)]`; watcher: `Materials` do `INTERESTING_EVENTS` + callback; panel: zakładka "Inżynieria" (wybór blueprintu/grade/liczby rolli → lista braków + gdzie zdobyć: link do istniejących `find_material_traders`/`find_material_bodies`).
**BLOKER:** jedna realna linia `"event":"Materials"` z journala usera (struktura tablic `Raw`/`Manufactured`/`Encoded` i pól `Name`/`Count` — nie zgadywać z pamięci, zasada z pkt 6).

### KOREKTA punktu 10 (checklist mode) — 2026-10-13
Ręczne potwierdzanie etapów (jak w TD) NIE ma sensu w overlayu: pasek nie dostaje fokusu w grze (patrz "Renderowanie overlaya"), więc nie da się kliknąć "zrobione" bez wychodzenia z gry. Lepiej: **automatyczne odhaczanie z journala** — `MarketBuy` (kupiony towar z hopu) → krok "kup" ✓, `Docked`/`Location` w systemie celu → "leć" ✓, `MarketSell` → "sprzedaj" ✓ i przejście do następnego hopu (dziś hop przesuwa się już przy wejściu do systemu, ZANIM gracz sprzeda — to może być przedwczesne). **BLOKER:** próbki linii `MarketBuy` i `MarketSell` z journala usera.

**Zrobione (2026-10-13): punkt 8 v1 — tracker materiałów, zakładka "Inżynieria" (wzór EDEngineer).**
Próbki od usera (`test_data/journal_samples.jsonl`: `Materials`, `MarketBuy`, `MarketSell`). Klient gry po angielsku (`Name_Localised` EN), Raw bez `Name_Localised`; limity magazynu POTWIERDZONE (Carbon/Sulphur 300 = G1, Shield Emitters 250 = G2, Focus Crystals 200 = G3, Compound Shielding 150 = G4); 115/115 materiałów usera mapuje się przez FDevIDs, żaden nie przekracza limitu.
- `edtrade/materials.py`: `load_material_table()` (FDevIDs `material.csv`), `load_blueprints()` (coriolis `blueprints.json`), cache w `~/.local/share/ed-trade-overlay/` (świeży <7 dni; błąd sieci → stary cache; brak obu → `{}`), `parse_materials_event()` (po symbolu `Name`, NIE `Name_Localised`), `requirements()`, `missing_for()` (braki malejąco, nieznany materiał → typ `?` zamiast wyjątku).
- `watcher.py`: `Materials` w `INTERESTING_EVENTS` + callback `on_materials`. **NAPRAWIONY BUG (pre-istniejący, z pkt 7):** `Market` nie było w `INTERESTING_EVENTS`, więc `_dispatch` nigdy nie dostawał tego eventu — `on_market` i zasilanie `market_cache` z gry NIGDY nie działały na żywo (testy pkt 7 wołały funkcje bezpośrednio). Dodane.
- `main.py`: `_on_materials` → `panel.set_materials(event)`.
- `panel.py`: zakładka Inżynieria (blueprint, grade od/do, rolle na grade → BRAKUJE z podpowiedzią gdzie zdobyć wg typu / MASZ). Dane blueprintów ładowane w wątku startowanym Z `mainloop` (`window.after(200, …)`) — pułapka `after()` przed mainloopem. Stan materiałów pod lockiem (przeżyje nieudane `after()` przy wyścigu na starcie). Kolizja etykiet blueprintów (`MC_Overcharged`/`Weapon_Overcharged` = "Weapon: Overcharged") → druga dostaje klucz w nawiasie.
Ograniczenie v1: stan materiałów = migawka z eventu `Materials` (start gry); zmiany w trakcie sesji (`MaterialCollected`, `EngineerCraft`, `MaterialTrade`…) NIE są jeszcze śledzone — potrzebne próbki tych eventów. Panel pokazuje znacznik czasu migawki.
Weryfikacja: `test_materials.py` (7 testów, bez sieci, na realnej próbce usera) + `test_trade.py` → 20/20; e2e Xvfb (prawdziwy `EDTradeOverlayApp`, journal z realnym `Materials` + `Docked` + `Market`): 81 blueprintów, widgety mapped, FSD Increased Range G1→5 ×3 → brakuje 2× Datamined Wake Exceptions (masz 1/3), reszta ✓; Market Colonia po 2.5 s; zero ERROR/Traceback (także po włączeniu eventu Market); `test_gui_brief.py` OK.
Obserwacja z próbek: ostatni kurs biowaste 246 t — kupione 54 cr, sprzedane 32 cr (strata 21 412 cr) — zgodne z wcześniejszym zgłoszeniem "bio" (bug hopów naprawiony wcześniej). Pkt 10 (auto-checklista z `MarketBuy`/`MarketSell`) ma już próbki — następny.

**Zrobione (2026-10-13): punkt 10 — automatyczna checklista trasy (kup → leć → sprzedaj), odhaczana z journala.**
Znalezione przy analizie (stary mechanizm hopów był martwy): `_on_location` przesuwał hop na evencie `Location`, który gra wysyła tylko przy starcie/odrodzeniu (przy skokach jest `FSDJump`), i sprawdzał cel NASTĘPNEGO hopu (`hops_list[_current_hop]`) — w praktyce hop się nie przesuwał. Do tego KAŻDE dokowanie liczyło nową trasę od zera, także w porcie docelowym bieżącego hopu, więc plan wieloetapowy był nadpisywany w trakcie realizacji.
- `edtrade/checklist.py`: `RouteChecklist` — `MarketBuy` towaru hopu → "kup" (licznik kupione/zalecane, ◐ przy częściowym), `Docked` w porcie celu → "leć", `MarketSell` w porcie celu → "sprzedaj"; gdy sprzedano ≥ kupiono → następny hop; po ostatnim → "[✓ trasa ukończona]". Towar z journala (symbol) mapowany na nazwę Spansh przez FDevIDs `commodity.csv` + `rare_commodity.csv` (115/412 symboli ≠ nazwa, np. `Opal` = "Void Opal"), cache jak materiały (`fetch_cached`, wspólny z `materials.py`). Stan startowy "kup" z ładowni (`Cargo`) — zakup często jest przed końcem liczenia Spansh. Eventy starsze niż utworzenie trasy ignorowane (catch-up journala przy starcie odtwarza historię); czas utworzenia obcięty do sekund (journal ma rozdzielczość sekundową — test e2e wyłapał, że zakup w tej samej sekundzie był odrzucany).
- `watcher.py`: `MarketBuy`/`MarketSell` w `INTERESTING_EVENTS` + callback `on_trade`. `main.py`: `_publish_route` (nowa trasa → nowa checklista, także po `Loadout`), `_feed_checklist`, `_on_trade`; `_on_docked` w porcie celu bieżącego hopu NIE przelicza trasy; po ukończeniu trasy od razu liczona następna z bieżącej stacji. `_on_location` (martwy) usunięty. `overlay.py`: znaczniki kroków w pasku (także dla trasy 1-hopowej), np. `Hop 2/3 [✓ kup 304/304 · ▶ leć · ○ sprzedaj]`.
- **Naprawiony pre-istniejący bug:** w `_on_docked` import `search_stations` był wewnątrz `if system_id64:` → bez `SystemAddress` `UnboundLocalError` (automat info o systemie padał). Importy przeniesione na górę pliku.
Weryfikacja: `test_checklist.py` (8 testów: pełna trasa Sol/Columbus 3 hopy, częściowy zakup/sprzedaż w 2 transakcjach, sprzedaż poza celem i inny towar ignorowane, historia + ładownia, symbol≠nazwa, realny format eventów usera, ta sama sekunda, pusta trasa) — razem 28/28. E2E na Xvfb (prawdziwy watcher śledzący dopisywany na żywo journal, overlay, trasa Sol/Columbus z prawdziwych danych Spansh podstawiona za liczenie): 10/10 kroków w tekście paska, `calculate_route_via_spansh` wołany 1× podczas realizacji trasy i 1× po jej ukończeniu, zero ERROR/Traceback. Regresja: `test_gui_brief.py`, Inżynieria (81 blueprintów), Market (2.2 s) OK.
Do sprawdzenia w grze: realne nazwy towarów Spansh vs journal dla rzadszych towarów; zachowanie przy sprzedaży części ładunku w innym porcie (dziś ignorowana).
