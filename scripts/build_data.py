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

from scripts.inject import escribir_atomico, leer_data, leer_html, reemplazar_data
from scripts.merge import fusionar, render_reporte

RAIZ = Path(__file__).resolve().parent.parent

_ESTADO_ORDER = re.compile(r"const ESTADO_ORDER\s*=\s*(\[.*?\]);", re.DOTALL)
_DEPT_MAP = re.compile(r"const DEPT_MAP\s*=\s*(\{.*?\});", re.DOTALL)


def estados_de_ui(html: str) -> set[str]:
    """Los estados que la UI sabe colorear, leidos de ESTADO_ORDER."""
    coincidencia = _ESTADO_ORDER.search(html)
    if coincidencia is None:
        raise SystemExit("no se encontro ESTADO_ORDER en index.html")
    return set(json.loads(coincidencia.group(1)))


def municipios_de_ui(html: str) -> set[str]:
    """Los municipios con departamento asignado, leidos de DEPT_MAP."""
    coincidencia = _DEPT_MAP.search(html)
    if coincidencia is None:
        raise SystemExit("no se encontro DEPT_MAP en index.html")
    return set(json.loads(coincidencia.group(1)))


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

    print(f"actuales: {len(actuales)} | snapshot: {len(snapshot)}", file=sys.stderr)

    filas, informe = fusionar(
        actuales,
        snapshot,
        estados_conocidos=estados_de_ui(html),
        municipios_conocidos=municipios_de_ui(html),
    )
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

    escribir_atomico(args.index, salida)
    args.reporte.parent.mkdir(parents=True, exist_ok=True)
    args.reporte.write_text(reporte, encoding="utf-8")
    print(
        f"{len(filas)} registros escritos en {args.index}\n"
        f"reporte en {args.reporte}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
