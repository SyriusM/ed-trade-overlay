# Zadanie: IMPLEMENTACJA ONLY — find_commodity_sellers (punkt 6 v1, kolonizacja)
Bez researchu, bez przeglądarki, bez curl. Tło: SPEC.md, sekcja "6. Materiały do kolonizacji/budowy — RESEARCH".
Nie ruszaj istniejących funkcji/klas (w szczególności `find_mineral_buyers`, `_ardent_commodity_name`, `_norm_commodity`, `PAD_SIZE_MAP`). Nie edytuj SPEC.md. Wszystko na poziomie modułu w edtrade/trade.py, NIE w TradeEngine. Błąd sieci -> [] + logger.error, nigdy wyjątek na zewnątrz.
Wzoruj się 1:1 na istniejącej `find_mineral_buyers` (przeczytaj ją najpierw) — to jej lustro: ten sam helper nazwy `_ardent_commodity_name(commodity)`, ten sam styl, ale endpoint `/exports` (sprzedawcy towaru) zamiast `/imports`.

## 1. Dataclass `CommoditySeller` (wszystkie pola z domyślnymi, tylko te): station_name:str, system_name:str, stock:int, buy_price:int, pad_size:str, distance:float, distance_to_arrival:float, updated_at:str

## 2. `find_commodity_sellers(commodity: str, reference_system: str, max_ly: float = 60.0, min_stock: int = 500, max_days: int = 7, size: int = 10) -> list[CommoditySeller]`
a) nazwa = `_ardent_commodity_name(commodity)`.
b) GET f"https://api.ardent-insight.com/v2/commodity/name/{nazwa}/exports" z params {"maxDaysAgo": max_days, "fleetCarriers": 0, "minVolume": min_stock, "systemName": reference_system, "maxDistance": max_ly}, nagłówek User-Agent "EdTradeOverlay/0.1", timeout 30. Odpowiedź to lista dictów, DOSŁOWNIE np.:
{"stationName": "Ivins City", "systemName": "Gendalla", "stock": 1253, "buyPrice": 200, "maxLandingPadSize": 2, "distanceToArrival": 1234.5, "distance": 17, "updatedAt": "2026-10-12T03:41:59.000Z"}
(klucz "buyPrice" = cena, po jakiej GRACZ KUPUJE towar od stacji; "stock" = ile jest do kupienia).
c) Odpowiedź nie jest listą -> []. Mapuj: pad_size z maxLandingPadSize przez PAD_SIZE_MAP (inaczej ""), `stock = b.get("stock") or 0`, `buy_price = b.get("buyPrice") or 0`, distance/distance_to_arrival z `or 0.0`, updated_at `or ""`. Odfiltruj stock < min_stock. Sortuj buy_price ROSNĄCO (najtaniej pierwszy), potem stock malejąco; utnij do size.

## 3. Test (realny, max 60 s), z katalogu ~/Projekty/ed-trade-overlay:
python3 -m py_compile edtrade/trade.py
python3 -c "from edtrade.trade import find_commodity_sellers as f; print(f('Aluminium','Sol',40,500,7,3)); print(f('CMM Composite','Sol',100,100,30,2)); print(f('Liquid Oxygen','Sol',150,100,30,2))"
Oczekiwane: aluminium >= 1 wynik (np. Ivins City, Gendalla), buy_price rosnące. CMM Composite i Liquid Oxygen mogą dać puste listy w małym promieniu — jeśli puste, sprawdź tylko że nie ma wyjątku i wypisz co zwróciło `_ardent_commodity_name('CMM Composite')` i `_ardent_commodity_name('Liquid Oxygen')`.
Na końcu krótko: co zrobione + wyniki testu.
