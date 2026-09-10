"""Empalme del array `const DATA` dentro de index.html.

El archivo tiene 951 lineas de UI y el DATA es una sola linea de 480 KB. Aqui se
reemplaza exclusivamente ese tramo: reescribir el archivo desde una plantilla es
la forma facil de perder la UI.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

PREFIJO = "const DATA = ["


class InjectError(RuntimeError):
    """El index.html no tiene la forma que este empalme necesita."""


def _limites(html: str) -> tuple[int, int]:
    """Indices [inicio, fin) del tramo `const DATA = [...]`."""
    inicio = html.find(PREFIJO)
    if inicio == -1:
        raise InjectError(
            f"no se encontro {PREFIJO!r} en el archivo. "
            "Verificar que sea el index.html del radar."
        )
    # El corchete de apertura es el ultimo caracter del prefijo. Se decodifica
    # el array con el propio parser de JSON, que devuelve el indice exacto donde
    # termina: buscar '];' por texto se rompe si un nombre de cliente lo
    # contiene.
    corchete = inicio + len(PREFIJO) - 1
    try:
        _, fin = json.JSONDecoder().raw_decode(html, corchete)
    except json.JSONDecodeError as exc:
        raise InjectError(
            f"el array DATA no parsea como JSON: {exc}. "
            "Puede haber quedado a medio escribir por una corrida anterior."
        ) from exc
    return inicio, fin


def leer_data(html: str) -> list[dict]:
    """Devuelve las filas del `const DATA` actual."""
    inicio, fin = _limites(html)
    corchete = inicio + len(PREFIJO) - 1
    return json.loads(html[corchete:fin])


def reemplazar_data(html: str, filas: list[dict]) -> str:
    """Devuelve el html con el array reemplazado por `filas`."""
    inicio, fin = _limites(html)
    payload = json.dumps(filas, ensure_ascii=False, separators=(",", ":"))
    return html[:inicio] + "const DATA = " + payload + html[fin:]


def escribir_atomico(destino: Path, contenido: str) -> None:
    """Escribe a un temporal en el mismo directorio y reemplaza de una vez."""
    destino = Path(destino)
    descriptor, temporal = tempfile.mkstemp(
        dir=str(destino.parent), prefix=destino.name, suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as manejador:
            manejador.write(contenido)
        os.replace(temporal, destino)
    except BaseException:
        if os.path.exists(temporal):
            os.unlink(temporal)
        raise
