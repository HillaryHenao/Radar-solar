"""Fusion del snapshot de air-e con el DATA actual, guardas y reporte.

Funciones puras: sin red y sin I/O de archivos. Es la pieza donde puede haber
bugs de verdad, asi que se testea completa con fixtures.
"""

from __future__ import annotations

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

# Umbral de registros actuales que pueden quedar sin contraparte en el
# snapshot antes de sospechar un pull fallido o incompleto (F5). En datos
# reales este valor es 0.
UMBRAL_SIN_CONTRAPARTE = 0.01

# Empresa de cada alta. Se asigna a mano: son pocas, `e` alimenta el filtro y
# los rankings, y una heuristica sobre NOMBRE_CLI produciria basura.
EMPRESAS_ALTAS: dict[str, str] = {
    "25857": "GECELCA",
    "22637": "GECELCA",
    "26761": "GREENYELLOW",
}

TOTAL_MINIMO = 1589
UMBRAL_DERIVA = 0.05
BATCH_ALTAS = "sept10"


class MergeError(RuntimeError):
    """Una guarda se disparo. No se escribe nada."""


def es_alta(fila: dict) -> bool:
    """Regla de inclusion: proyectos GD con almacenamiento.

    Se ancla en GD y no en "cualquier cosa que no sea AGPE pequeno" porque el
    codigo 21489 es AGPE 0.1-1MVA con 5 kWh y 10 kW AC a nombre de una persona:
    no es un proyecto.
    """
    return fila.get("al") is True and str(fila.get("tg", "")).startswith("GD")


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
    if total_actuales:
        frac_sin_contraparte = len(informe["sin_contraparte"]) / total_actuales
        if frac_sin_contraparte > UMBRAL_SIN_CONTRAPARTE:
            pct = frac_sin_contraparte * 100
            raise MergeError(
                f"guarda de sin contraparte: {len(informe['sin_contraparte'])} de "
                f"{total_actuales} registros actuales ({pct:.1f}%) no aparecieron en "
                f"el snapshot de air-e, sobre un umbral de "
                f"{UMBRAL_SIN_CONTRAPARTE * 100:.0f}%. Sugiere un pull fallido o "
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

    sin_coords = [f["c"] for f in filas if f.get("la") is None or f.get("lo") is None]
    if sin_coords:
        raise MergeError(
            f"guarda de coordenadas: {len(sin_coords)} registros quedaron sin "
            f"latitud o longitud, por ejemplo {sin_coords[:5]}."
        )

    sin_depto = sorted({f["ci"] for f in filas if f["ci"] not in municipios_conocidos})
    if sin_depto:
        raise MergeError(
            f"guarda de municipios: {sin_depto} no estan en DEPT_MAP y "
            "apareceria 'Sin clasificar' en Analisis. Agregarlos a DEPT_MAP."
        )


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
            fila_huerfana["al"] = None
            fila_huerfana["ak"] = 0.0
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
    candidatos_excluidos: list[dict] = []
    for fila in snapshot:
        if fila["c"] in presentes:
            continue
        if es_alta(fila):
            empresa = EMPRESAS_ALTAS.get(fila["c"])
            if not empresa:
                raise MergeError(
                    f"el codigo {fila['c']} cumple la regla de altas "
                    f"({fila['ak']} kWh, {fila['ci']}, cliente {fila['cl']!r}) pero no "
                    "tiene empresa asignada en EMPRESAS_ALTAS. Asignarla a mano: "
                    "el campo alimenta el filtro y los rankings."
                )
            nueva = {campo: fila[campo] for campo in CAMPOS_DE_AIRE}
            nueva.update(
                c=fila["c"], al=fila["al"], ak=fila["ak"],
                e=empresa, se="", p="", un=False, b=batch,
            )
            salida.append(nueva)
            altas.append(fila["c"])
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

    informe = {
        "fecha": date.today().isoformat(),
        "cambios": cambios,
        "altas": altas,
        "sin_contraparte": sin_contraparte,
        "deriva_estados": (estados_movidos / comparados) if comparados else 0.0,
        "candidatos_excluidos": candidatos_excluidos,
        "almacenamiento_incoherente": [
            f["c"] for f in snapshot if f.get("al") is True and f.get("ak") == 0
        ],
        "total": len(salida),
        "universo_aire": len(snapshot),
        "con_almacenamiento_aire": sum(1 for f in snapshot if f.get("al") is True),
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
        f"- Deriva de estados: **{informe['deriva_estados'] * 100:.2f}%** "
        f"(umbral {UMBRAL_DERIVA * 100:.0f}%)",
        "",
    ]

    lineas += ["## Altas", ""]
    if informe["altas"]:
        for codigo in informe["altas"]:
            lineas.append(f"- `{codigo}` — empresa `{EMPRESAS_ALTAS.get(codigo, '')}`")
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

    lineas += ["## Registros sin contraparte en air-e", ""]
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

    return "\n".join(lineas)
