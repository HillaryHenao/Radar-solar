"""Fusion del snapshot de air-e con el DATA actual, guardas y reporte.

Funciones puras: sin red y sin I/O de archivos. Es la pieza donde puede haber
bugs de verdad, asi que se testea completa con fixtures.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

# Campos que air-e manda y sobrescriben lo que hay.
CAMPOS_DE_AIRE = ("f", "es", "cl", "ci", "co", "ve", "t", "tg", "la", "lo")
# Campos que solo existen en la BD y nunca se recalculan.
CAMPOS_PROPIOS = ("e", "se", "p", "un", "b")

# Si algun dia se agrega un campo a ambas listas, se sobrescribiria un campo
# propio de la BD con lo que mande air-e (el mismo desastre que revirtio
# a2cabc2). Que esto falle en el momento del edit, no en produccion.
assert not set(CAMPOS_DE_AIRE) & set(CAMPOS_PROPIOS), (
    "CAMPOS_DE_AIRE y CAMPOS_PROPIOS se solapan: un campo compartido se "
    "sobrescribiria con air-e y dejaria de ser propio de la BD."
)

# Precision de comparacion para coordenadas: la BD guarda algunas sin
# redondear (10.913179999999999) y el snapshot ya llega redondeado
# (10.91318); esa diferencia de ~1.8e-15 es ruido de punto flotante, no un
# cambio real. Se escribe igual el valor del snapshot; solo se deja de
# reportar como "cambio" en el informe.
DECIMALES_COORDENADAS = 5

# Tope absoluto (no porcentaje) de registros actuales que pueden quedar sin
# contraparte en el snapshot antes de sospechar un pull fallido o incompleto
# (F5). En datos reales este valor es 0. Un porcentaje se queda corto: al 1%
# sobre 1.589 registros tolera 15 desapariciones, y ese margen absoluto crece
# sin limite a medida que la BD crece, cuando el spec exige que esto sea 0 en
# la practica.
TOPE_SIN_CONTRAPARTE = 3

# Caja delimitadora del Caribe colombiano, con margen: cubre el territorio de
# air-e. Reemplaza un chequeo de "no es None", que no atrapa el centinela
# `0.0` (un `LATITUD: 0` pondria un pin en el Golfo de Guinea y pasaria todo).
LAT_MIN, LAT_MAX = 9.0, 12.6
LON_MIN, LON_MAX = -76.0, -71.5

# Empresa de cada alta de la regla de almacenamiento (`es_alta`). Se asigna a
# mano: son pocas, `e` alimenta el filtro y los rankings, y una heuristica
# sobre NOMBRE_CLI produciria basura. Este mecanismo es exclusivo de
# `es_alta`: la regla de cliente Unergy (`es_alta_unergy`, abajo) NUNCA
# consulta este diccionario. Son 227 codigos -no "pocas"- y su empresa ya se
# conoce de antemano porque la regla misma lo dice: no hay nada que asignar
# a mano, y si se enruta por aca el build fallaria pidiendo 227 asignaciones
# que no tienen sentido.
EMPRESAS_ALTAS: dict[str, str] = {
    "25857": "GECELCA",
    "22637": "GECELCA",
    "26761": "GREENYELLOW",
}

# Empresa derivada -no asignada a mano- para las altas de `es_alta_unergy`.
# Deliberadamente no es "GMAIL": ese es el valor partido y no confiable que
# documenta docs/notas/2026-09-10-pendiente-filtro-cliente.md, y repetirlo
# aqui solo agregaria una tercera variante mas de la misma ambiguedad.
EMPRESA_UNERGY = "UNERGY"

# Fecha desde la cual una solicitud de cliente Unergy se incorpora aunque no
# cumpla `es_alta`. Ver `es_alta_unergy` para el porque del ancla "desde".
UNERGY_DESDE = "2026-01-01"

TOTAL_MINIMO = 1816
UMBRAL_DERIVA = 0.05
BATCH_ALTAS = "sept10"


class MergeError(RuntimeError):
    """Una guarda se disparo. No se escribe nada."""


def es_alta(fila: dict) -> bool:
    """Regla de inclusion: proyectos de escala de red (GD o AG) con almacenamiento.

    "GD" y "AG " (con el espacio final) son ambos de escala de red/planta, a
    diferencia de "AGPE" (autogeneracion a pequena escala, tipicamente techo
    residencial o comercial). El espacio en "AG " es deliberado: sin el,
    `str.startswith("AG")` tambien haria match con "AGPE", justo la clase que
    se debe excluir.

    No se ancla en "cualquier cosa que no sea AGPE pequeno" porque el codigo
    21489 es AGPE 0.1-1MVA con 5 kWh y 10 kW AC a nombre de una persona: no es
    un proyecto.
    """
    tg = str(fila.get("tg", ""))
    return fila.get("al") is True and (tg.startswith("GD") or tg.startswith("AG "))


def es_alta_unergy(fila: dict) -> bool:
    """Segunda regla de inclusion: cliente Unergy con solicitud desde 2026.

    Existe porque `empresa` (`e`) no sirve para contar "proyectos de Unergy":
    es la cuenta que radico ante air-e, no el dueño del proyecto, y esta
    partida para el mismo cliente (168 registros dicen `GMAIL`, otros dicen
    `Unergy Energia Digital S.A.S`). `cliente` (`cl`), en cambio, viene de
    air-e sin ambiguedad y cubre el universo completo.

    Se ancla en "fecha de solicitud >= 2026-01-01", no en "el anio de la
    fecha es 2026", para que la regla se automantenga: cuando llegue 2027 esos
    proyectos entran solos, sin que alguien tenga que volver a este archivo
    cada fin de anio a correr el ancla. La comparacion de strings alcanza
    porque `f` siempre llega en formato `YYYY-MM-DD HH:mm` (orden lexico ==
    orden cronologico para ese formato).

    Deliberadamente independiente de `es_alta`: una solicitud puede cumplir
    esta regla sin cumplir la de almacenamiento (de hecho, los 227 conocidos
    son todos `AGPE menor igual 1MVA y mayor 0.1MVA`, la clase que `es_alta`
    excluye).
    """
    cliente = str(fila.get("cl", ""))
    fecha = str(fila.get("f", ""))
    return "unergy" in cliente.lower() and fecha >= UNERGY_DESDE


def _nueva_fila(fila: dict, *, empresa: str, un: bool, batch: str) -> dict:
    """Arma una fila nueva (alta) con los campos de air-e mas los propios.

    Compartida por las dos rutas de alta en `fusionar`: `es_alta` (empresa
    manual, `un=False`) y `es_alta_unergy` (empresa derivada, `un=True`). `se`
    y `p` van vacios en ambas: estos registros no estan en el sheet de ECS.
    """
    nueva = {campo: fila[campo] for campo in CAMPOS_DE_AIRE}
    nueva.update(
        c=fila["c"], al=fila["al"], ak=fila["ak"],
        e=empresa, se="", p="", un=un, b=batch,
    )
    return nueva


def _valida_guardas(filas: list[dict], informe: dict, estados_conocidos: set[str],
                    municipios_conocidos: set[str], total_minimo: int,
                    total_actuales: int) -> None:
    if len(filas) < total_minimo:
        raise MergeError(
            f"guarda de conteo: quedaron {len(filas)} registros y se esperaban "
            f"al menos {total_minimo}. Revisar el snapshot antes de reintentar."
        )

    # Invariante directa e independiente del piso estatico de arriba: ningun
    # registro se elimina en la fusion, sin importar cuanto crezca DATA con
    # el tiempo (el piso de TOTAL_MINIMO se queda corto si DATA supera 1589).
    if len(filas) < total_actuales:
        raise MergeError(
            f"guarda de no eliminacion: quedaron {len(filas)} registros mezclados "
            f"pero habia {total_actuales} actuales; se perdieron "
            f"{total_actuales - len(filas)}. Ningun registro se elimina en la fusion."
        )

    # Un pull vacio o truncado hace que todo actual quede "sin_contraparte":
    # eso deja pasar deriva 0.0, coordenadas y estados intactos, y el conteo
    # sigue en pie porque no se perdio nada. Sin esta guarda el build
    # "exitoso" simplemente reescribe el archivo sin ningun dato nuevo.
    n_sin_contraparte = len(informe["sin_contraparte"])
    if n_sin_contraparte > TOPE_SIN_CONTRAPARTE:
        raise MergeError(
            f"guarda de sin contraparte: {n_sin_contraparte} de {total_actuales} "
            f"registros actuales no aparecieron en el snapshot de air-e, sobre "
            f"un tope de {TOPE_SIN_CONTRAPARTE}. Sugiere un pull fallido o "
            "incompleto; revisar la extraccion antes de reintentar."
        )

    # Esta guarda va antes que la de deriva a proposito: un estado desconocido
    # ES la causa de la deriva (un registro que migra a un estado que la UI no
    # conoce cuenta como cambio de estado), asi que si ambas se disparan a la
    # vez el diagnostico preciso ("Normalizado no esta en ESTADO_ORDER") debe
    # ganarle a la alarma generica de deriva ("X% cambio de estado, sugiere un
    # pull defectuoso"). Lo especifico y accionable primero; el sintoma despues.
    desconocidos = sorted({f["es"] for f in filas if f["es"] not in estados_conocidos})
    if desconocidos:
        raise MergeError(
            f"guarda de estados conocidos: {desconocidos} no estan en "
            "ESTADO_ORDER. Entrarian sin color en el mapa y sin chip en el "
            "filtro. Agregarlos a la UI antes de incorporarlos."
        )

    if informe["deriva_estados"] > UMBRAL_DERIVA:
        pct = informe["deriva_estados"] * 100
        raise MergeError(
            f"guarda de deriva de estados: {pct:.1f}% de los registros cambio de "
            f"estado, sobre un umbral de {UMBRAL_DERIVA * 100:.0f}%. El movimiento "
            "real es gradual, asi que esto sugiere un pull defectuoso."
        )

    # Caja del Caribe en vez de un simple "no es None": esa version no atrapa
    # el centinela `0.0` (un `LATITUD: 0` es un punto valido para `is None`, y
    # pondria un pin en el Golfo de Guinea sin que ninguna guarda se diera
    # cuenta). El registro 11142 del universo air-e declara `LATITUD: 1.10311`
    # para "PUERTO COLOMBIA" -en el Amazonas, no el Caribe- y esta guarda es
    # lo que lo atraparia si algun dia entrara a la salida.
    fuera_de_rango = [
        (f["c"], f.get("la"), f.get("lo"))
        for f in filas
        if f.get("la") is None
        or f.get("lo") is None
        or not (LAT_MIN <= f["la"] <= LAT_MAX)
        or not (LON_MIN <= f["lo"] <= LON_MAX)
    ]
    if fuera_de_rango:
        detalle = ", ".join(f"{c} ({la}, {lo})" for c, la, lo in fuera_de_rango[:5])
        raise MergeError(
            f"guarda de coordenadas: {len(fuera_de_rango)} registros quedaron "
            f"con latitud/longitud fuera del Caribe colombiano "
            f"(lat {LAT_MIN}-{LAT_MAX}, lon {LON_MIN}-{LON_MAX}), por ejemplo: "
            f"{detalle}."
        )

    sin_depto = sorted({f["ci"] for f in filas if f["ci"] not in municipios_conocidos})
    if sin_depto:
        raise MergeError(
            f"guarda de municipios: {sin_depto} no estan en DEPT_MAP y "
            "apareceria 'Sin clasificar' en Analisis. Agregarlos a DEPT_MAP."
        )


def _ultimos_12_meses(hoy: date) -> list[str]:
    """Los 12 meses `YYYY-MM` que terminan en el mes de `hoy`, en orden."""
    meses = []
    anio, mes = hoy.year, hoy.month
    for _ in range(12):
        meses.append(f"{anio:04d}-{mes:02d}")
        mes -= 1
        if mes == 0:
            mes, anio = 12, anio - 1
    return list(reversed(meses))


def fusionar(
    actuales: list[dict],
    snapshot: list[dict],
    *,
    estados_conocidos: set[str],
    municipios_conocidos: set[str],
    total_minimo: int = TOTAL_MINIMO,
    batch: str = BATCH_ALTAS,
) -> tuple[list[dict], dict]:
    """Devuelve (filas fusionadas, informe). Aborta si una guarda falla."""
    por_codigo = {f["c"]: f for f in snapshot}
    presentes = {f["c"] for f in actuales}

    cambios: list[dict] = []
    sin_contraparte: list[str] = []
    estados_movidos = 0
    salida: list[dict] = []

    for actual in actuales:
        fresco = por_codigo.get(actual["c"])
        if fresco is None:
            sin_contraparte.append(actual["c"])
            fila_huerfana = dict(actual)
            # Mismo conjunto de claves que una fila fusionada: sin esto, un
            # snapshot parcial deja la salida con dos formas de fila distintas.
            # setdefault, no asignacion directa: a partir de la segunda
            # corrida `actual` ya trae al/ak escritos por una fusion previa
            # (este pipeline los escribe en index.html), y un huerfano sin
            # contraparte hoy no tiene forma de saber su valor fresco. Pisarlo
            # con None/0.0 borraria en silencio un almacenamiento real.
            fila_huerfana.setdefault("al", None)
            fila_huerfana.setdefault("ak", 0.0)
            salida.append(fila_huerfana)
            continue

        fila = dict(actual)
        for campo in CAMPOS_DE_AIRE:
            antes, despues = actual.get(campo), fresco[campo]
            if (
                campo in ("la", "lo")
                and isinstance(antes, (int, float))
                and isinstance(despues, (int, float))
            ):
                # Ruido de punto flotante entre BD sin redondear y snapshot ya
                # redondeado: se escribe `despues` igual, pero no cuenta como
                # cambio real si coinciden a DECIMALES_COORDENADAS.
                hay_cambio = round(antes, DECIMALES_COORDENADAS) != round(
                    despues, DECIMALES_COORDENADAS
                )
            else:
                hay_cambio = antes != despues
            if hay_cambio:
                cambios.append(
                    {"c": actual["c"], "campo": campo, "antes": antes, "despues": despues}
                )
                if campo == "es":
                    estados_movidos += 1
            fila[campo] = despues
        fila["al"] = fresco["al"]
        fila["ak"] = fresco["ak"]
        salida.append(fila)

    altas: list[str] = []
    altas_unergy: list[str] = []
    candidatos_excluidos: list[dict] = []
    for fila in snapshot:
        if fila["c"] in presentes:
            continue
        if es_alta(fila):
            # Ruta manual: EMPRESAS_ALTAS aplica SOLO aqui. `es_alta_unergy`
            # (elif de abajo) nunca pasa por este camino ni por su guarda.
            empresa = EMPRESAS_ALTAS.get(fila["c"])
            if not empresa:
                raise MergeError(
                    f"el codigo {fila['c']} cumple la regla de altas "
                    f"({fila['ak']} kWh, {fila['ci']}, cliente {fila['cl']!r}) pero no "
                    "tiene empresa asignada en EMPRESAS_ALTAS. Asignarla a mano: "
                    "el campo alimenta el filtro y los rankings."
                )
            salida.append(_nueva_fila(fila, empresa=empresa, un=False, batch=batch))
            altas.append(fila["c"])
        elif es_alta_unergy(fila):
            # Ruta derivada: la empresa sale de la regla misma (EMPRESA_UNERGY
            # = "UNERGY"), no de EMPRESAS_ALTAS. Ese mecanismo manual no
            # escala a estos 227 codigos y aqui no hace falta: ya se sabe cual
            # es la empresa porque es literalmente lo que la regla filtra.
            salida.append(
                _nueva_fila(fila, empresa=EMPRESA_UNERGY, un=True, batch=batch)
            )
            altas_unergy.append(fila["c"])
        elif fila.get("al") is True:
            candidatos_excluidos.append(
                {"c": fila["c"], "tg": fila["tg"], "ak": fila["ak"],
                 "ci": fila["ci"], "cl": fila["cl"], "pac": fila["pac"]}
            )

    # El denominador correcto es la poblacion comparada (actuales con
    # contraparte en el snapshot), no todos los actuales: si air-e devuelve
    # solo una fraccion de los registros, dividir por el total diluye la
    # deriva real entre los que si se compararon (F4).
    comparados = len(actuales) - len(sin_contraparte)

    # Entregable del spec: un reporte del universo air-e que no queda
    # incorporado a esta salida, por tipo/estado/mes. `salida` ya tiene el
    # codigo de cada actual (fusionado o huerfano) mas las altas nuevas, asi
    # que todo lo del snapshot que no aparezca ahi es "no incorporado":
    # incluye a `candidatos_excluidos` y al resto del universo no curado
    # (~9.000 registros). Se resume en agregados, nunca en detalle por fila.
    codigos_incorporados = {f["c"] for f in salida}
    no_incorporados = [f for f in snapshot if f["c"] not in codigos_incorporados]
    hoy = date.today()
    meses_recientes = _ultimos_12_meses(hoy)
    conteo_por_mes = Counter(f["f"][:7] for f in no_incorporados)

    informe = {
        "fecha": hoy.isoformat(),
        "cambios": cambios,
        "altas": altas,
        "altas_unergy": altas_unergy,
        "sin_contraparte": sin_contraparte,
        "deriva_estados": (estados_movidos / comparados) if comparados else 0.0,
        "candidatos_excluidos": candidatos_excluidos,
        "almacenamiento_incoherente": [
            f["c"] for f in snapshot if f.get("al") is True and f.get("ak") == 0
        ],
        "total": len(salida),
        "universo_aire": len(snapshot),
        "con_almacenamiento_aire": sum(1 for f in snapshot if f.get("al") is True),
        "no_incorporado_total": len(no_incorporados),
        "no_incorporado_por_tg": dict(
            sorted(
                Counter(f["tg"] for f in no_incorporados).items(),
                key=lambda kv: (-kv[1], kv[0]),
            )
        ),
        "no_incorporado_por_es": dict(
            sorted(
                Counter(f["es"] for f in no_incorporados).items(),
                key=lambda kv: (-kv[1], kv[0]),
            )
        ),
        "no_incorporado_por_mes": {
            mes: conteo_por_mes.get(mes, 0) for mes in meses_recientes
        },
    }

    _valida_guardas(
        salida, informe, estados_conocidos, municipios_conocidos, total_minimo,
        len(actuales),
    )
    return salida, informe


def render_reporte(informe: dict) -> str:
    """Reporte en markdown para revision humana antes de commitear."""
    lineas = [
        f"# Reporte de cambios — {informe['fecha']}",
        "",
        f"- Registros resultantes: **{informe['total']}**",
        f"- Universo air-e consultado: {informe['universo_aire']}",
        f"- Con almacenamiento en air-e: {informe['con_almacenamiento_aire']}",
        f"- Altas por regla de almacenamiento: {len(informe['altas'])}",
        f"- Altas por cliente Unergy (desde 2026): "
        f"{len(informe.get('altas_unergy', []))}",
        f"- Deriva de estados: **{informe['deriva_estados'] * 100:.2f}%** "
        f"(umbral {UMBRAL_DERIVA * 100:.0f}%)",
        "",
    ]

    lineas += ["## Altas por regla de almacenamiento", ""]
    if informe["altas"]:
        for codigo in informe["altas"]:
            lineas.append(f"- `{codigo}` — empresa `{EMPRESAS_ALTAS.get(codigo, '')}`")
    else:
        lineas.append("Ninguna.")
    lineas.append("")

    lineas += ["## Altas por cliente Unergy (desde 2026)", ""]
    altas_unergy = informe.get("altas_unergy", [])
    if altas_unergy:
        lineas.append(
            f"Se incorporaron **{len(altas_unergy)}** registros: cliente "
            f"contiene \"unergy\" y fecha de solicitud desde {UNERGY_DESDE}. "
            f"Empresa derivada `{EMPRESA_UNERGY}` en todos (no viene de "
            "EMPRESAS_ALTAS)."
        )
        lineas.append("")
        lineas.append(", ".join(f"`{c}`" for c in altas_unergy))
    else:
        lineas.append("Ninguna.")
    lineas.append("")

    lineas += ["## Campos que cambiaron", ""]
    if informe["cambios"]:
        lineas += ["| Código | Campo | Antes | Después |", "|---|---|---|---|"]
        for cambio in informe["cambios"]:
            lineas.append(
                f"| `{cambio['c']}` | `{cambio['campo']}` | "
                f"{cambio['antes']!r} | {cambio['despues']!r} |"
            )
    else:
        lineas.append("Ninguno. La BD ya coincide con air-e.")
    lineas.append("")

    lineas += ["## Registros de la BD que air-e ya no devuelve", ""]
    if informe["sin_contraparte"]:
        lineas.append(
            "Se conservaron sin cambios. **Revisar**: con la ventana semiabierta "
            "esto deberia dar 0, asi que sugiere un problema de extraccion."
        )
        lineas.append("")
        lineas.append(", ".join(f"`{c}`" for c in informe["sin_contraparte"]))
    else:
        lineas.append("Ninguno.")
    lineas.append("")
    lineas.append(
        "Nota: los 5 codigos del sheet sin contraparte en air-e (`C139`, "
        "`C153`, `C159`, `20707`, `20715`) no aparecen en esta seccion porque "
        "este pipeline no lee el sheet; estan documentados en el spec."
    )
    lineas.append("")

    lineas += ["## Candidatos excluidos por la regla de altas", ""]
    if informe["candidatos_excluidos"]:
        lineas += ["| Código | Tipo | kWh | kW AC | Municipio | Cliente |",
                   "|---|---|---|---|---|---|"]
        for cand in sorted(informe["candidatos_excluidos"],
                           key=lambda x: -float(x["ak"]))[:40]:
            lineas.append(
                f"| `{cand['c']}` | {cand['tg']} | {cand['ak']:g} | "
                f"{cand['pac']:g} | {cand['ci']} | {cand['cl']} |"
            )
        if len(informe["candidatos_excluidos"]) > 40:
            lineas.append("")
            lineas.append(
                f"Y {len(informe['candidatos_excluidos']) - 40} mas, "
                "casi todos AGPE residencial de techo."
            )
    else:
        lineas.append("Ninguno.")
    lineas.append("")

    lineas += ["## Almacenamiento incoherente en air-e", ""]
    if informe["almacenamiento_incoherente"]:
        lineas.append(
            "Registros con `almacenamiento = Sí` y capacidad `0`. Se reportan sin "
            "interpretar."
        )
        lineas.append("")
        lineas.append(", ".join(f"`{c}`" for c in informe["almacenamiento_incoherente"]))
    else:
        lineas.append("Ninguno.")
    lineas.append("")

    lineas += ["## Universo air-e no incorporado", ""]
    lineas.append(
        f"Registros del universo air-e que no forman parte de esta salida "
        f"(ni actuales, ni altas): **{informe['no_incorporado_total']}**. Incluye "
        "a los candidatos excluidos de arriba y al resto del universo no "
        "curado. Se resume en agregados; nunca en un listado fila por fila."
    )
    lineas.append("")
    lineas += ["### Por tipo de generación", "", "| Tipo | Registros |", "|---|---|"]
    for tg, n in informe["no_incorporado_por_tg"].items():
        lineas.append(f"| {tg} | {n} |")
    lineas.append("")
    lineas += ["### Por estado", "", "| Estado | Registros |", "|---|---|"]
    for es, n in informe["no_incorporado_por_es"].items():
        lineas.append(f"| {es} | {n} |")
    lineas.append("")
    lineas += [
        "### Por mes de solicitud (últimos 12 meses)", "",
        "| Mes | Registros |", "|---|---|",
    ]
    for mes, n in informe["no_incorporado_por_mes"].items():
        lineas.append(f"| {mes} | {n} |")
    lineas.append("")

    return "\n".join(lineas)
