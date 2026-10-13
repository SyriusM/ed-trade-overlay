"""Testy katalogu tekstów UI (i18n.py): kompletność PL/EN, placeholdery, liczebniki, przełączanie języka."""

import string
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from edtrade import i18n
from edtrade.checklist import RouteChecklist
from edtrade.filters import MarketFilter
from edtrade.trade import Hop, TradeRoute


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


class CatalogTest(unittest.TestCase):
    def test_same_keys_in_every_language(self):
        keys = set(i18n.CATALOG[i18n.DEFAULT_LANGUAGE])
        for lang, texts in i18n.CATALOG.items():
            self.assertEqual(set(texts), keys, lang)
        self.assertEqual(set(i18n.LANGUAGES), set(i18n.CATALOG))

    def test_same_placeholders_in_every_language(self):
        for key, text in i18n.CATALOG[i18n.DEFAULT_LANGUAGE].items():
            for lang, texts in i18n.CATALOG.items():
                self.assertEqual(_fields(texts[key]), _fields(text), f'{lang}:{key}')

    def test_plural_keys_have_three_forms(self):
        for lang, texts in i18n.CATALOG.items():
            for key, text in texts.items():
                if key.startswith('n.'):
                    self.assertEqual(len(text.split('|')), 3, f'{lang}:{key}')


class LanguageTest(unittest.TestCase):
    def tearDown(self):
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_polish_is_default_and_unknown_falls_back(self):
        self.assertEqual(i18n.get_language(), 'pl')
        self.assertEqual(i18n.set_language('xx'), 'pl')
        self.assertEqual(i18n.t('bar.position'), 'POZYCJA')

    def test_switch_to_english(self):
        i18n.set_language('en')
        self.assertEqual(i18n.t('bar.position'), 'POSITION')
        self.assertEqual(i18n.t('route.active', n=2, total=3), 'ROUTE ACTIVE — HOP 2/3')

    def test_missing_key_shows_key(self):
        self.assertEqual(i18n.t('no.such.key'), 'no.such.key')

    def test_polish_plural(self):
        words = [i18n.plural(n, 'n.hops') for n in (1, 2, 4, 5, 12, 22, 25, 0)]
        self.assertEqual(words, ['hop', 'hopy', 'hopy', 'hopów', 'hopów', 'hopy', 'hopów', 'hopów'])

    def test_english_plural(self):
        i18n.set_language('en')
        self.assertEqual([i18n.plural(n, 'n.stations') for n in (1, 2, 5)], ['station', 'stations', 'stations'])

    def test_checklist_and_filter_follow_language(self):
        hop = Hop(source_system='Sol', source_station='Columbus', destination_system='Barnard', destination_station='X',
                  commodity='Gold', amount=10, buy_price=1, sell_price=2)
        route = TradeRoute(source_system='Sol', source_station='Columbus', hops=1, hops_list=[hop])
        self.assertEqual(RouteChecklist(route, {}).status_text(), '[▶ kup 10 · ○ leć · ○ sprzedaj]')
        self.assertEqual(MarketFilter().describe(), 'pad M+ · ≤5,000 ls')
        i18n.set_language('en')
        self.assertEqual(RouteChecklist(route, {}).status_text(), '[▶ buy 10 · ○ fly · ○ sell]')
        self.assertEqual(MarketFilter(min_pad='small', max_star_ls=0).describe(), 'any pad · no ls limit')

    def test_finished_flag_does_not_depend_on_text(self):
        route = TradeRoute(source_system='Sol', source_station='Columbus')
        i18n.set_language('en')
        RouteChecklist(route, {})
        self.assertTrue(route._finished)
        self.assertEqual(route._checklist_text, '[✓ route complete]')


if __name__ == '__main__':
    unittest.main()
