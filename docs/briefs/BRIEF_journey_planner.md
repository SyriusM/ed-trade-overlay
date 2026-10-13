# Zadanie: IMPLEMENTACJA ONLY — journey planner v1 (punkt 3)
Nie rób researchu, nie szukaj docs w przeglądarce (wiemy już wszystko — patrz SPEC.md, sekcja "KOREKTA punktu 3" na końcu pliku).
1. Przeczytaj tę sekcję w SPEC.md oraz polling Spansh w edtrade/trade.py (okolice linii 480-560, POST /api/trade/route + GET /api/results/{job}).
2. Dodaj w edtrade/trade.py: dataclassy JourneyHop i JourneyPlan (poziom modułu) oraz funkcję plan_journey(...) wg sygnatury z SPEC.md.
   POST https://spansh.co.uk/api/route, form data from/to/range/efficiency (+via jeśli podane), potem polling wyniku jak w TradeEngine (timeout 120 s, błąd -> JourneyPlan(error=...), nigdy wyjątek na zewnątrz).
3. NIE ruszaj istniejących funkcji/klas. NIE dodawaj logiki paliwa.
4. Test: python3 -m py_compile edtrade/trade.py, potem realny test: plan_journey("Sol", "Colonia", 30.0) -> total_jumps > 0, hops[0].system == "Sol", jakiś hop z neutron_star=True. Daj mu do 60 s.
5. Na końcu wypisz krótko co zrobiłeś i wynik testu. Nie edytuj SPEC.md.
