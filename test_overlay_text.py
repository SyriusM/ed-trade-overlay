"""Teksty paska overlay: skracanie kwot i przycinanie do szerokości."""

from edtrade.overlay import compact_cr, fit_line


def test_compact_cr():
    assert compact_cr(7_920_877) == "7.92M"
    assert compact_cr(84_500) == "84.5K"
    assert compact_cr(9_999) == "9,999"
    assert compact_cr(-1_500_000) == "-1.50M"


def test_fit_line_keeps_short_text():
    assert fit_line("ZYSK 7.92M CR", 1000, len) == "ZYSK 7.92M CR"


def test_fit_line_truncates_with_ellipsis():
    out = fit_line("LEPIDOLITE ×256  352 → 3,353", 12, len)
    assert out.endswith("…") and len(out) <= 12


def test_fit_line_unmapped_widget_untouched():
    assert fit_line("ABC", 1, len) == "ABC"
