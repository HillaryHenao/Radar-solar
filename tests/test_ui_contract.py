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


def test_la_ficha_muestra_el_almacenamiento(html):
    inicio = html.index("function selectPoint")
    cuerpo = html[inicio : html.index("document.getElementById('detailClose')")]
    assert "Almacenamiento" in cuerpo
    assert "almacenamientoTexto" in cuerpo


def test_almacenamiento_texto_distingue_sin_dato(html):
    inicio = html.index("function almacenamientoTexto")
    cuerpo = html[inicio : inicio + 400]
    assert "Sin dato" in cuerpo
    # 'No' solo debe salir cuando al es exactamente false, no cuando es null.
    assert "=== false" in cuerpo or "===false" in cuerpo


def test_existe_la_seccion_de_analisis(html):
    assert "almacenamiento-section" in html
    assert 'id="almbody"' in html
    assert 'id="almcnt"' in html
    assert 'id="almkwh"' in html


def test_la_tabla_de_analisis_tiene_las_nueve_columnas(html):
    inicio = html.index("almacenamiento-section")
    cuerpo = html[inicio : inicio + 1800]
    for columna in ("Código", "Empresa", "Cliente", "Municipio",
                    "Tipo de generación", "Estado air-e", "Estado Sheet",
                    "Fecha solicitud", "Capacidad"):
        assert columna in cuerpo, columna


def test_render_almacenamiento_se_llama_desde_refresh(html):
    inicio = html.index("function refresh()")
    cuerpo = html[inicio : html.index("// ---------- table view ----------")]
    # No puede depender de renderAnalysis: esa funcion tiene un return temprano
    # cuando no hay cambios de estado.
    assert "renderAlmacenamiento()" in cuerpo


def test_render_almacenamiento_ordena_por_capacidad(html):
    inicio = html.index("function renderAlmacenamiento")
    cuerpo = html[inicio : inicio + 2200]
    assert "sort" in cuerpo
    assert "b.ak" in cuerpo or "ak - a.ak" in cuerpo.replace(" ", "")


def test_render_almacenamiento_tiene_estado_vacio(html):
    inicio = html.index("function renderAlmacenamiento")
    cuerpo = html[inicio : inicio + 2200]
    assert "alm-empty" in cuerpo
