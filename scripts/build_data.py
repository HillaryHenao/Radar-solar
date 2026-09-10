"""Construye el DATA nuevo y lo reinyecta en index.html.

Uso:
    python -m scripts.build_data --snapshot data/snapshots/aire-2026-09-10.json
    python -m scripts.build_data --snapshot ... --dry-run

Con --dry-run no escribe nada: imprime el reporte por stdout. Es la forma de
revisar el diff antes de tocar el archivo.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from scripts.inject import (
    InjectError,
    actualizar_fecha_footer,
    escribir_atomico,
    leer_data,
    leer_html,
    reemplazar_data,
)
from scripts.merge import MergeError, fusionar, render_reporte

RAIZ = Path(__file__).resolve().parent.parent

_ESTADO_ORDER = re.compile(r"const ESTADO_ORDER\s*=\s*(\[.*?\]);", re.DOTALL)
_DEPT_MAP = re.compile(r"const DEPT_MAP\s*=\s*(\{.*?\});", re.DOTALL)

# Abreviatura de mes en espanol que replica la convencion ya presente en la
# BD (`sept1`, `sept9`, `sept10`: "sept", no "sep"). El campo `b` no lo lee la
# UI, asi que el formato es libre; lo unico que importa es no colisionar
# entre corridas de dias distintos.
_MESES_ES = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sept", 10: "oct", 11: "nov", 12: "dic",
}


def batch_del_dia(fecha: date) -> str:
    """Batch de esta corrida, con la misma forma que `sept10`."""
    return f"{_MESES_ES[fecha.month]}{fecha.day}"


def estados_de_ui(html: str) -> set[str]:
    """Los estados que la UI sabe colorear, leidos de ESTADO_ORDER."""
    coincidencia = _ESTADO_ORDER.search(html)
    if coincidencia is None:
        raise SystemExit("no se encontro ESTADO_ORDER en index.html")
    try:
        return set(json.loads(coincidencia.group(1)))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"ESTADO_ORDER en index.html no parsea como JSON: {exc}. "
            "Revisar que el literal use comillas dobles en claves y valores "
            "y no tenga coma final."
        )


def municipios_de_ui(html: str) -> set[str]:
    """Los municipios con departamento asignado, leidos de DEPT_MAP."""
    coincidencia = _DEPT_MAP.search(html)
    if coincidencia is None:
        raise SystemExit("no se encontro DEPT_MAP en index.html")
    try:
        return set(json.loads(coincidencia.group(1)))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"DEPT_MAP en index.html no parsea como JSON: {exc}. "
            "Revisar que el literal use comillas dobles en claves y valores "
            "y no tenga coma final."
        )


def main(argv: list[str] | None = None) -> int:
    hoy = date.today()
    parser = argparse.ArgumentParser(description="Reconstruye el DATA del radar.")
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=RAIZ / "data" / "snapshots" / f"aire-{hoy.isoformat()}.json",
    )
    parser.add_argument("--index", type=Path, default=RAIZ / "index.html")
    parser.add_argument(
        "--reporte",
        type=Path,
        default=RAIZ / "data" / "reports" / f"cambios-{hoy.isoformat()}.md",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        html = leer_html(args.index)
    except FileNotFoundError:
        raise SystemExit(
            f"no se encontro el index.html en {args.index}. "
            "Verificar la ruta con --index."
        )
    except PermissionError:
        raise SystemExit(
            f"no se pudo leer {args.index}: permiso denegado. "
            "Verificar los permisos del archivo."
        )

    actuales = leer_data(html)

    try:
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(
            f"no se encontro el snapshot en {args.snapshot}. "
            "Correr primero: python -m scripts.fetch_aire"
        )
    except PermissionError:
        raise SystemExit(
            f"no se pudo leer {args.snapshot}: permiso denegado. "
            "Verificar los permisos del archivo."
        )
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"el snapshot en {args.snapshot} no parsea como JSON: {exc}. "
            "Puede estar truncado o corrupto; volver a correr "
            "python -m scripts.fetch_aire y reintentar."
        )

    print(f"actuales: {len(actuales)} | snapshot: {len(snapshot)}", file=sys.stderr)

    try:
        filas, informe = fusionar(
            actuales,
            snapshot,
            estados_conocidos=estados_de_ui(html),
            municipios_conocidos=municipios_de_ui(html),
            # Explicito y derivado de la fecha de esta corrida: el default de
            # `fusionar` (BATCH_ALTAS) es un fallback fijo que colisionaria
            # con el batch de esta misma corrida en la siguiente ejecucion.
            batch=batch_del_dia(hoy),
        )
    except MergeError as exc:
        raise SystemExit(str(exc))
    reporte = render_reporte(informe)

    if args.dry_run:
        print(reporte)
        return 0

    salida = reemplazar_data(html, filas)
    # Verificacion antes de escribir: si el resultado no parsea, no se toca nada.
    releidas = leer_data(salida)
    if len(releidas) != len(filas):
        raise SystemExit(
            f"el DATA reinyectado reparsea a {len(releidas)} filas y se "
            f"esperaban {len(filas)}. No se escribio nada."
        )

    try:
        salida = actualizar_fecha_footer(salida, hoy.isoformat())
    except InjectError as exc:
        raise SystemExit(str(exc))

    # El reporte se escribe antes que el index.html: si la escritura del
    # index fallara a mitad de camino, queda igual un registro en disco de
    # que la corrida se intento, en vez de dejar produccion cambiada sin
    # ningun rastro.
    args.reporte.parent.mkdir(parents=True, exist_ok=True)
    args.reporte.write_text(reporte, encoding="utf-8")
    escribir_atomico(args.index, salida)
    print(
        f"{len(filas)} registros escritos en {args.index}\n"
        f"reporte en {args.reporte}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
