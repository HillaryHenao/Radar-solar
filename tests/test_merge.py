import pytest

from scripts.merge import (
    MergeError,
    es_alta,
    fusionar,
    render_reporte,
)

ESTADOS = {"Estudio solicitud", "Pendiente documento", "Revisión documento", "De Baja"}
MUNICIPIOS = {"ARACATACA", "FONSECA", "CIENAGA", "BARRANQUILLA"}


def _actual(**extra):
    base = {
        "c": "1", "e": "ACME", "cl": "Cliente Viejo", "p": "PROY_X",
        "ci": "ARACATACA", "co": "ARACATACA", "ve": "RURAL",
        "f": "2024-01-01 10:00", "es": "Estudio solicitud",
        "t": "Solar FV", "tg": "GD menor igual 0.1MVA",
        "la": 10.5, "lo": -74.5, "se": "ECS en proceso", "un": False, "b": "sept1",
    }
    base.update(extra)
    return base


def _snap(**extra):
    base = {
        "c": "1", "f": "2024-01-01 10:00", "es": "Estudio solicitud",
        "cl": "Cliente Nuevo", "ci": "ARACATACA", "co": "ARACATACA",
        "ve": "RURAL", "t": "Solar FV", "tg": "GD menor igual 0.1MVA",
        "la": 10.5, "lo": -74.5, "al": False, "ak": 0.0, "pac": 100.0,
    }
    base.update(extra)
    return base


def _fusionar(actuales, snapshot, **kw):
    return fusionar(
        actuales, snapshot,
        estados_conocidos=kw.get("estados", ESTADOS),
        municipios_conocidos=kw.get("municipios", MUNICIPIOS),
        total_minimo=kw.get("total_minimo", 1),
    )


def test_preserva_los_campos_propios_de_la_bd():
    filas, _ = _fusionar([_actual()], [_snap()])
    fila = filas[0]
    assert fila["e"] == "ACME"
    assert fila["se"] == "ECS en proceso"
    assert fila["p"] == "PROY_X"
    assert fila["un"] is False
    assert fila["b"] == "sept1"


def test_sobrescribe_los_campos_de_aire():
    filas, informe = _fusionar([_actual()], [_snap()])
    assert filas[0]["cl"] == "Cliente Nuevo"
    assert {c["campo"] for c in informe["cambios"]} == {"cl"}


def test_agrega_al_y_ak():
    filas, _ = _fusionar([_actual()], [_snap(al=True, ak=250.0)])
    assert filas[0]["al"] is True
    assert filas[0]["ak"] == 250.0


def test_conserva_el_registro_ausente_del_snapshot():
    filas, informe = _fusionar([_actual(c="1"), _actual(c="2")], [_snap(c="1")])
    assert len(filas) == 2
    assert informe["sin_contraparte"] == ["2"]
    conservada = next(f for f in filas if f["c"] == "2")
    assert conservada["cl"] == "Cliente Viejo"


def test_nunca_elimina_registros():
    filas, _ = _fusionar([_actual(c="1"), _actual(c="2")], [])
    assert {f["c"] for f in filas} == {"1", "2"}


def test_es_alta_solo_para_gd_con_almacenamiento():
    assert es_alta({"al": True, "tg": "GD menor igual 0.1MVA"}) is True
    assert es_alta({"al": True, "tg": "AGPE menor igual 0.1MVA"}) is False
    assert es_alta({"al": True, "tg": "AGPE menor igual 1MVA y mayor 0.1MVA"}) is False
    assert es_alta({"al": False, "tg": "GD menor igual 0.1MVA"}) is False
    assert es_alta({"al": None, "tg": "GD menor igual 0.1MVA"}) is False


def test_incorpora_el_alta_con_sus_campos_propios(monkeypatch):
    from scripts import merge

    monkeypatch.setitem(merge.EMPRESAS_ALTAS, "25857", "GECELCA")
    alta = _snap(c="25857", al=True, ak=6517.0, ci="FONSECA", cl="GECELCA S.A. E.S.P")
    filas, informe = _fusionar([_actual()], [_snap(), alta])

    nueva = next(f for f in filas if f["c"] == "25857")
    assert nueva["e"] == "GECELCA"
    assert nueva["se"] == ""
    assert nueva["p"] == ""
    assert nueva["un"] is False
    assert nueva["b"] == "sept10"
    assert nueva["ak"] == 6517.0
    assert informe["altas"] == ["25857"]


def test_falla_si_un_alta_no_tiene_empresa_asignada():
    alta = _snap(c="99999", al=True, ak=100.0, ci="FONSECA")
    with pytest.raises(MergeError, match="99999"):
        _fusionar([_actual()], [_snap(), alta])


def test_reporta_el_candidato_excluido_por_la_regla():
    borde = _snap(c="21489", al=True, ak=5.0,
                  tg="AGPE menor igual 1MVA y mayor 0.1MVA", ci="BARRANQUILLA")
    _, informe = _fusionar([_actual()], [_snap(), borde])
    assert [c["c"] for c in informe["candidatos_excluidos"]] == ["21489"]


def test_reporta_almacenamiento_incoherente():
    raro = _snap(c="362", al=True, ak=0.0, tg="AGPE menor igual 0.1MVA")
    _, informe = _fusionar([_actual()], [_snap(), raro])
    assert informe["almacenamiento_incoherente"] == ["362"]


# ---------- guardas ----------

def test_guarda_conteo_aborta_si_falta_algun_registro():
    with pytest.raises(MergeError, match="conteo"):
        _fusionar([_actual()], [_snap()], total_minimo=5)


def test_guarda_deriva_aborta_sobre_el_5_por_ciento():
    actuales = [_actual(c=str(i)) for i in range(100)]
    snapshot = [_snap(c=str(i), es="Pendiente documento") for i in range(100)]
    with pytest.raises(MergeError, match="deriva de estados"):
        _fusionar(actuales, snapshot, total_minimo=1)


def test_guarda_deriva_permite_un_movimiento_normal():
    actuales = [_actual(c=str(i)) for i in range(100)]
    snapshot = [_snap(c=str(i)) for i in range(100)]
    snapshot[0]["es"] = "Pendiente documento"
    filas, informe = _fusionar(actuales, snapshot, total_minimo=1)
    assert informe["deriva_estados"] == pytest.approx(0.01)


def test_guarda_coordenadas_aborta_si_falta_una():
    with pytest.raises(MergeError, match="coordenadas"):
        _fusionar([_actual()], [_snap(la=None)])


def test_guarda_estados_conocidos_aborta_con_un_estado_nuevo():
    # Con un solo registro, cambiar "es" dispara la guarda de deriva (100%)
    # antes de llegar a la guarda de estados conocidos. Se usa un lote de 100
    # con una sola anomalia -como en los tests de deriva- para mantener la
    # deriva bajo el umbral y ejercitar especificamente esta guarda.
    actuales = [_actual(c=str(i)) for i in range(100)]
    snapshot = [_snap(c=str(i)) for i in range(100)]
    snapshot[0]["es"] = "Normalizado"
    with pytest.raises(MergeError, match="Normalizado"):
        _fusionar(actuales, snapshot, total_minimo=1)


def test_guarda_municipios_aborta_con_ciudad_sin_departamento():
    with pytest.raises(MergeError, match="DEPT_MAP"):
        _fusionar([_actual()], [_snap(ci="EL PI¿ON")])


def test_render_reporte_declara_los_bloques():
    _, informe = _fusionar([_actual()], [_snap()])
    texto = render_reporte(informe)
    assert "# Reporte de cambios" in texto
    assert "Cliente Nuevo" in texto
    assert "Deriva de estados" in texto
