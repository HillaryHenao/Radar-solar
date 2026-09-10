"""Baja el historico completo de air-e y escribe un snapshot slim.

Uso:
    python -m scripts.fetch_aire
    python -m scripts.fetch_aire --desde 2019-01 --hasta 2026-10
    python -m scripts.fetch_aire --salida data/snapshots/aire-2026-09-10.json

El snapshot guarda solo los 14 campos que consume el radar. El registro crudo de
air-e tiene 95 y pesa 27,5 MB en el historico completo; la proyeccion pesa 2,6 MB
y queda diffeable entre corridas.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from scripts.aire_client import AireError, fetch_window, month_windows, next_month
from scripts.inject import InjectError, escribir_atomico
from scripts.transform import to_row

RAIZ = Path(__file__).resolve().parent.parent
DESDE_POR_DEFECTO = date(2019, 1, 1)


def _mes(texto: str) -> date:
    try:
        return datetime.strptime(texto, "%Y-%m").date().replace(day=1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"se espera un mes con formato YYYY-MM, no {texto!r}"
        ) from exc


def _clave_orden(codigo: str) -> tuple[int, object]:
    """Orden numerico por CONSECUTIVO, con los codigos no numericos al final.

    `int(f["c"])` lanzaria ValueError si algun dia air-e devolviera un
    CONSECUTIVO no numerico (como los codigos internos `C139`/`C153`/`C159`
    del sheet), y eso pasaria *despues* de que el pull completo de ~10 minutos
    ya termino. Mejor ordenar tolerando esos casos y reportarlos que perder el
    pull entero.
    """
    try:
        return (0, int(codigo))
    except ValueError:
        return (1, codigo)


def descargar(desde: date, hasta: date) -> list[dict]:
    ventanas = month_windows(desde, hasta)
    print(f"ventanas a consultar: {len(ventanas)}", file=sys.stderr)

    por_codigo: dict[str, dict] = {}
    for indice, (ini, fin) in enumerate(ventanas, start=1):
        crudos = fetch_window(ini, fin)
        for crudo in crudos:
            fila = to_row(crudo)
            # Indexado por la identidad propia del registro, nunca por lo que
            # se pidio: es la guarda contra el modo de falla de a2cabc2.
            por_codigo[fila["c"]] = fila
        print(
            f"  [{indice}/{len(ventanas)}] {ini}..{fin}: {len(crudos)} registros",
            file=sys.stderr,
        )

    filas = sorted(por_codigo.values(), key=lambda f: _clave_orden(f["c"]))
    no_numericos = [f["c"] for f in filas if not f["c"].isdigit()]
    if no_numericos:
        print(
            f"codigos no numericos, ordenados al final: {no_numericos}",
            file=sys.stderr,
        )
    return filas


def main(argv: list[str] | None = None) -> int:
    hoy = date.today()
    parser = argparse.ArgumentParser(description="Descarga el historico de air-e.")
    parser.add_argument("--desde", type=_mes, default=DESDE_POR_DEFECTO)
    parser.add_argument("--hasta", type=_mes, default=next_month(hoy))
    parser.add_argument(
        "--salida",
        type=Path,
        default=RAIZ / "data" / "snapshots" / f"aire-{hoy.isoformat()}.json",
    )
    args = parser.parse_args(argv)

    try:
        filas = descargar(args.desde, args.hasta)
    except AireError as exc:
        raise SystemExit(
            f"{exc}\n"
            "Este comando es idempotente: se puede volver a correr sin riesgo, "
            "no deja un snapshot a medio escribir."
        )

    args.salida.parent.mkdir(parents=True, exist_ok=True)
    try:
        escribir_atomico(
            args.salida,
            json.dumps(filas, ensure_ascii=False, indent=0),
            # LF, no el default de index.html: es un archivo generado, no
            # empalmado, y LF es lo que git ya guarda para el bajo
            # `core.autocrlf=true` de este repo. Con el default ("") los
            # separadores del JSON pasarian sin traducir y la proxima corrida
            # en Windows reescribiria las 170 mil lineas como diff completo.
            newline="\n",
        )
    except InjectError as exc:
        raise SystemExit(str(exc))
    print(f"{len(filas)} registros unicos en {args.salida}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
