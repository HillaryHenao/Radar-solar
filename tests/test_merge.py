import pytest

from scripts.merge import (
    MergeError,
    es_alta,
    es_alta_unergy,
    es_minigranja_gd,
    fusionar,
    render_reporte,
)
from scripts.merge import _es_cliente_unergy

ESTADOS = {"Estudio solicitud", "Pendiente documento", "Revisión documento", "De Baja"}
MUNICIPIOS = {"ARACATACA", "FONSECA", "CIENAGA", "BARRANQUILLA"}


def _actual(**extra):
    base = {
        "c": "1", "e": "ACME", "cl": "Cliente Viejo", "p": "PROY_X",
        "ci": "ARACATACA", "co": "ARACATACA", "ve": "RURAL",
        "f": "2024-01-01 10:00", "es": "Estudio solicitud",
        "t": "Solar FV", "tg": "GD menor igual 0.1MVA",
        "la": 10.5, "lo": -74.5, "se": "ECS en proceso", "un": False, "b": "sept1",
        # Mismo default que _snap(): sin esto, cada test de fusion existente
        # vería un cambio fantasma de pac (None -> 100.0) que no tiene nada
        # que ver con lo que ese test esta verificando.
        "pac": 100.0,
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


def test_registro_existente_que_pareceria_alta_unergy_conserva_sus_campos_propios():
    # Regresion para la invariante "nunca se re-clasifica un registro
    # existente": planta un actual cuyo cl/f harian match con
    # es_alta_unergy si fuera nuevo (cliente Unergy, fecha 2026), y confirma
    # que como YA esta presente, pasa por la rama de fusion (no por la de
    # altas) y sus campos propios llegan intactos, no recalculados como
    # e=UNERGY/un=True. El bucle de fusion lo garantiza estructuralmente
    # (solo mira `snapshot` para altas cuando el codigo no esta en
    # `presentes`), pero ese hecho no era evidente leyendo solo los tests.
    actual = _actual(
        c="1", e="ACME", cl="Unergy Energía Digital S.A.S", p="PROY_X",
        se="ECS en proceso", un=False, b="sept1",
    )
    fresco = _snap(c="1", cl="Unergy Energía Digital S.A.S", f="2026-03-01 00:00")
    assert es_alta_unergy(fresco) is True  # si fuera nuevo, calificaria

    filas, _ = _fusionar([actual], [fresco])
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


def test_agrega_pac_desde_air_e():
    # `pac` (potencia AC) se agrego a CAMPOS_DE_AIRE para que el filtro de
    # potencia en la UI tenga un numero real que mostrar, no solo el `tg` de
    # air-e (que resulto no ser confiable como indicador de tamano).
    filas, informe = _fusionar([_actual(pac=100.0)], [_snap(pac=960.0)])
    assert filas[0]["pac"] == 960.0
    assert {"pac"} <= {c["campo"] for c in informe["cambios"]}


def test_huerfano_conserva_su_pac_si_ya_lo_tenia():
    # Mismo patron que al/ak: un huerfano sin contraparte en el snapshot no
    # debe perder un pac que ya tenia de una fusion anterior.
    actuales = [_actual(c=str(i), pac=100.0) for i in range(100)]
    actuales[99]["pac"] = 6200.0
    snapshot = [_snap(c=str(i)) for i in range(99)]  # falta "99"
    filas, informe = _fusionar(actuales, snapshot, total_minimo=1)
    assert informe["sin_contraparte"] == ["99"]
    huerfano = next(f for f in filas if f["c"] == "99")
    assert huerfano["pac"] == 6200.0


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
    # Lote de 100 con un solo faltante, bien bajo el tope absoluto de la
    # guarda de sin contraparte, para poder verificar la conservacion sin
    # disparar esa guarda.
    actuales = [_actual(c=str(i)) for i in range(100)]
    snapshot = [_snap(c=str(i)) for i in range(99)]  # falta "99"
    filas, informe = _fusionar(actuales, snapshot, total_minimo=1)
    assert len(filas) == 100
    assert informe["sin_contraparte"] == ["99"]
    conservada = next(f for f in filas if f["c"] == "99")
    assert conservada["cl"] == "Cliente Viejo"


def test_nunca_elimina_registros():
    # Varios faltantes (2 de 300, bajo el tope absoluto de sin contraparte)
    # para confirmar que ninguno desaparece de la salida.
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


def test_es_alta_incluye_ag_de_escala_de_red():
    # AG menor igual 5MVA y mayor 1MVA es la clase de mayor capacidad y es
    # escala de red, igual que GD: la regla original la dejaba invisible
    # porque "AG" no empieza con "GD".
    assert es_alta(
        {"al": True, "tg": "AG menor igual 5MVA y mayor 1MVA"}
    ) is True


def test_es_alta_no_confunde_ag_con_agpe():
    # "AG " (con espacio) no debe hacer match por prefijo con "AGPE": son
    # clases opuestas, escala de red contra autogeneracion residencial.
    assert es_alta(
        {"al": True, "tg": "AGPE menor igual 1MVA y mayor 0.1MVA"}
    ) is False


def test_es_alta_unergy_acepta_cliente_unergy_desde_2026():
    assert es_alta_unergy(
        {"cl": "Unergy Energía Digital S.A.S", "f": "2026-01-01 00:00"}
    ) is True
    assert es_alta_unergy(
        {"cl": "Unergy Energía Digital S.A.S", "f": "2027-06-15 10:00"}
    ) is True


def test_es_alta_unergy_rechaza_fecha_anterior_a_2026():
    assert es_alta_unergy(
        {"cl": "Unergy Energía Digital S.A.S", "f": "2025-12-31 23:59"}
    ) is False


def test_es_alta_unergy_rechaza_cliente_no_unergy():
    assert es_alta_unergy(
        {"cl": "Otro Cliente S.A.S.", "f": "2026-05-01 00:00"}
    ) is False


def test_es_alta_unergy_es_insensible_a_mayusculas():
    assert es_alta_unergy(
        {"cl": "UNERGY ENERGIA DIGITAL S.A.S", "f": "2026-01-01 00:00"}
    ) is True
    assert es_alta_unergy(
        {"cl": "unergy energia digital s.a.s", "f": "2026-01-01 00:00"}
    ) is True


def test_es_alta_unergy_no_hace_match_de_substring_dentro_de_otra_palabra():
    # "unergy" como substring de un nombre mas largo no debe contar: el
    # cliente real es otro, no Unergy. `\bunergy\b` exige que sea una
    # palabra completa; un `in` sin anclar haria match aqui por error.
    assert es_alta_unergy(
        {"cl": "Grupo Munergystore S.A.S", "f": "2026-05-01 00:00"}
    ) is False
    assert _es_cliente_unergy("Grupo Munergystore S.A.S") is False


def test_es_minigranja_gd_acepta_el_cluster_de_potencia_desde_2025():
    assert es_minigranja_gd(
        {"tg": "GD menor igual 0.1MVA", "pac": 990.0, "f": "2025-03-01 00:00"}
    ) is True
    assert es_minigranja_gd(
        {"tg": "GD menor igual 0.1MVA", "pac": 900.0, "f": "2026-01-01 00:00"}
    ) is True
    assert es_minigranja_gd(
        {"tg": "GD menor igual 0.1MVA", "pac": 1100.0, "f": "2025-01-01 00:00"}
    ) is True


def test_es_minigranja_gd_rechaza_fuera_del_rango_de_potencia():
    assert es_minigranja_gd(
        {"tg": "GD menor igual 0.1MVA", "pac": 899.9, "f": "2025-03-01 00:00"}
    ) is False
    assert es_minigranja_gd(
        {"tg": "GD menor igual 0.1MVA", "pac": 1100.1, "f": "2025-03-01 00:00"}
    ) is False


def test_es_minigranja_gd_rechaza_fecha_anterior_a_2025():
    assert es_minigranja_gd(
        {"tg": "GD menor igual 0.1MVA", "pac": 1000.0, "f": "2024-12-31 23:59"}
    ) is False


def test_es_minigranja_gd_rechaza_ag_y_agpe():
    # Solo generador distribuido: "AG " y "AGPE" son autogeneracion, no la
    # clase que se pidio incorporar.
    assert es_minigranja_gd(
        {"tg": "AG menor igual 5MVA y mayor 1MVA", "pac": 1000.0, "f": "2025-06-01 00:00"}
    ) is False
    assert es_minigranja_gd(
        {"tg": "AGPE menor igual 1MVA y mayor 0.1MVA", "pac": 1000.0, "f": "2025-06-01 00:00"}
    ) is False


def test_incorpora_alta_unergy_con_sus_campos_propios():
    # A diferencia de la alta por almacenamiento, esta no pasa por
    # EMPRESAS_ALTAS: `tg` es AGPE (la regla de almacenamiento la excluye) y
    # `al` no interviene para nada en esta regla.
    alta = _snap(
        c="30001", cl="Unergy Energía Digital S.A.S", f="2026-03-15 09:00",
        tg="AGPE menor igual 1MVA y mayor 0.1MVA",
    )
    filas, informe = _fusionar([_actual()], [_snap(), alta])

    nueva = next(f for f in filas if f["c"] == "30001")
    assert nueva["e"] == "UNERGY"
    assert nueva["se"] == ""
    assert nueva["p"] == ""
    assert nueva["un"] is True
    assert nueva["b"] == "sept10"
    assert informe["altas_unergy"] == ["30001"]
    # Misma forma de fila que las fusionadas, o el JS rompe en runtime.
    assert set(nueva) == set(filas[0])


def test_alta_unergy_no_requiere_empresa_asignada_en_empresas_altas():
    # EMPRESAS_ALTAS es exclusivo de la regla de almacenamiento: un codigo de
    # Unergy 2026 sin entrada ahi no debe hacer fallar el build.
    from scripts.merge import EMPRESAS_ALTAS

    alta = _snap(c="30002", cl="Unergy Energía Digital S.A.S", f="2026-01-01 00:00")
    assert "30002" not in EMPRESAS_ALTAS

    filas, informe = _fusionar([_actual()], [_snap(), alta])
    assert informe["altas_unergy"] == ["30002"]
    assert next(f for f in filas if f["c"] == "30002")["e"] == "UNERGY"


def test_reglas_de_almacenamiento_y_de_cliente_unergy_coexisten(monkeypatch):
    # Una fila cumple solo la regla de almacenamiento (y por eso si necesita
    # EMPRESAS_ALTAS); la otra cumple solo la de cliente Unergy (y por eso no
    # la necesita). Las dos deben incorporarse, cada una por su propio camino.
    from scripts import merge

    monkeypatch.setitem(merge.EMPRESAS_ALTAS, "25857", "GECELCA")
    alta_almacenamiento = _snap(
        c="25857", al=True, ak=6517.0, ci="FONSECA", cl="GECELCA S.A. E.S.P",
    )
    alta_unergy = _snap(
        c="30003", cl="Unergy Energía Digital S.A.S", f="2026-02-01 00:00",
        tg="AGPE menor igual 1MVA y mayor 0.1MVA",
    )
    filas, informe = _fusionar(
        [_actual()], [_snap(), alta_almacenamiento, alta_unergy],
    )

    assert informe["altas"] == ["25857"]
    assert informe["altas_unergy"] == ["30003"]
    fila_gecelca = next(f for f in filas if f["c"] == "25857")
    fila_unergy = next(f for f in filas if f["c"] == "30003")
    assert fila_gecelca["e"] == "GECELCA" and fila_gecelca["un"] is False
    assert fila_unergy["e"] == "UNERGY" and fila_unergy["un"] is True


def test_registro_que_cumple_ambas_reglas_se_incorpora_como_unergy_una_sola_vez():
    # El caso que importaba corregir: un proyecto grande (GD, con
    # almacenamiento -cumple es_alta) que ademas es cliente Unergy desde 2026
    # (cumple es_alta_unergy). Con un if/elif por orden de regla, es_alta
    # ganaba y el registro perdia un=True/e=UNERGY y exigia una entrada en
    # EMPRESAS_ALTAS que no tiene sentido para un cliente ya identificado.
    # No se toca EMPRESAS_ALTAS: si esto fallara pidiendo una entrada ahi,
    # la regresion volvio.
    ambas = _snap(
        c="30004", cl="Unergy Energía Digital S.A.S", f="2026-04-01 00:00",
        al=True, ak=500.0, tg="GD menor igual 0.1MVA",
    )
    filas, informe = _fusionar([_actual()], [_snap(), ambas])

    coincidencias = [f for f in filas if f["c"] == "30004"]
    assert len(coincidencias) == 1
    nueva = coincidencias[0]
    assert nueva["un"] is True
    assert nueva["e"] == "UNERGY"
    assert informe["altas_unergy"] == ["30004"]
    assert informe["altas"] == []


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


def test_incorpora_minigranja_con_empresa_derivada_del_cliente():
    # A diferencia de la regla de almacenamiento, esta no exige EMPRESAS_ALTAS
    # ni almacenamiento: la empresa es el propio `cl` que manda air-e.
    minigranja = _snap(
        c="40001", cl="Javier Oliveros", f="2025-06-01 00:00",
        tg="GD menor igual 0.1MVA", pac=1000.0,
    )
    filas, informe = _fusionar([_actual()], [_snap(), minigranja])

    nueva = next(f for f in filas if f["c"] == "40001")
    assert nueva["e"] == "Javier Oliveros"
    assert nueva["un"] is False
    assert nueva["se"] == ""
    assert nueva["p"] == ""
    assert informe["altas_minigranja"] == ["40001"]
    assert set(nueva) == set(filas[0])


def test_minigranja_no_requiere_empresa_asignada_en_empresas_altas():
    from scripts.merge import EMPRESAS_ALTAS

    minigranja = _snap(
        c="40002", cl="Persona Natural Cualquiera", f="2025-01-15 00:00",
        tg="GD menor igual 0.1MVA", pac=960.0,
    )
    assert "40002" not in EMPRESAS_ALTAS

    filas, informe = _fusionar([_actual()], [_snap(), minigranja])
    assert informe["altas_minigranja"] == ["40002"]
    assert next(f for f in filas if f["c"] == "40002")["e"] == (
        "Persona Natural Cualquiera"
    )


def test_minigranja_con_almacenamiento_y_empresa_conocida_usa_empresas_altas(monkeypatch):
    # Overlap real en los datos: un registro puede cumplir la regla de
    # minigranja (GD, ~1MW, desde 2025) y ademas la de almacenamiento
    # (es_alta). Cuando ya tiene empresa asignada a mano, esa asignacion debe
    # ganar sobre el nombre del cliente, para no perder la curaduria manual.
    from scripts import merge

    monkeypatch.setitem(merge.EMPRESAS_ALTAS, "40003", "GECELCA")
    ambas = _snap(
        c="40003", cl="Generadora Cliente S.A.S", f="2025-09-01 00:00",
        tg="GD menor igual 0.1MVA", pac=1000.0, al=True, ak=6200.0,
    )
    filas, informe = _fusionar([_actual()], [_snap(), ambas])

    nueva = next(f for f in filas if f["c"] == "40003")
    assert nueva["e"] == "GECELCA"
    assert informe["altas"] == ["40003"]
    assert informe["altas_minigranja"] == []


def test_minigranja_de_cliente_unergy_antes_de_2026_se_incorpora_como_unergy():
    # Cliente Unergy con fecha 2025: no cumple es_alta_unergy (ancla 2026),
    # pero si es_minigranja_gd. Debe incorporarse por identidad de cliente
    # (e="UNERGY", un=True), no con el nombre literal como empresa.
    minigranja_unergy = _snap(
        c="40004", cl="Unergy Energía Digital S.A.S", f="2025-07-01 00:00",
        tg="GD menor igual 0.1MVA", pac=990.0,
    )
    assert es_alta_unergy(minigranja_unergy) is False

    filas, informe = _fusionar([_actual()], [_snap(), minigranja_unergy])
    nueva = next(f for f in filas if f["c"] == "40004")
    assert nueva["e"] == "UNERGY"
    assert nueva["un"] is True
    assert informe["altas_unergy"] == ["40004"]
    assert informe["altas_minigranja"] == []


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


def test_guarda_sin_contraparte_permite_hasta_el_tope():
    actuales = [_actual(c=str(i)) for i in range(10)]
    snapshot = [_snap(c=str(i)) for i in range(7)]  # faltan 3: justo en el tope
    filas, informe = _fusionar(actuales, snapshot, total_minimo=1)
    assert len(informe["sin_contraparte"]) == 3
    assert len(filas) == 10


def test_guarda_sin_contraparte_aborta_por_encima_del_tope():
    actuales = [_actual(c=str(i)) for i in range(10)]
    snapshot = [_snap(c=str(i)) for i in range(6)]  # faltan 4: sobre el tope
    with pytest.raises(MergeError, match="sin contraparte"):
        _fusionar(actuales, snapshot, total_minimo=1)


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
    # 1000 actuales, 3 sin contraparte (justo en el tope absoluto de esa
    # guarda, no por encima) y 50 movimientos entre los 997 que si se
    # compararon. Con el denominador viejo (len(actuales)): 50/1000 = 5.0%,
    # justo en el umbral, no dispara. Con el denominador correcto (solo
    # comparados): 50/997 = 5.02%, si dispara. Ninguno de los dos tests de
    # deriva existentes distingue esto porque usan cobertura completa, donde
    # ambos denominadores son numericamente identicos.
    actuales = [_actual(c=str(i)) for i in range(1000)]
    snapshot = [_snap(c=str(i)) for i in range(997)]
    for i in range(50):
        snapshot[i]["es"] = "Pendiente documento"
    with pytest.raises(MergeError, match="deriva de estados"):
        _fusionar(actuales, snapshot, total_minimo=1)


def test_guarda_coordenadas_aborta_si_falta_una():
    with pytest.raises(MergeError, match="coordenadas"):
        _fusionar([_actual()], [_snap(la=None)])


def test_guarda_coordenadas_aborta_fuera_del_caribe():
    # Registro real 11142 del universo air-e: LATITUD 1.10311 para "PUERTO
    # COLOMBIA" cae en el Amazonas, no en el Caribe. Un chequeo de "no es
    # None" no lo atraparia.
    with pytest.raises(MergeError, match="coordenadas"):
        _fusionar([_actual()], [_snap(la=1.10311, lo=-74.5)])


def test_guarda_coordenadas_aborta_con_el_centinela_cero():
    # LATITUD/LONGITUD en 0.0 es un punto valido para "is None" y pondria un
    # pin en el Golfo de Guinea sin que la guarda anterior lo notara.
    with pytest.raises(MergeError, match="coordenadas"):
        _fusionar([_actual()], [_snap(la=0.0, lo=0.0)])


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
    assert "Altas por minigranjas GD" in texto


def test_render_reporte_con_datos_reales_en_todas_las_secciones():
    # `render_reporte` solo se testeaba con un informe vacio: toda la
    # superficie de tablas quedaba sin cubrir, incluyendo dos formas de
    # crash reales si `ak` alguna vez fuera string o None: el sort hace
    # `float(x["ak"])` y la fila hace `{cand['ak']:g}`.
    informe = {
        "fecha": "2026-09-10",
        "cambios": [
            {"c": "23465", "campo": "ve", "antes": "VDA  CHARCO LATA",
             "despues": "VDA CHARCO LATA"},
        ],
        "altas": ["25857"],
        "sin_contraparte": ["999999"],
        "deriva_estados": 0.01,
        "candidatos_excluidos": [
            {"c": "23751", "tg": "AGPE menor igual 0.1MVA", "ak": 20480.0,
             "ci": "PLATO", "cl": "JOAQUIN CESAR CAMARGO MOLINA", "pac": 24.0},
            {"c": "8221", "tg": "AGPE menor igual 0.1MVA", "ak": 3000.0,
             "ci": "BARRANQUILLA", "cl": "ESTHER ZAIDA SOLIS ANDRADE", "pac": 3000.0},
            {"c": "21489", "tg": "AGPE menor igual 1MVA y mayor 0.1MVA", "ak": 5.0,
             "ci": "RIOHACHA", "cl": "PERSONA NATURAL", "pac": 10.0},
        ],
        "almacenamiento_incoherente": ["362"],
        "total": 1589,
        "universo_aire": 10641,
        "con_almacenamiento_aire": 316,
        "no_incorporado_total": 9049,
        "no_incorporado_por_tg": {"AGPE menor igual 0.1MVA": 8500, "GD menor igual 0.1MVA": 549},
        "no_incorporado_por_es": {"Estudio solicitud": 6000, "De Baja": 3049},
        "no_incorporado_por_mes": {"2026-08": 40, "2026-09": 12},
    }
    texto = render_reporte(informe)

    assert "`23465`" in texto and "VDA CHARCO LATA" in texto
    assert "`25857`" in texto and "GECELCA" in texto
    assert "`999999`" in texto
    assert "## Registros de la BD que air-e ya no devuelve" in texto
    assert "C139" in texto and "20715" in texto
    assert "`23751`" in texto and "20480" in texto
    assert "`362`" in texto
    assert "## Universo air-e no incorporado" in texto
    assert "9049" in texto
    assert "AGPE menor igual 0.1MVA" in texto and "8500" in texto
    assert "Estudio solicitud" in texto and "6000" in texto
    assert "2026-09" in texto and "12" in texto


def test_render_reporte_limita_los_cambios_mostrados():
    # El backfill de `pac` (agregarlo a CAMPOS_DE_AIRE) hace que una sola
    # corrida pueda reportar miles de cambios (None -> valor real, uno por
    # cada registro existente). Sin un tope, el reporte queda inmanejable.
    informe = {
        "fecha": "2026-09-17", "cambios": [
            {"c": str(i), "campo": "pac", "antes": None, "despues": 100.0}
            for i in range(50)
        ],
        "altas": [], "altas_unergy": [], "altas_minigranja": [],
        "sin_contraparte": [], "deriva_estados": 0.0,
        "candidatos_excluidos": [], "almacenamiento_incoherente": [],
        "total": 50, "universo_aire": 50, "con_almacenamiento_aire": 0,
        "no_incorporado_total": 0, "no_incorporado_por_tg": {},
        "no_incorporado_por_es": {}, "no_incorporado_por_mes": {},
    }
    texto = render_reporte(informe)
    assert texto.count("| `pac` |") == 40
    assert "Y 10 mas." in texto
