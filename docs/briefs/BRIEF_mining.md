# Zadanie: IMPLEMENTACJA ONLY — wyszukiwarka górnicza v1 (punkt 5)
Bez researchu, bez przeglądarki, bez curl. Pełne tło: SPEC.md, sekcja "5. Trasy górnicze — RESEARCH" + akapit "Zweryfikowane (uzupełnienie punktu 5)" na końcu.
Wzoruj się na istniejącym w edtrade/trade.py: `_spansh_search(url, payload)` (POST JSON, zwraca results[] lub []), `find_material_bodies`, `MATERIAL_BODY_URL`. Nie ruszaj istniejących funkcji/klas. Nie edytuj SPEC.md. Wszystko na poziomie modułu, błąd sieci -> pusta lista + logger.error (nigdy wyjątek na zewnątrz).

## 1. Dataclassy (wszystkie pola z domyślnymi, tylko te pola)
- `MiningHotspot`: system_name:str, body_name:str, ring_name:str, ring_type:str, count:int, distance:float, distance_to_arrival:float, updated_at:str
- `MineralBuyer`: station_name:str, system_name:str, demand:int, sell_price:int, pad_size:str, distance:float, distance_to_arrival:float, updated_at:str

## 2. `find_mining_hotspots(reference_system: str, mineral: str, max_ly: float = 50.0, min_count: int = 1, size: int = 10) -> list[MiningHotspot]`
Użyj `_spansh_search(MATERIAL_BODY_URL, payload)` z payloadem (DOSŁOWNIE tak, to działa):
{"filters": {"ring_signals": [{"name": mineral, "comparison": "<=>", "value": [1, 100]}], "distance": {"min": 0, "max": max_ly}}, "reference_system": reference_system, "size": 100}
Wynik: results[] to ciała: r["name"], r["system_name"], r["distance"], r["distance_to_arrival"], r["rings"] = lista pierścieni, np.
{"name": "BD+16 2404 4 A Ring", "type": "Metallic", "signals": [{"count": 1, "name": "Platinum"}, {"count": 2, "name": "Rhodplumsite"}], "signals_updated_at": "2026-08-16T19:52:02Z", ...}
Dla KAŻDEGO pierścienia ciała, który w ring["signals"] ma wpis o name == mineral (porównanie bez rozróżniania wielkości liter) i count >= min_count, utwórz jeden MiningHotspot (ring_name=ring["name"], ring_type=ring["type"], count=signal["count"], updated_at=ring.get("signals_updated_at") or ""). Pomiń pierścienie bez tego minerału (ciało może mieć inny pierścień z minerałem, a inny bez). Sortuj: count malejąco, potem distance_to_arrival rosnąco; utnij do size. Użyj `or 0.0` przy distance/distance_to_arrival (mogą być None).

## 3. `find_mineral_buyers(mineral: str, reference_system: str, max_ly: float = 60.0, min_demand: int = 100, max_days: int = 7, size: int = 10) -> list[MineralBuyer]`
a) Nazwa towaru w Ardent jest nieregularna. Dodaj helper `_ardent_commodity_name(mineral: str) -> str`: pobierz GET https://api.ardent-insight.com/v2/commodities (JSON: lista dictów z kluczem "commodityName", timeout 30), zbuduj normalizację `norm(s) = "".join(ch for ch in s.lower() if ch.isalnum())` i potem utnij JEDNO końcowe "s" jeśli jest; znajdź pierwszy commodityName z norm(commodityName) == norm(mineral) i zwróć go. Przykłady: "Platinum" -> "platinum", "Low Temperature Diamonds" -> "lowtemperaturediamond", "Void Opals" -> "void opal". Cache listy w zmiennej modułowej (pobieraj raz). Gdy brak dopasowania lub błąd sieci: zwróć mineral.lower().
b) GET f"https://api.ardent-insight.com/v2/commodity/name/{nazwa}/imports" z params {"maxDaysAgo": max_days, "fleetCarriers": 0, "minVolume": min_demand, "systemName": reference_system, "maxDistance": max_ly}, nagłówki User-Agent "EdTradeOverlay/0.1", timeout 30. Odpowiedź: lista dictów, np.
{"stationName": "Molina Platform", "systemName": "Crucis Sector DB-X b1-6", "demand": 3174, "sellPrice": 302844, "maxLandingPadSize": 2, "distanceToArrival": 318882.68, "distance": 57, "updatedAt": "2026-10-12T03:41:59.000Z", "stationType": "Outpost"}
Mapuj: pad_size z maxLandingPadSize: {1: "small", 2: "medium", 3: "large"} (inaczej ""). Odfiltruj demand < min_demand (API zwraca też demand 0). Sortuj sell_price malejąco, utnij do size. Błąd sieci / odpowiedź nie-lista -> [].

## 4. Test (realny, uruchom sam, max 60 s)
`python3 -m py_compile edtrade/trade.py`, potem z katalogu ~/Projekty/ed-trade-overlay:
python3 -c "from edtrade.trade import find_mining_hotspots as h, find_mineral_buyers as b; r=h('Sol','Platinum',50,1,3); print(r); print(b('Platinum','Sol',60,100,7,3)); print(b('Low Temperature Diamonds','Sol',300,10,30,2))"
Oczekiwane: hotspoty >= 1 z niepustym ring_name i count >= 1; kupcy platyny >= 1 (np. Molina Platform), malejące sell_price.
Na końcu krótko: co zrobione + wynik testu.
