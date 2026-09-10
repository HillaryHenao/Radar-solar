"""Empalme del array `const DATA` dentro de index.html.

El archivo tiene 951 lineas de UI y el DATA es una sola linea de 480 KB. Aqui se
reemplaza exclusivamente ese tramo: reescribir el archivo desde una plantilla es
la forma facil de perder la UI.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

PREFIJO = "const DATA = ["

# Coincide con "Actualizado YYYY-MM-DD" dentro del div `sidebar-foot`, sin
# depender del resto del markup de ese pie (fuente, separador, etc).
#
# `[^<]*?` en vez de `.*?`: ambos son igual de laxos hoy porque el archivo
# real siempre tiene la fecha justo despues de "Actualizado ". Pero si el
# footer alguna vez la perdiera, `.*?` con DOTALL no tiene motivo para
# detenerse en '<' y seguiria buscando el siguiente "Actualizado " a traves
# de toda la linea de 480 KB de `DATA` antes de fallar. Anclado a
# "sin '<'" el fallo es inmediato, dentro del propio div.
_FOOTER_FECHA = re.compile(
    r'(<div class="sidebar-foot">[^<]*?Actualizado )(\d{4}-\d{2}-\d{2})([^<]*?</div>)',
    re.DOTALL,
)


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


def actualizar_fecha_footer(html: str, fecha: str) -> str:
    """Reemplaza la fecha `Actualizado YYYY-MM-DD` dentro de `sidebar-foot`.

    Cada build reescribe los 1.589+ registros de `DATA` pero, sin esto, deja
    el pie de pagina reclamando la fecha de la corrida anterior a mano. Se
    edita como un tramo estructural propio -igual que `reemplazar_data`- en
    vez de otro regex disperso en `build_data`.
    """
    salida, n = _FOOTER_FECHA.subn(
        lambda m: m.group(1) + fecha + m.group(3), html, count=1
    )
    if n == 0:
        raise InjectError(
            "no se encontro 'Actualizado YYYY-MM-DD' dentro de sidebar-foot "
            "en el archivo. Verificar que el markup del footer no haya cambiado."
        )
    return salida


def leer_html(origen: Path) -> str:
    """Lee el HTML preservando los saltos de linea CRLF del archivo original.

    Esta funcion lee con newline="" para garantizar que \\r\\n se mantiene como
    caracteres literales en la cadena. El modulo promete dejar todo fuera del
    array DATA sin cambios, y una lectura en modo universal-newlines rompe esa
    promesa antes de que el empalme siquiera corra.
    """
    with open(origen, encoding="utf-8", newline="") as f:
        return f.read()


def escribir_atomico(destino: Path, contenido: str, *, newline: str | None = "") -> None:
    """Escribe a un temporal en el mismo directorio y reemplaza de una vez.

    `newline` se pasa tal cual a `open()` y por defecto es `""`: ese default
    existe para preservar el CRLF de index.html, un archivo que este modulo
    solo empalma (ver `leer_html`) y nunca debe reescribir con los saltos de
    linea del sistema. Quien escriba un archivo generado (no empalmado) desde
    cero -como el snapshot de `fetch_aire`- debe elegir `newline` a proposito:
    `""` aqui haria pasar los `\\n` del JSON sin traducir y, en Windows,
    dejaria el archivo con avisos de linea mixtos frente a la proxima corrida.
    """
    destino = Path(destino)
    descriptor, temporal = tempfile.mkstemp(
        dir=str(destino.parent), prefix=destino.name, suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline=newline) as manejador:
            manejador.write(contenido)
        os.replace(temporal, destino)
    except OSError as exc:
        if os.path.exists(temporal):
            os.unlink(temporal)
        raise InjectError(
            f"no se pudo escribir en {destino}: {exc}. "
            "Verificar que el archivo no este abierto en otro programa."
        ) from exc
    except BaseException:
        if os.path.exists(temporal):
            os.unlink(temporal)
        raise
