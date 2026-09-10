"""Capa de red contra el portal CREG030 de air-e.

Este modulo no conoce el esquema del radar: entrega los registros crudos tal
como los devuelve el portal.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import date

ENDPOINT = (
    "https://servicios.air-e.com/CREG030/form/WFListadoSolicitud.aspx/ListaSolicitudes"
)

# El portal a veces responde con la pagina de Runtime Error de ASP.NET y codigo
# HTTP 200. Se detecta por forma, no por status.
_TIMEOUT_S = 300


class AireError(RuntimeError):
    """La respuesta del portal no es utilizable."""


def next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def month_windows(start: date, end_exclusive: date) -> list[tuple[str, str]]:
    """Ventanas mensuales semiabiertas [inicio, fin).

    FECHAFIN es exclusivo y el portal lo interpreta a las 00:00 de ese dia, asi
    que cerrar en el ultimo dia del mes descarta todo lo creado despues de
    medianoche. Cerrar en el primero del mes siguiente no pierde nada.
    """
    ventanas: list[tuple[str, str]] = []
    cursor = date(start.year, start.month, 1)
    limite = date(end_exclusive.year, end_exclusive.month, 1)
    while cursor < limite:
        siguiente = next_month(cursor)
        ventanas.append((cursor.isoformat(), siguiente.isoformat()))
        cursor = siguiente
    return ventanas


def fetch_window(
    ini: str,
    fin: str,
    *,
    opener=None,
    attempts: int = 3,
    sleep=time.sleep,
) -> list[dict]:
    """Devuelve los registros crudos de una ventana [ini, fin)."""
    if opener is None:
        opener = urllib.request.urlopen

    cuerpo = json.dumps({"Objsolicitud": {"FECHAINI": ini, "FECHAFIN": fin}})
    peticion = urllib.request.Request(
        ENDPOINT,
        data=cuerpo.encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    ultimo: Exception | None = None
    for intento in range(attempts):
        try:
            with opener(peticion, timeout=_TIMEOUT_S) as respuesta:
                crudo = respuesta.read()
            # air-e sirve UTF-8. Se decodifica explicitamente desde bytes:
            # dejar que la libreria adivine, o recodificar desde Latin-1,
            # corrompe cada caracter acentuado.
            texto = crudo.decode("utf-8")
            if not texto.lstrip().startswith("{"):
                raise AireError("el portal respondio HTML en lugar de JSON")
            return json.loads(texto)["d"]
        except (AireError, urllib.error.URLError, json.JSONDecodeError, KeyError) as exc:
            ultimo = exc
            if intento < attempts - 1:
                sleep(2**intento)

    raise AireError(
        f"la ventana {ini}..{fin} fallo tras {attempts} intentos: {ultimo}. "
        "Reintentar mas tarde; el snapshot no se escribe parcial."
    )
