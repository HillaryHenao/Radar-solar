from pathlib import Path

import pytest

from scripts.build_data import estados_de_ui, municipios_de_ui

INDEX = Path(__file__).resolve().parent.parent / "index.html"


@pytest.fixture(scope="module")
def html():
    return INDEX.read_text(encoding="utf-8")


def test_dept_map_cubre_el_pinon_corrupto(html):
    # air-e trae el municipio con el nombre corrupto (bytes C2 BF, U+00BF) en
    # vez del nombre real. La clave debe usar la forma corrupta o el lookup
    # falla y sale 'Sin clasificar'. Se usa el escape para no depender de la
    # codificacion de este archivo.
    municipios = municipios_de_ui(html)
    assert "EL PI\u00bfON" in municipios


def test_dept_map_cubre_los_municipios_del_magdalena_que_faltaban(html):
    municipios = municipios_de_ui(html)
    for nombre in ("SABANAS DE SAN ANGEL", "ZAPAYAN", "ARIGUANI", "PEDRAZA",
                   "PUEBLO VIEJO"):
        assert nombre in municipios, nombre


def test_dept_map_cubre_los_municipios_de_las_altas(html):
    municipios = municipios_de_ui(html)
    for nombre in ("FONSECA", "CIENAGA"):
        assert nombre in municipios, nombre


def test_estado_order_sigue_teniendo_los_siete_estados(html):
    assert len(estados_de_ui(html)) == 7


def test_el_state_tiene_la_bandera_de_almacenamiento(html):
    assert "soloAlmacenamiento:false" in html.replace(" ", "")


def test_passes_other_filters_considera_el_almacenamiento(html):
    inicio = html.index("function passesOtherFilters")
    cuerpo = html[inicio : html.index("function passesFilter")]
    assert "state.soloAlmacenamiento" in cuerpo
    assert "d.al" in cuerpo


def test_existe_el_control_del_filtro(html):
    assert 'id="soloAlmacenamiento"' in html
    assert 'id="almacenamientoCount"' in html


def test_clear_filters_resetea_el_almacenamiento(html):
    inicio = html.index("document.getElementById('clearFilters')")
    cuerpo = html[inicio : inicio + 900]
    assert "soloAlmacenamiento" in cuerpo


def test_refresh_actualiza_el_contador(html):
    inicio = html.index("function refresh()")
    cuerpo = html[inicio : html.index("// ---------- table view ----------")]
    assert "updateAlmacenamientoCount()" in cuerpo
