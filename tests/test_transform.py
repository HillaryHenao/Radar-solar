import pytest

from scripts.transform import (
    norm_text,
    parse_almacenamiento,
    parse_fecha,
    round5,
    to_row,
)


def test_norm_text_colapsa_espacios_y_recorta():
    crudo = "                              UNIVERSIDAD          DEL NORTE           "
    assert norm_text(crudo) == "UNIVERSIDAD DEL NORTE"


def test_norm_text_colapsa_tabuladores():
    assert norm_text("LICA ENERGÍA RENOVABLE S.A.S\t\t\t\t\t") == "LICA ENERGÍA RENOVABLE S.A.S"


def test_norm_text_colapsa_el_espacio_doble_de_la_vereda():
    # Es el unico cambio real que produce esta corrida, en el codigo 23465.
    assert norm_text("VDA  CHARCO LATA") == "VDA CHARCO LATA"


def test_norm_text_none_da_cadena_vacia():
    assert norm_text(None) == ""


def test_parse_fecha_convierte_a_utc_menos_5():
    # Golden 22810: el portal da 2025-01-31 22:37 UTC; la BD tiene 17:37.
    assert parse_fecha("/Date(1738363020000)/") == "2025-01-31 17:37"


def test_parse_fecha_golden_21941():
    # Contra ejemplo.pdf: 30/10/2024 14:32.
    assert parse_fecha("/Date(1730316720000)/") == "2024-10-30 14:32"


def test_parse_fecha_rechaza_formato_desconocido():
    with pytest.raises(ValueError, match="FEC_CREA"):
        parse_fecha("2025-01-31")


def test_parse_fecha_rechaza_el_epoch_centinela():
    # air-e usa /Date(-62135578800000)/ como "sin fecha" en otros campos.
    with pytest.raises(ValueError, match="fuera de rango"):
        parse_fecha("/Date(-62135578800000)/")


def test_round5_recorta_el_ruido_de_punto_flotante():
    assert round5(-74.156100000000009) == -74.1561


def test_round5_none_da_none():
    assert round5(None) is None


@pytest.mark.parametrize(
    "crudo,esperado",
    [(1, True), (2, False), (0, None), (None, None), (3, None)],
)
def test_parse_almacenamiento(crudo, esperado):
    assert parse_almacenamiento(crudo) is esperado


def test_to_row_mapea_el_registro_completo():
    rec = {
        "CONSECUTIVO": 23433,
        "FEC_CREA": "/Date(1744145640000)/",
        "DESC_ESTADO": "  Estudio solicitud ",
        "NOMBRE_CLI": "We-262 ",
        "DESC_CIUDAD_PRO": "ARACATACA",
        "DESC_CORREGIMIENTO_PRO": "ARACATACA",
        "DESC_VEREDA_PRO": "ARACATACA  RURAL",
        "TECNO_UTILIZADA_DESC": "Solar FV",
        "TIPO": "GD menor igual 0.1MVA",
        "LATITUD": 10.58598,
        "LONGITUD": -74.156100000000009,
        "TIENE_ALMACENAMIENTO": 2,
        "CAPACIDAD_ALMACENAMIENTO": 0,
        "POTENCIA_TOTAL_AC": 100,
    }
    row = to_row(rec)
    assert row["c"] == "23433"
    assert row["es"] == "Estudio solicitud"
    assert row["cl"] == "We-262"
    assert row["ve"] == "ARACATACA RURAL"
    assert row["lo"] == -74.1561
    assert row["al"] is False
    assert row["ak"] == 0
    assert row["pac"] == 100


def test_to_row_codigo_es_string():
    rec = {
        "CONSECUTIVO": 7,
        "FEC_CREA": "/Date(1744145640000)/",
        "LATITUD": 1,
        "LONGITUD": 2,
        "TIENE_ALMACENAMIENTO": 1,
        "CAPACIDAD_ALMACENAMIENTO": 250,
    }
    row = to_row(rec)
    assert row["c"] == "7"
    assert isinstance(row["c"], str)
    assert row["al"] is True
    assert row["ak"] == 250
