"""Text helpers of the UI: power formatting / parsing and ellipsizing (no display needed)."""

import pytest

pytest.importorskip("tkinter")

from laser_app.ui import text as ui_text  # noqa: E402


@pytest.mark.parametrize("value, text", [
    (35, "35.0"), (12.25, "12.25"), (0.2, "0.2"), (12.0, "12.0"), (1.005, "1.0"), (0, "0.0"),
])
def test_fmt_mw(value, text):
    assert ui_text.fmt_mw(value) == text


@pytest.mark.parametrize("text, value", [
    ("12", 12.0), (" 12.5 ", 12.5), ("12,5", 12.5), ("-3", -3.0), ("1e1", 10.0),
])
def test_parse_mw_numbers(text, value):
    assert ui_text.parse_mw(text) == value


@pytest.mark.parametrize("text", ["", "abc", "1.2.3", "nan", "inf", "-inf"])
def test_parse_mw_rejects(text):
    assert ui_text.parse_mw(text) is None


class OnePxPerChar:
    """Stands in for a tkfont.Font: every character is 1 px wide."""

    @staticmethod
    def measure(text):
        return len(text)


def test_ellipsize():
    f = OnePxPerChar()
    assert ui_text.ellipsize("hello", f, 10) == "hello"
    assert ui_text.ellipsize("hello", f, 5) == "hello"
    assert ui_text.ellipsize("hello world", f, 6) == "hello…"
    assert len(ui_text.ellipsize("hello world", f, 6)) <= 6
    assert ui_text.ellipsize("hello", f, 1) == "hello"       # no room at all: left alone
    assert ui_text.ellipsize("hello", f, 0) == "hello"
