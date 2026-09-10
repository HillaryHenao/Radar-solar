from datetime import date

from scripts import fetch_aire

_FEC_CREA = "/Date(1738363020000)/"


def _crudo(consecutivo, **extra):
    base = {
        "CONSECUTIVO": consecutivo,
        "FEC_CREA": _FEC_CREA,
        "LATITUD": 10.5,
        "LONGITUD": -74.5,
        "TIENE_ALMACENAMIENTO": 2,
        "CAPACIDAD_ALMACENAMIENTO": 0,
    }
    base.update(extra)
    return base


def test_descargar_indexa_por_el_codigo_propio_del_registro(monkeypatch):
    # Guarda #1 del spec: cada registro se indexa por su propio CONSECUTIVO,
    # nunca por lo que se pidio en la ventana. Una sola ventana devuelve DOS
    # registros con CONSECUTIVO distinto; si `descargar` indexara por algo
    # derivado de la solicitud (la ventana pedida, por ejemplo) en vez de
    # `fila["c"]`, el segundo registro pisaria al primero bajo la misma
    # clave y solo sobreviviria uno. Que ambos sobrevivan bajo su propio
    # codigo es justamente lo que este test observa -no el contenido de las
    # filas, que es tautologico si se lee de si mismo.
    def fake_fetch_window(ini, fin):
        return [_crudo(999), _crudo(888)]

    monkeypatch.setattr(fetch_aire, "fetch_window", fake_fetch_window)
    monkeypatch.setattr(
        fetch_aire, "month_windows",
        lambda desde, hasta: [("2025-01-01", "2025-02-01")],
    )

    filas = fetch_aire.descargar(date(2025, 1, 1), date(2025, 2, 1))
    assert {f["c"] for f in filas} == {"999", "888"}


def test_descargar_con_codigo_duplicado_entre_ventanas_conserva_el_ultimo(monkeypatch):
    ventanas = [("2025-01-01", "2025-02-01"), ("2025-02-01", "2025-03-01")]
    respuestas = {
        ventanas[0]: [_crudo(5, DESC_ESTADO="Viejo")],
        ventanas[1]: [_crudo(5, DESC_ESTADO="Nuevo")],
    }

    def fake_fetch_window(ini, fin):
        return respuestas[(ini, fin)]

    monkeypatch.setattr(fetch_aire, "fetch_window", fake_fetch_window)
    monkeypatch.setattr(fetch_aire, "month_windows", lambda desde, hasta: ventanas)

    filas = fetch_aire.descargar(date(2025, 1, 1), date(2025, 3, 1))
    assert len(filas) == 1
    assert filas[0]["c"] == "5"
    assert filas[0]["es"] == "Nuevo"


def test_descargar_ordena_los_codigos_no_numericos_al_final(monkeypatch):
    # C139/C153/C159 (marcadores internos del sheet, nunca vistos en air-e)
    # son el ejemplo real de un CONSECUTIVO no numerico; int(f["c"]) lanzaria
    # ValueError si alguno apareciera despues de un pull de ~10 minutos.
    def fake_fetch_window(ini, fin):
        return [_crudo("C139"), _crudo(5)]

    monkeypatch.setattr(fetch_aire, "fetch_window", fake_fetch_window)
    monkeypatch.setattr(
        fetch_aire, "month_windows",
        lambda desde, hasta: [("2025-01-01", "2025-02-01")],
    )

    filas = fetch_aire.descargar(date(2025, 1, 1), date(2025, 2, 1))
    assert [f["c"] for f in filas] == ["5", "C139"]
