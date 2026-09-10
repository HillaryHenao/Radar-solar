import json
from pathlib import Path

import pytest

from scripts.inject import (
    InjectError,
    escribir_atomico,
    leer_data,
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
    original = _html()
    filas = leer_data(original)
    # Reinyectar lo mismo debe cambiar unicamente el formato del array, y el
    # resto del archivo debe seguir siendo identico.
    salida = reemplazar_data(original, filas)
    marcador = "const DATA = "
    assert original[: original.index(marcador)] == salida[: salida.index(marcador)]
    cola_original = original[original.index("const ESTADO_ORDER") :]
    cola_salida = salida[salida.index("const ESTADO_ORDER") :]
    assert cola_original == cola_salida


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


def test_escribir_atomico_no_deja_temporales(tmp_path):
    destino = tmp_path / "index.html"
    destino.write_text("viejo", encoding="utf-8")
    escribir_atomico(destino, "nuevo")
    assert destino.read_text(encoding="utf-8") == "nuevo"
    assert list(tmp_path.iterdir()) == [destino]
