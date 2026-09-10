"""Conversion de un registro crudo de air-e al esquema del radar.

Funciones puras: sin red, sin I/O. Cada regla aqui existe porque su ausencia
produjo un diff falso al medir contra la BD.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

# Colombia no aplica horario de verano, asi que un offset fijo es correcto.
_COLOMBIA = timezone(timedelta(hours=-5))

_ESPACIOS = re.compile(r"\s+")
_FEC_CREA = re.compile(r"^/Date\((-?\d+)\)/$")

# Rango plausible para una solicitud CREG030: el portal usa
# /Date(-62135578800000)/ (ano 1) como centinela de "sin fecha".
_EPOCH_MIN_MS = 946_684_800_000  # 2000-01-01
_EPOCH_MAX_MS = 4_102_444_800_000  # 2100-01-01

SNAPSHOT_FIELDS = (
    "c", "f", "es", "cl", "ci", "co", "ve", "t", "tg", "la", "lo", "al", "ak", "pac",
)


def norm_text(value) -> str:
    """Colapsa espacios en blanco a uno solo y recorta los extremos.

    air-e devuelve texto con relleno y tabuladores. La BD lo tiene limpio, asi
    que sin esta normalizacion el refresco ensuciaria 107 nombres de cliente.
    """
    if value is None:
        return ""
    return _ESPACIOS.sub(" ", str(value)).strip()


def parse_fecha(value) -> str:
    """`/Date(<ms epoch>)/` a `YYYY-MM-DD HH:mm` en UTC-5."""
    coincidencia = _FEC_CREA.match(str(value or ""))
    if coincidencia is None:
        raise ValueError(
            f"FEC_CREA no reconocida: {value!r}. Se espera '/Date(<ms>)/'."
        )
    ms = int(coincidencia.group(1))
    if not _EPOCH_MIN_MS <= ms <= _EPOCH_MAX_MS:
        raise ValueError(
            f"FEC_CREA fuera de rango: {value!r}. Probable centinela de fecha vacia."
        )
    momento = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(_COLOMBIA)
    return momento.strftime("%Y-%m-%d %H:%M")


def round5(value):
    """Redondea a 5 decimales, que es lo que la BD ya guarda (~1 metro)."""
    if value is None or value == "":
        return None
    return round(float(value), 5)


def parse_almacenamiento(value):
    """`1` es Si, `2` es No, cualquier otra cosa es dato ausente."""
    if value == 1:
        return True
    if value == 2:
        return False
    return None


def to_row(rec: dict) -> dict:
    """Registro crudo de air-e a fila del snapshot."""
    return {
        "c": str(rec["CONSECUTIVO"]),
        "f": parse_fecha(rec.get("FEC_CREA")),
        "es": norm_text(rec.get("DESC_ESTADO")),
        "cl": norm_text(rec.get("NOMBRE_CLI")),
        "ci": norm_text(rec.get("DESC_CIUDAD_PRO")),
        "co": norm_text(rec.get("DESC_CORREGIMIENTO_PRO")),
        "ve": norm_text(rec.get("DESC_VEREDA_PRO")),
        "t": norm_text(rec.get("TECNO_UTILIZADA_DESC")),
        "tg": norm_text(rec.get("TIPO")),
        "la": round5(rec.get("LATITUD")),
        "lo": round5(rec.get("LONGITUD")),
        "al": parse_almacenamiento(rec.get("TIENE_ALMACENAMIENTO")),
        "ak": float(rec.get("CAPACIDAD_ALMACENAMIENTO") or 0),
        "pac": float(rec.get("POTENCIA_TOTAL_AC") or 0),
    }
