import json
from pathlib import Path

import pytest

from scripts.inject import (
    InjectError,
    actualizar_fecha_footer,
    escribir_atomico,
    leer_data,
    leer_html,
    reemplazar_data,
)

FIXTURE = Path(__file__).parent / "fixtures" / "index_minimo.html"


def _html():
    return FIXTURE.read_text(encoding="utf-8")


def test_leer_data_devuelve_las_filas():
    filas = leer_data(_html())
    assert [f["c"] for f in filas] == ["1", "2"]


def test_reemplazar_data_cambia_solo_el_tramo_del_array():
    original = _html()
    nuevas = [{"c": "9", "e": "NUEVA", "es": "De Baja", "la": 1.0, "lo": 2.0}]
    salida = reemplazar_data(original, nuevas)

    assert leer_data(salida) == nuevas
    # Todo lo que no es el array queda intacto.
    assert 'const ESTADO_ORDER = ["Estudio solicitud", "De Baja"];' in salida
    assert "function refresh(){ return DATA.length; }" in salida
    assert salida.startswith("<!doctype html>")
    assert salida.endswith("</body></html>\n") or salida.endswith("</body></html>")


def test_reemplazar_data_preserva_el_resto_byte_a_byte():
    from scripts.inject import _limites

    original = _html()
    filas = leer_data(original)
    # Reinyectar lo mismo debe cambiar unicamente el formato del array, y el
    # resto del archivo debe seguir siendo identico.
    salida = reemplazar_data(original, filas)

    # Calcular los limites en original y salida usando el metodo real.
    inicio_orig, fin_orig = _limites(original)
    inicio_salida, fin_salida = _limites(salida)

    # Comparar todo excepto el array: prefijo + sufijo deben ser identicos.
    assert original[:inicio_orig] + original[fin_orig:] == salida[:inicio_salida] + salida[fin_salida:]


def test_reemplazar_data_no_escapa_los_acentos():
    salida = reemplazar_data(_html(), [{"c": "1", "es": "Revisión documento"}])
    assert "Revisión documento" in salida
    assert "\\u00f3" not in salida


def test_reemplazar_data_falla_si_no_encuentra_el_prefijo():
    with pytest.raises(InjectError, match="const DATA"):
        reemplazar_data("<html><body>sin data</body></html>", [])


def test_reemplazar_data_falla_si_el_array_no_parsea():
    roto = "<script>const DATA = [{'c':1,</script>"
    with pytest.raises(InjectError):
        reemplazar_data(roto, [])


def test_actualizar_fecha_footer_reemplaza_la_fecha_del_pie():
    html = (
        '<div class="sidebar-foot">Fuente: servicios.air-e.com/CREG030 '
        '&middot; Actualizado 2026-09-01</div>'
    )
    salida = actualizar_fecha_footer(html, "2026-10-05")
    assert "Actualizado 2026-10-05" in salida
    assert "2026-09-01" not in salida
    # El resto del div queda intacto.
    assert "Fuente: servicios.air-e.com/CREG030" in salida


def test_actualizar_fecha_footer_falla_si_no_encuentra_el_footer():
    with pytest.raises(InjectError, match="sidebar-foot"):
        actualizar_fecha_footer("<html><body>sin footer</body></html>", "2026-10-05")


def test_escribir_atomico_no_deja_temporales(tmp_path):
    destino = tmp_path / "index.html"
    destino.write_text("viejo", encoding="utf-8")
    escribir_atomico(destino, "nuevo")
    assert destino.read_text(encoding="utf-8") == "nuevo"
    assert list(tmp_path.iterdir()) == [destino]


def test_reemplazar_data_preserva_crlf(tmp_path):
    """Regresion: verificar que CRLF se preserve a traves del ciclo completo.

    El archivo real tiene 993 CRLF y zero LF solitarios. Una lectura en modo
    universal-newlines colapsaria \\r\\n a \\n, rompiendo la promesa de que
    todo fuera del array queda intacto.
    """
    # Crear HTML con CRLF explícitos.
    html_con_crlf = (
        "<!doctype html>\r\n"
        "<html><body>\r\n"
        "<script>\r\n"
        'const DATA = [{"c":"1","e":"ACME","es":"Estudio solicitud"}];\r\n'
        "const ESTADO_ORDER = [];\r\n"
        "</script>\r\n"
        "</body></html>"
    )

    # Escribir con newline="" para preservar CRLF.
    archivo = tmp_path / "con_crlf.html"
    archivo.write_text(html_con_crlf, encoding="utf-8", newline="")

    # Contar CRLF en el original.
    original_bytes = archivo.read_bytes()
    crlf_count_original = original_bytes.count(b"\r\n")
    assert crlf_count_original > 0, "El fixture debe tener al menos un CRLF"

    # Leer con leer_html, reemplazar, escribir.
    html = leer_html(archivo)
    filas = leer_data(html)
    nuevas_filas = [{"c": "2", "e": "NUEVA", "es": "De Baja"}]
    salida = reemplazar_data(html, nuevas_filas)
    escribir_atomico(archivo, salida)

    # Verificar que los CRLF se preservaron.
    resultado_bytes = archivo.read_bytes()
    crlf_count_resultado = resultado_bytes.count(b"\r\n")
    assert crlf_count_resultado == crlf_count_original, (
        f"CRLF destruidos: {crlf_count_original} -> {crlf_count_resultado}"
    )
