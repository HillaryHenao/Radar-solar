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


# ---------- clic en fila ya no navega al mapa; copiar codigo + boton de mapa ----------

def test_existe_el_helper_compartido_wire_row_actions(html):
    assert "function wireRowActions(tbody)" in html


def test_wire_row_actions_copia_el_codigo_crudo_al_portapapeles(html):
    inicio = html.index("function wireRowActions(tbody)")
    cuerpo = html[inicio : html.index("function openRankDetail(title, scopeLabel, rows){")]
    # El portapapeles recibe el codigo crudo (sin '#'), no el texto visible de la celda.
    assert "navigator.clipboard.writeText(code)" in cuerpo
    # La promesa puede rechazar (permisos, foco); debe manejarse, no fallar en silencio.
    assert ".catch(" in cuerpo
    assert "selectCellText" in cuerpo
    assert "td.code" in cuerpo
    assert ".map-btn" in cuerpo


def test_open_rank_detail_ya_no_navega_al_mapa_desde_la_fila(html):
    inicio = html.index("function openRankDetail(title, scopeLabel, rows){")
    cuerpo = html[inicio : html.index("function closeRankDetail()")]
    assert "setView('map')" not in cuerpo
    assert "wireRowActions(body)" in cuerpo
    assert 'class="map-btn"' in cuerpo


def test_render_analysis_ya_no_navega_al_mapa_desde_la_fila(html):
    inicio = html.index("function renderAnalysis(){")
    cuerpo = html[inicio : html.index("function renderAlmacenamiento(){")]
    assert "setView('map')" not in cuerpo
    assert "wireRowActions(body)" in cuerpo
    assert 'class="map-btn"' in cuerpo


def test_render_almacenamiento_ya_no_navega_al_mapa_desde_la_fila(html):
    inicio = html.index("function renderAlmacenamiento(){")
    cuerpo = html[inicio : html.index("function renderTable(){")]
    assert "setView('map')" not in cuerpo
    assert "wireRowActions(body)" in cuerpo
    assert 'class="map-btn"' in cuerpo


def test_render_table_ya_no_navega_al_mapa_desde_la_fila(html):
    inicio = html.index("function renderTable(){")
    cuerpo = html[inicio : html.index("function updateSortArrows(){")]
    assert "setView('map')" not in cuerpo
    assert "wireRowActions(body)" in cuerpo
    assert 'class="map-btn"' in cuerpo


def test_el_boton_de_mapa_tiene_titulo_y_aria_label_en_espanol(html):
    marcado = 'title="Ver esta solicitud en el mapa" aria-label="Ver esta solicitud en el mapa"'
    # Una vez por cada una de las 4 tablas (ranking, cambios de estado,
    # almacenamiento y tabla principal).
    assert html.count(marcado) == 4


def test_render_list_del_sidebar_sigue_navegando_al_seleccionar(html):
    # renderList (la lista de resultados del sidebar) queda fuera de este
    # cambio: seleccionar un resultado en la lista sigue llevando al mapa.
    inicio = html.index("function renderList(filtered){")
    cuerpo = html[inicio : html.index("function buildEstadoChips(){")]
    assert "selectPoint(d)" in cuerpo
