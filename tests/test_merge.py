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
    # Valores hostiles en el snapshot: si algun refactor futuro mezclara con
    # algo como `{**actual, **fresco}`, esto fallaria. `_snap()` normal no
    # incluye e/se/p/un/b, asi que no puede detectar esa regresion.
    filas, _ = _fusionar(
        [_actual()],
        [_snap(e="WRONG", se="X", p="Y", un=True, b="sept99")],
    )
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


def test_al_y_ak_frescos_reemplazan_los_de_una_corrida_anterior():
    # A partir de la segunda corrida, `actual` ya trae al/ak escritos por una
    # fusion previa (este pipeline los guarda en index.html). Si el
    # almacenamiento cambio en air-e -evento normal-, la fusion debe seguir
    # el valor fresco del snapshot, no quedarse con el viejo.
    filas, _ = _fusionar(
        [_actual(al=False, ak=0.0)],
        [_snap(al=True, ak=250.0)],
    )
    assert filas[0]["al"] is True
    assert filas[0]["ak"] == 250.0


def test_huerfano_conserva_su_al_y_ak_si_ya_los_tenia():
    # Regresion de F8 (round 3): setear al/ak sin condicion en una fila
    # huerfana borraria en silencio el almacenamiento real de un registro que
    # cae en sin_contraparte en una segunda corrida. El test de
    # uniformidad de claves no lo detecta porque su fixture no trae al/ak.
    actuales = [_actual(c=str(i)) for i in range(100)]
    actuales[99]["al"] = True
    actuales[99]["ak"] = 250.0
    snapshot = [_snap(c=str(i)) for i in range(99)]  # falta "99"
    filas, informe = _fusionar(actuales, snapshot, total_minimo=1)
    assert informe["sin_contraparte"] == ["99"]
    huerfano = next(f for f in filas if f["c"] == "99")
    assert huerfano["al"] is True
    assert huerfano["ak"] == 250.0


def test_conserva_el_registro_ausente_del_snapshot():
    # Lote de 100 con un solo faltante (1%, justo en el umbral de la guarda
    # de sin contraparte, no por encima) para poder verificar la conservacion
    # sin disparar esa guarda.
    actuales = [_actual(c=str(i)) for i in range(100)]
    snapshot = [_snap(c=str(i)) for i in range(99)]  # falta "99"
    filas, informe = _fusionar(actuales, snapshot, total_minimo=1)
    assert len(filas) == 100
    assert informe["sin_contraparte"] == ["99"]
    conservada = next(f for f in filas if f["c"] == "99")
    assert conservada["cl"] == "Cliente Viejo"


def test_nunca_elimina_registros():
    # Varios faltantes (2 de 300, bajo el umbral de sin contraparte) para
    # confirmar que ninguno desaparece de la salida.
    actuales = [_actual(c=str(i)) for i in range(300)]
    snapshot = [_snap(c=str(i)) for i in range(298)]  # faltan "298" y "299"
    filas, _ = _fusionar(actuales, snapshot, total_minimo=1)
    assert {f["c"] for f in filas} == {str(i) for i in range(300)}


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
    # Un alta con una clave de menos o de mas rompe el JS en runtime, no en
    # build time: hay que fijarlo con un test.
    assert set(nueva) == set(filas[0])


def test_falla_si_un_alta_no_tiene_empresa_asignada():
    alta = _snap(c="99999", al=True, ak=100.0, ci="FONSECA")
    with pytest.raises(MergeError, match="99999"):
        _fusionar([_actual()], [_snap(), alta])


def test_reporta_el_candidato_excluido_por_la_regla():
    borde = _snap(c="21489", al=True, ak=5.0,
                  tg="AGPE menor igual 1MVA y mayor 0.1MVA", ci="BARRANQUILLA")
    _, informe = _fusionar([_actual()], [_snap(), borde])
    assert [c["c"] for c in informe["candidatos_excluidos"]] == ["21489"]


def test_no_reporta_diferencias_de_punto_flotante_en_coordenadas():
    # La BD guarda algunas coordenadas sin redondear; el snapshot ya llega
    # redondeado. round(10.913179999999999, 5) == round(10.91318, 5), asi que
    # esto no debe aparecer como un cambio, aunque si se escriba el valor
    # nuevo.
    filas, informe = _fusionar(
        [_actual(la=10.913179999999999, lo=-74.5, cl="Cliente Viejo")],
        [_snap(la=10.91318, lo=-74.5, cl="Cliente Viejo")],
    )
    assert filas[0]["la"] == 10.91318
    assert informe["cambios"] == []


def test_si_reporta_un_cambio_real_de_coordenadas():
    filas, informe = _fusionar(
        [_actual(la=10.0, lo=-74.0, cl="Cliente Viejo")],
        [_snap(la=10.5, lo=-74.5, cl="Cliente Viejo")],
    )
    assert filas[0]["la"] == 10.5
    assert filas[0]["lo"] == -74.5
    assert {"la", "lo"} <= {c["campo"] for c in informe["cambios"]}


def test_reporta_almacenamiento_incoherente():
    raro = _snap(c="362", al=True, ak=0.0, tg="AGPE menor igual 0.1MVA")
    _, informe = _fusionar([_actual()], [_snap(), raro])
    assert informe["almacenamiento_incoherente"] == ["362"]


# ---------- guardas ----------

def test_guarda_conteo_aborta_si_falta_algun_registro():
    with pytest.raises(MergeError, match="conteo"):
        _fusionar([_actual()], [_snap()], total_minimo=5)


def test_guarda_no_eliminacion_es_independiente_del_piso_de_conteo():
    # Invariante directa ("nunca se elimina un registro"), probada contra
    # _valida_guardas directamente: por construccion, fusionar() nunca puede
    # producir menos filas que actuales (cada actual siempre agrega
    # exactamente una fila), asi que esta guarda es defensiva ante un futuro
    # refactor, no alcanzable hoy a traves de la API publica de fusionar().
    # Con DATA creciendo mas alla de TOTAL_MINIMO, el piso estatico ya no
    # detectaria una perdida de registros; esta invariante si.
    from scripts.merge import _valida_guardas

    informe = {"sin_contraparte": [], "deriva_estados": 0.0}
    with pytest.raises(MergeError, match="no eliminacion"):
        _valida_guardas(
            filas=[{"c": "1", "es": "Estudio solicitud", "ci": "ARACATACA",
                    "la": 1.0, "lo": 1.0}],
            informe=informe,
            estados_conocidos=ESTADOS,
            municipios_conocidos=MUNICIPIOS,
            total_minimo=1,
            total_actuales=2,
        )


def test_guarda_sin_contraparte_aborta_pull_fallido():
    # Un pull vacio deja todo en sin_contraparte: deriva 0.0, coordenadas y
    # estados intactos, conteo sin perdidas. Sin esta guarda el build
    # "exitoso" reescribiria el archivo sin ningun dato nuevo (F5).
    actuales = [_actual(c=str(i)) for i in range(100)]
    with pytest.raises(MergeError, match="sin contraparte"):
        _fusionar(actuales, [], total_minimo=1)


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


def test_guarda_deriva_usa_el_denominador_correcto_con_snapshot_parcial():
    # 1000 actuales, 9 sin contraparte (0.9%, bajo el umbral de la guarda de
    # sin contraparte) y 50 movimientos entre los 991 que si se compararon.
    # Con el denominador viejo (len(actuales)): 50/1000 = 5.0%, justo en el
    # umbral, no dispara. Con el denominador correcto (solo comparados):
    # 50/991 = 5.05%, si dispara. Ninguno de los dos tests de deriva
    # existentes distingue esto porque usan cobertura completa, donde ambos
    # denominadores son numericamente identicos.
    actuales = [_actual(c=str(i)) for i in range(1000)]
    snapshot = [_snap(c=str(i)) for i in range(991)]
    for i in range(50):
        snapshot[i]["es"] = "Pendiente documento"
    with pytest.raises(MergeError, match="deriva de estados"):
        _fusionar(actuales, snapshot, total_minimo=1)


def test_guarda_coordenadas_aborta_si_falta_una():
    with pytest.raises(MergeError, match="coordenadas"):
        _fusionar([_actual()], [_snap(la=None)])


def test_guarda_estados_conocidos_aborta_con_un_estado_nuevo():
    # Lote de 100 con una sola anomalia -como en los tests de deriva- para que
    # este test ejercite especificamente la guarda de estados conocidos sin
    # depender de en que orden se evaluen las guardas entre si.
    actuales = [_actual(c=str(i)) for i in range(100)]
    snapshot = [_snap(c=str(i)) for i in range(100)]
    snapshot[0]["es"] = "Normalizado"
    with pytest.raises(MergeError, match="Normalizado"):
        _fusionar(actuales, snapshot, total_minimo=1)


def test_la_guarda_de_estados_gana_a_la_de_deriva():
    # Un estado desconocido ES la causa de la deriva (un registro que migra a
    # un estado que la UI no conoce cuenta como cambio de estado), no un
    # problema aparte. Cuando ambas condiciones son ciertas a la vez -aqui,
    # 50% de deriva y un estado desconocido- el diagnostico especifico y
    # accionable debe ganarle a la alarma generica de deriva.
    actuales = [_actual(c=str(i)) for i in range(100)]
    snapshot = [_snap(c=str(i)) for i in range(100)]
    for i in range(50):
        snapshot[i]["es"] = "Normalizado"
    with pytest.raises(MergeError, match="Normalizado") as excinfo:
        _fusionar(actuales, snapshot, total_minimo=1)
    assert "deriva de estados" not in str(excinfo.value)


def test_guarda_municipios_aborta_con_ciudad_sin_departamento():
    with pytest.raises(MergeError, match="DEPT_MAP"):
        _fusionar([_actual()], [_snap(ci="EL PI¿ON")])


def test_todas_las_filas_de_salida_tienen_el_mismo_conjunto_de_claves():
    # Con un snapshot parcial, las filas huerfanas (sin contraparte) deben
    # tener las mismas claves que las fusionadas -incluyendo al/ak- o la
    # salida mezcla dos formas de fila distintas (F8).
    actuales = [_actual(c=str(i)) for i in range(100)]
    snapshot = [_snap(c=str(i)) for i in range(99)]  # falta "99"
    filas, _ = _fusionar(actuales, snapshot, total_minimo=1)
    claves = {frozenset(f.keys()) for f in filas}
    assert len(claves) == 1
    huerfana = next(f for f in filas if f["c"] == "99")
    assert huerfana["al"] is None
    assert huerfana["ak"] == 0.0


def test_campos_de_aire_y_campos_propios_son_disjuntos():
    # Redundante con el assert a nivel de modulo en scripts/merge.py, pero
    # documenta la invariante: si un futuro edit agrega "e" a CAMPOS_DE_AIRE,
    # se borrarian en silencio 1,586 empresas sin este test (ni el assert de
    # import) fallando de forma visible en la suite.
    from scripts.merge import CAMPOS_DE_AIRE, CAMPOS_PROPIOS

    assert not set(CAMPOS_DE_AIRE) & set(CAMPOS_PROPIOS)


def test_render_reporte_declara_los_bloques():
    _, informe = _fusionar([_actual()], [_snap()])
    texto = render_reporte(informe)
    assert "# Reporte de cambios" in texto
    assert "Cliente Nuevo" in texto
    assert "Deriva de estados" in texto
