import json
from datetime import date

import pytest

from scripts.aire_client import AireError, fetch_window, month_windows


def test_month_windows_son_semiabiertas():
    got = month_windows(date(2025, 1, 1), date(2025, 4, 1))
    assert got == [
        ("2025-01-01", "2025-02-01"),
        ("2025-02-01", "2025-03-01"),
        ("2025-03-01", "2025-04-01"),
    ]


def test_month_windows_cruza_fin_de_anio():
    got = month_windows(date(2025, 11, 1), date(2026, 2, 1))
    assert got == [
        ("2025-11-01", "2025-12-01"),
        ("2025-12-01", "2026-01-01"),
        ("2026-01-01", "2026-02-01"),
    ]


def test_month_windows_rango_completo_da_93_ventanas():
    got = month_windows(date(2019, 1, 1), date(2026, 10, 1))
    assert len(got) == 93
    assert got[0] == ("2019-01-01", "2019-02-01")
    assert got[-1] == ("2026-09-01", "2026-10-01")


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_window_decodifica_utf8_desde_bytes():
    # 'Revisión' en UTF-8 real: los bytes C3 B3 forman la o con tilde.
    payload = json.dumps(
        {"d": [{"CONSECUTIVO": 1, "DESC_ESTADO": "Revisión documento"}]},
        ensure_ascii=False,
    ).encode("utf-8")
    rows = fetch_window("2025-01-01", "2025-02-01", opener=lambda *a, **k: _FakeResponse(payload))
    assert rows[0]["DESC_ESTADO"] == "Revisión documento"


def test_fetch_window_no_recodifica_latin1():
    payload = '{"d":[{"DESC_ESTADO":"Revisión documento"}]}'.encode("utf-8")
    rows = fetch_window("2025-01-01", "2025-02-01", opener=lambda *a, **k: _FakeResponse(payload))
    assert "Ã" not in rows[0]["DESC_ESTADO"]


def test_fetch_window_detecta_el_html_de_error_de_aspnet():
    html = b"<html><head><title>Runtime Error</title></head><body>Server Error</body></html>"
    calls = []
    dormido = []

    def opener(*a, **k):
        calls.append(1)
        return _FakeResponse(html)

    with pytest.raises(AireError) as exc:
        fetch_window("2025-01-01", "2025-02-01", opener=opener, attempts=3, sleep=lambda s: dormido.append(s))
    assert len(calls) == 3
    assert dormido == [1, 2]
    assert "2025-01-01" in str(exc.value)


def test_fetch_window_reintenta_y_luego_acierta():
    good = json.dumps({"d": [{"CONSECUTIVO": 7}]}).encode("utf-8")
    respuestas = [b"<html>Runtime Error</html>", good]
    dormido = []

    def opener(*a, **k):
        return _FakeResponse(respuestas.pop(0))

    rows = fetch_window("2025-01-01", "2025-02-01", opener=opener, attempts=3, sleep=lambda s: dormido.append(s))
    assert dormido == [1]
    assert rows == [{"CONSECUTIVO": 7}]
