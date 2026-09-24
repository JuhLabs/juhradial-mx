"""GTK fallback app profiles write a SmartShift threshold in 1..49 (PR #123).

The dialog used to write threshold 50, Logitech's ratchet-only endpoint, for
every profile. The helper is extracted from the source (GTK is not importable
headless) and exercised directly.
"""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "overlay" / "settings_dialog_apps.py"


def _helper():
    tree = ast.parse(SRC.read_text())
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "_profile_smartshift_threshold")
    ns = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(SRC), "exec"), ns)
    return ns["_profile_smartshift_threshold"]


def test_keeps_a_valid_profile_value():
    f = _helper()
    assert f(12, 90) == 12
    assert f(49, 1) == 49


def test_maps_the_global_sensitivity_like_the_qt_app():
    f = _helper()
    assert f(None, 1) == 1
    assert f(None, 50) == 25
    assert f(None, 100) == 49
    assert f(50, 23) == 12       # out-of-range legacy value is replaced
    assert f(True, 50) == 25     # a bool is not a threshold
    assert f(None, "junk") == 25


def test_no_literal_fifty_threshold_left():
    assert '"threshold": 50' not in SRC.read_text()
