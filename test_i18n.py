"""Język interfejsu: tłumaczenie tekstów (całych i złożonych) oraz hak Tk."""
import tkinter as tk
from tkinter import ttk

import pytest

from edtrade import i18n


@pytest.fixture
def english():
    i18n.set_language('en')
    yield
    i18n.set_language('pl')


def test_polish_is_untouched():
    i18n.set_language('pl')
    assert i18n.tr('BŁĄD TRASY') == 'BŁĄD TRASY'


def test_detect_language():
    assert i18n.detect_language('en') == 'en'
    assert i18n.detect_language('pl', env={'LANG': 'en_US.UTF-8'}) == 'pl'
    assert i18n.detect_language('auto', env={'LANG': 'pl_PL.UTF-8'}) == 'pl'
    assert i18n.detect_language('auto', env={'LANG': 'de_DE.UTF-8'}) == 'en'


@pytest.mark.parametrize('pl, en', [
    ('Ustawienia', 'Settings'),
    ('BŁĄD TRASY', 'ROUTE ERROR'),
    ('Ceny', 'Prices'),
    ('CENY', 'PRICES'),
    ('LICZĘ TRASĘ… 12s', 'PLOTTING ROUTE… 12s'),
    ('Brak traderów Raw w zasięgu 50 ly od Sol', 'No Raw traders within 50 ly of Sol'),
    ('1,024 t za 12,000 cr (4 sprzedaży)', '1,024 t for 12,000 cr (4 sales)'),
    ('brakuje 3 z 7', 'missing 3 of 7'),
    ('◐ sprzedaj 10/100', '◐ sell 10/100'),
    ('3h temu', '3h ago'),
    ('Jameson Memorial', 'Jameson Memorial'),  # nazwy własne zostają
])
def test_translations(english, pl, en):
    assert i18n.tr(pl) == en


def test_source_maps_back_to_polish_key(english):
    assert i18n.source('Settings') == 'Ustawienia'
    assert i18n.source('Unknown page') == 'Unknown page'


def test_every_polish_entry_has_no_polish_letters_in_english():
    polish = set('ąćęłńóśźżĄĆĘŁŃÓŚŹŻ')
    assert not [k for k, v in i18n.EN.items() if polish & set(v)]


def test_tk_widgets_are_translated(english):
    i18n.install()
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip('no display')
    try:
        label = tk.Label(root, text='Zapisz')
        assert label.cget('text') == 'Save'
        label.configure(text='TRASA UKOŃCZONA')
        assert label.cget('text') == 'ROUTE COMPLETE'
        notebook = ttk.Notebook(root)
        frame = ttk.Frame(notebook)
        notebook.add(frame, text='Okolica')
        assert notebook.tab(frame, 'text') == 'Nearby'
        tree = ttk.Treeview(root, columns=('a',), show='headings')
        tree.heading('a', text='Zysk/t')
        assert tree.heading('a', 'text') == 'Profit/t'
        iid = tree.insert('', tk.END, values=['brak zysku'])
        assert tree.item(iid, 'values') == ('no profit',)
    finally:
        root.destroy()
