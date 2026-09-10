# Consulta air-e y almacenamiento — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir un pipeline reproducible que valide los 1.586 registros del radar contra el portal CREG030 de air-e, incorpore los 3 proyectos GD con almacenamiento, y haga explotable el almacenamiento con filtro en el sidebar y tabla en la vista Análisis.

**Architecture:** Dos entry points sobre cuatro módulos puros. `fetch_aire.py` habla con air-e y escribe un snapshot slim commiteable; `build_data.py` fusiona ese snapshot con el `DATA` actual, aplica 7 guardas, reinyecta el array en `index.html` y escribe un reporte de cambios. Los módulos `transform`, `merge` e `inject` no tocan la red, así que se testean completos con fixtures.

**Tech Stack:** Python 3.12, solo biblioteca estándar (`urllib.request`, `json`, `datetime`, `re`). `pytest` como única dependencia de desarrollo. El frontend es un `index.html` estático de 951 líneas con Leaflet 1.9.4 y markercluster 1.5.3 desde cdnjs; no hay build ni toolchain JS.

**Spec:** `docs/superpowers/specs/2026-09-10-radar-solar-consulta-aire-design.md`

## Global Constraints

- **Encoding:** air-e responde UTF-8 (`Content-Type: application/json; charset=utf-8`). Los bytes se decodifican con `.decode("utf-8")` **directo**. Nunca aplicar recodificación Latin-1 → UTF-8: corrompe cada acento.
- **Ventana de fechas:** semiabierta, `[primer día del mes, primer día del mes siguiente)`. `FECHAFIN` es exclusivo a las 00:00.
- **Rango completo:** `2019-01-01` hasta `2026-10-01`, 93 ventanas mensuales.
- **Huso:** `FEC_CREA` es epoch en milisegundos; se convierte a **UTC-5** y se formatea `YYYY-MM-DD HH:mm`.
- **Normalización de texto:** todo campo de texto colapsa secuencias de espacios en blanco a un espacio y recorta extremos.
- **Coordenadas:** redondeo a **5 decimales**.
- **`al`:** `1 → True`, `2 → False`, cualquier otro → `None`.
- **Preservados de la BD, nunca recalculados:** `e`, `se`, `p`, `un`, `b`.
- **Total esperado tras el build:** **1.589** registros.
- **Endpoint:** `https://servicios.air-e.com/CREG030/form/WFListadoSolicitud.aspx/ListaSolicitudes`
- **Serialización del `DATA`:** `json.dumps(rows, ensure_ascii=False, separators=(",", ":"))`.
- Todo texto de UI y de reportes en español. Los mensajes de error dicen qué pasó y qué hacer.

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `scripts/aire_client.py` | Capa de red. Construye ventanas, hace el POST, decodifica UTF-8, detecta el HTML de error de ASP.NET, reintenta. No conoce el esquema del radar. |
| `scripts/transform.py` | Funciones puras air-e → esquema del radar: fecha, espacios, redondeo, `al`/`ak`. |
| `scripts/fetch_aire.py` | CLI. Recorre las 93 ventanas, deduplica por `CONSECUTIVO`, escribe el snapshot slim ordenado. |
| `scripts/merge.py` | Reglas de fusión, regla de altas, las 7 guardas, generación del reporte. Sin red, sin I/O de archivos. |
| `scripts/inject.py` | Empalme del `const DATA` en `index.html` con `raw_decode`. Escritura atómica. |
| `scripts/build_data.py` | CLI. Orquesta: carga snapshot + `index.html`, llama `merge`, llama `inject`, escribe el reporte. |
| `tests/test_transform.py` | Casos de conversión, incluidos los goldens `21941` y `22810`. |
| `tests/test_aire_client.py` | Ventanas semiabiertas, decodificación, detección de error, reintentos. |
| `tests/test_merge.py` | Preservación de campos, altas, y las 7 guardas. |
| `tests/test_inject.py` | Empalme exacto, byte a byte fuera del tramo. |
| `tests/test_ui_contract.py` | Asserts sobre `index.html`: hooks del filtro, ids de la tabla, `DEPT_MAP`. |
| `tests/fixtures/` | Respuesta recortada de air-e y un `index.html` mínimo. |

`index.html` se modifica en las tareas 7 a 9, siempre por empalme quirúrgico, nunca reescrito.

---

### Task 1: Capa de red

**Files:**
- Create: `scripts/aire_client.py`
- Create: `tests/test_aire_client.py`
- Create: `requirements-dev.txt`
- Create: `pytest.ini`

**Interfaces:**
- Consumes: nada.
- Produces: `month_windows(start: date, end_exclusive: date) -> list[tuple[str, str]]`, `fetch_window(ini: str, fin: str, *, opener=None, attempts: int = 3) -> list[dict]`, `AireError(RuntimeError)`, `ENDPOINT: str`.

- [ ] **Step 1: Crear la configuración de pytest y la dependencia de desarrollo**

`requirements-dev.txt`:

```
pytest==8.3.4
```

`pytest.ini`:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
addopts = -q
```

- [ ] **Step 2: Escribir los tests que fallan**

`tests/test_aire_client.py`:

```python
import json
from datetime import date

import pytest

from scripts.aire_client import AireError, fetch_window, month_windows


def test_month_windows_son_semiabiertas():
    got = month_windows(date(2025, 1, 1), date(2025, 4, 1))
    assert got == [
        ("2025-01-01", "2025-02-01"),
        ("2025-02-01", "2025-03-01"),
        ("2025-03-01", "2025-04-01"),
    ]


def test_month_windows_cruza_fin_de_anio():
    got = month_windows(date(2025, 11, 1), date(2026, 2, 1))
    assert got == [
        ("2025-11-01", "2025-12-01"),
        ("2025-12-01", "2026-01-01"),
        ("2026-01-01", "2026-02-01"),
    ]


def test_month_windows_rango_completo_da_93_ventanas():
    got = month_windows(date(2019, 1, 1), date(2026, 10, 1))
    assert len(got) == 93
    assert got[0] == ("2019-01-01", "2019-02-01")
    assert got[-1] == ("2026-09-01", "2026-10-01")


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_window_decodifica_utf8_desde_bytes():
    # 'Revisión' en UTF-8 real: los bytes C3 B3 forman la o con tilde.
    payload = json.dumps(
        {"d": [{"CONSECUTIVO": 1, "DESC_ESTADO": "Revisión documento"}]},
        ensure_ascii=False,
    ).encode("utf-8")
    rows = fetch_window("2025-01-01", "2025-02-01", opener=lambda *a, **k: _FakeResponse(payload))
    assert rows[0]["DESC_ESTADO"] == "Revisión documento"


def test_fetch_window_no_recodifica_latin1():
    payload = '{"d":[{"DESC_ESTADO":"Revisión documento"}]}'.encode("utf-8")
    rows = fetch_window("2025-01-01", "2025-02-01", opener=lambda *a, **k: _FakeResponse(payload))
    assert "Ã" not in rows[0]["DESC_ESTADO"]


def test_fetch_window_detecta_el_html_de_error_de_aspnet():
    html = b"<html><head><title>Runtime Error</title></head><body>Server Error</body></html>"
    calls = []

    def opener(*a, **k):
        calls.append(1)
        return _FakeResponse(html)

    with pytest.raises(AireError) as exc:
        fetch_window("2025-01-01", "2025-02-01", opener=opener, attempts=3)
    assert len(calls) == 3
    assert "2025-01-01" in str(exc.value)


def test_fetch_window_reintenta_y_luego_acierta():
    good = json.dumps({"d": [{"CONSECUTIVO": 7}]}).encode("utf-8")
    respuestas = [b"<html>Runtime Error</html>", good]

    def opener(*a, **k):
        return _FakeResponse(respuestas.pop(0))

    rows = fetch_window("2025-01-01", "2025-02-01", opener=opener, attempts=3)
    assert rows == [{"CONSECUTIVO": 7}]
```

- [ ] **Step 3: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_aire_client.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'scripts'`

- [ ] **Step 4: Crear el paquete y la implementación**

`scripts/__init__.py` vacío y `tests/__init__.py` vacío, para que `from scripts.aire_client import ...` resuelva desde la raíz del repo.

`scripts/aire_client.py`:

```python
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


def _next_month(d: date) -> date:
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
        siguiente = _next_month(cursor)
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
```

- [ ] **Step 5: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_aire_client.py -v`
Expected: PASS, 7 tests

- [ ] **Step 6: Commit**

```bash
git add scripts/__init__.py scripts/aire_client.py tests/__init__.py tests/test_aire_client.py requirements-dev.txt pytest.ini
git commit -m "feat: capa de red contra air-e con ventanas semiabiertas y UTF-8 explicito"
```

---

### Task 2: Transformación de campos

**Files:**
- Create: `scripts/transform.py`
- Create: `tests/test_transform.py`

**Interfaces:**
- Consumes: nada.
- Produces: `norm_text(value) -> str`, `parse_fecha(value) -> str`, `round5(value) -> float | None`, `parse_almacenamiento(value) -> bool | None`, `to_row(rec: dict) -> dict`, `SNAPSHOT_FIELDS: tuple[str, ...]`.

`to_row` devuelve un dict con las claves `c, f, es, cl, ci, co, ve, t, tg, la, lo, al, ak, pac`.

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_transform.py`:

```python
import pytest

from scripts.transform import (
    norm_text,
    parse_almacenamiento,
    parse_fecha,
    round5,
    to_row,
)


def test_norm_text_colapsa_espacios_y_recorta():
    crudo = "                              UNIVERSIDAD          DEL NORTE           "
    assert norm_text(crudo) == "UNIVERSIDAD DEL NORTE"


def test_norm_text_colapsa_tabuladores():
    assert norm_text("LICA ENERGÍA RENOVABLE S.A.S\t\t\t\t\t") == "LICA ENERGÍA RENOVABLE S.A.S"


def test_norm_text_colapsa_el_espacio_doble_de_la_vereda():
    # Es el unico cambio real que produce esta corrida, en el codigo 23465.
    assert norm_text("VDA  CHARCO LATA") == "VDA CHARCO LATA"


def test_norm_text_none_da_cadena_vacia():
    assert norm_text(None) == ""


def test_parse_fecha_convierte_a_utc_menos_5():
    # Golden 22810: el portal da 2025-01-31 22:37 UTC; la BD tiene 17:37.
    assert parse_fecha("/Date(1738362422000)/") == "2025-01-31 17:37"


def test_parse_fecha_golden_21941():
    # Contra ejemplo.pdf: 30/10/2024 14:32.
    assert parse_fecha("/Date(1730309520000)/") == "2024-10-30 14:32"


def test_parse_fecha_rechaza_formato_desconocido():
    with pytest.raises(ValueError, match="FEC_CREA"):
        parse_fecha("2025-01-31")


def test_parse_fecha_rechaza_el_epoch_centinela():
    # air-e usa /Date(-62135578800000)/ como "sin fecha" en otros campos.
    with pytest.raises(ValueError, match="fuera de rango"):
        parse_fecha("/Date(-62135578800000)/")


def test_round5_recorta_el_ruido_de_punto_flotante():
    assert round5(-74.156100000000009) == -74.1561


def test_round5_none_da_none():
    assert round5(None) is None


@pytest.mark.parametrize(
    "crudo,esperado",
    [(1, True), (2, False), (0, None), (None, None), (3, None)],
)
def test_parse_almacenamiento(crudo, esperado):
    assert parse_almacenamiento(crudo) is esperado


def test_to_row_mapea_el_registro_completo():
    rec = {
        "CONSECUTIVO": 23433,
        "FEC_CREA": "/Date(1744145640000)/",
        "DESC_ESTADO": "  Estudio solicitud ",
        "NOMBRE_CLI": "We-262 ",
        "DESC_CIUDAD_PRO": "ARACATACA",
        "DESC_CORREGIMIENTO_PRO": "ARACATACA",
        "DESC_VEREDA_PRO": "ARACATACA  RURAL",
        "TECNO_UTILIZADA_DESC": "Solar FV",
        "TIPO": "GD menor igual 0.1MVA",
        "LATITUD": 10.58598,
        "LONGITUD": -74.156100000000009,
        "TIENE_ALMACENAMIENTO": 2,
        "CAPACIDAD_ALMACENAMIENTO": 0,
        "POTENCIA_TOTAL_AC": 100,
    }
    row = to_row(rec)
    assert row["c"] == "23433"
    assert row["es"] == "Estudio solicitud"
    assert row["cl"] == "We-262"
    assert row["ve"] == "ARACATACA RURAL"
    assert row["lo"] == -74.1561
    assert row["al"] is False
    assert row["ak"] == 0
    assert row["pac"] == 100


def test_to_row_codigo_es_string():
    rec = {
        "CONSECUTIVO": 7,
        "FEC_CREA": "/Date(1744145640000)/",
        "LATITUD": 1,
        "LONGITUD": 2,
        "TIENE_ALMACENAMIENTO": 1,
        "CAPACIDAD_ALMACENAMIENTO": 250,
    }
    row = to_row(rec)
    assert row["c"] == "7"
    assert isinstance(row["c"], str)
    assert row["al"] is True
    assert row["ak"] == 250
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_transform.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'scripts.transform'`

- [ ] **Step 3: Escribir la implementación**

`scripts/transform.py`:

```python
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
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_transform.py -v`
Expected: PASS, 16 tests

- [ ] **Step 5: Verificar los goldens contra epochs reales**

Los dos epochs de los tests salen de air-e. Confirmar que corresponden:

Run: `python -c "from scripts.transform import parse_fecha; print(parse_fecha('/Date(1738362422000)/'), '|', parse_fecha('/Date(1730309520000)/'))"`
Expected: `2025-01-31 17:37 | 2024-10-30 14:32`

Si el segundo no da `2024-10-30 14:32`, corregir el epoch del test contra el valor real que devuelve air-e para el código `21941`, no la función.

- [ ] **Step 6: Commit**

```bash
git add scripts/transform.py tests/test_transform.py
git commit -m "feat: transformacion de campos air-e con UTC-5, normalizacion y redondeo"
```

---

### Task 3: CLI de descarga y snapshot

**Files:**
- Create: `scripts/fetch_aire.py`
- Create: `data/snapshots/.gitkeep`

**Interfaces:**
- Consumes: `scripts.aire_client.month_windows`, `scripts.aire_client.fetch_window`, `scripts.transform.to_row`.
- Produces: el archivo `data/snapshots/aire-<YYYY-MM-DD>.json`: lista JSON de filas ordenada por `c` numérico, con las claves de `SNAPSHOT_FIELDS`.

- [ ] **Step 1: Escribir la implementación**

`scripts/fetch_aire.py`:

```python
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

from scripts.aire_client import fetch_window, month_windows
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


def _primero_del_mes_siguiente(hoy: date) -> date:
    if hoy.month == 12:
        return date(hoy.year + 1, 1, 1)
    return date(hoy.year, hoy.month + 1, 1)


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

    return sorted(por_codigo.values(), key=lambda f: int(f["c"]))


def main(argv: list[str] | None = None) -> int:
    hoy = date.today()
    parser = argparse.ArgumentParser(description="Descarga el historico de air-e.")
    parser.add_argument("--desde", type=_mes, default=DESDE_POR_DEFECTO)
    parser.add_argument("--hasta", type=_mes, default=_primero_del_mes_siguiente(hoy))
    parser.add_argument(
        "--salida",
        type=Path,
        default=RAIZ / "data" / "snapshots" / f"aire-{hoy.isoformat()}.json",
    )
    args = parser.parse_args(argv)

    filas = descargar(args.desde, args.hasta)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(
        json.dumps(filas, ensure_ascii=False, indent=0),
        encoding="utf-8",
    )
    print(f"{len(filas)} registros unicos en {args.salida}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Correr la descarga real**

Run: `python -m scripts.fetch_aire`
Expected: 93 ventanas sin error, y una línea final `10640 registros unicos en data/snapshots/aire-2026-09-10.json` (el total puede haber crecido si air-e recibió solicitudes nuevas; nunca debe ser menor).

Si alguna ventana falla, el proceso aborta con `AireError`. Reintentar el comando completo: es idempotente.

- [ ] **Step 3: Verificar el snapshot**

Run:

```bash
python -c "
import json
filas = json.load(open('data/snapshots/aire-2026-09-10.json', encoding='utf-8'))
print('registros:', len(filas))
print('codigos unicos:', len({f['c'] for f in filas}))
print('con almacenamiento:', sum(1 for f in filas if f['al'] is True))
print('acentos ok:', any('ó' in (f['es'] or '') for f in filas))
print('21941:', next(f for f in filas if f['c'] == '21941'))
"
```

Expected: registros y códigos únicos iguales; `con almacenamiento` en 316 o más; `acentos ok: True`; y el registro `21941` con `f` igual a `2024-10-30 14:32`, `es` igual a `Estudio solicitud`, `al` en `false`.

Si `acentos ok` da `False`, la decodificación está mal: revisar que `aire_client` use `.decode("utf-8")` sobre los bytes.

- [ ] **Step 4: Commit**

```bash
git add scripts/fetch_aire.py data/snapshots/
git commit -m "feat: CLI de descarga y snapshot slim del historico de air-e"
```

---

### Task 4: Empalme del DATA en index.html

**Files:**
- Create: `scripts/inject.py`
- Create: `tests/test_inject.py`
- Create: `tests/fixtures/index_minimo.html`

**Interfaces:**
- Consumes: nada.
- Produces: `PREFIJO: str`, `leer_data(html: str) -> list[dict]`, `reemplazar_data(html: str, filas: list[dict]) -> str`, `escribir_atomico(destino: Path, contenido: str) -> None`, `InjectError(RuntimeError)`.

- [ ] **Step 1: Crear el fixture**

`tests/fixtures/index_minimo.html`:

```html
<!doctype html>
<html><body>
<div id="map"></div>
<script>
const DATA = [{"c":"1","e":"ACME","es":"Estudio solicitud","la":10.5,"lo":-74.5},{"c":"2","e":"OTRA","es":"De Baja","la":11.0,"lo":-75.0}];
const ESTADO_ORDER = ["Estudio solicitud", "De Baja"];
function refresh(){ return DATA.length; }
</script>
</body></html>
```

- [ ] **Step 2: Escribir los tests que fallan**

`tests/test_inject.py`:

```python
import json
from pathlib import Path

import pytest

from scripts.inject import (
    InjectError,
    escribir_atomico,
    leer_data,
    reemplazar_data,
)

FIXTURE = Path(__file__).parent / "fixtures" / "index_minimo.html"


def _html():
    return FIXTURE.read_text(encoding="utf-8")


def test_leer_data_devuelve_las_filas():
    filas = leer_data(_html())
    assert [f["c"] for f in filas] == ["1", "2"]


def test_reemplazar_data_cambia_solo_el_tramo_del_array():
    original = _html()
    nuevas = [{"c": "9", "e": "NUEVA", "es": "De Baja", "la": 1.0, "lo": 2.0}]
    salida = reemplazar_data(original, nuevas)

    assert leer_data(salida) == nuevas
    # Todo lo que no es el array queda intacto.
    assert 'const ESTADO_ORDER = ["Estudio solicitud", "De Baja"];' in salida
    assert "function refresh(){ return DATA.length; }" in salida
    assert salida.startswith("<!doctype html>")
    assert salida.endswith("</body></html>\n") or salida.endswith("</body></html>")


def test_reemplazar_data_preserva_el_resto_byte_a_byte():
    original = _html()
    filas = leer_data(original)
    # Reinyectar lo mismo debe cambiar unicamente el formato del array, y el
    # resto del archivo debe seguir siendo identico.
    salida = reemplazar_data(original, filas)
    marcador = "const DATA = "
    assert original[: original.index(marcador)] == salida[: salida.index(marcador)]
    cola_original = original[original.index("const ESTADO_ORDER") :]
    cola_salida = salida[salida.index("const ESTADO_ORDER") :]
    assert cola_original == cola_salida


def test_reemplazar_data_no_escapa_los_acentos():
    salida = reemplazar_data(_html(), [{"c": "1", "es": "Revisión documento"}])
    assert "Revisión documento" in salida
    assert "\\u00f3" not in salida


def test_reemplazar_data_falla_si_no_encuentra_el_prefijo():
    with pytest.raises(InjectError, match="const DATA"):
        reemplazar_data("<html><body>sin data</body></html>", [])


def test_reemplazar_data_falla_si_el_array_no_parsea():
    roto = "<script>const DATA = [{'c':1,</script>"
    with pytest.raises(InjectError):
        reemplazar_data(roto, [])


def test_escribir_atomico_no_deja_temporales(tmp_path):
    destino = tmp_path / "index.html"
    destino.write_text("viejo", encoding="utf-8")
    escribir_atomico(destino, "nuevo")
    assert destino.read_text(encoding="utf-8") == "nuevo"
    assert list(tmp_path.iterdir()) == [destino]
```

- [ ] **Step 3: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_inject.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'scripts.inject'`

- [ ] **Step 4: Escribir la implementación**

`scripts/inject.py`:

```python
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
```

- [ ] **Step 5: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_inject.py -v`
Expected: PASS, 7 tests

- [ ] **Step 6: Verificar contra el index.html real, sin escribirlo**

Run:

```bash
python -c "
from pathlib import Path
from scripts.inject import leer_data, reemplazar_data
html = Path('index.html').read_text(encoding='utf-8')
filas = leer_data(html)
print('registros leidos:', len(filas))
print('claves:', sorted(filas[0]))
salida = reemplazar_data(html, filas)
print('idempotente fuera del array:', html[:html.index('const DATA')] == salida[:salida.index('const DATA')])
print('cola identica:', html[html.index('const ESTADO_ORDER'):] == salida[salida.index('const ESTADO_ORDER'):])
"
```

Expected: `registros leidos: 1586`; claves `['b','c','ci','cl','co','e','es','f','la','lo','p','se','t','tg','un','ve']`; y las dos comprobaciones en `True`.

- [ ] **Step 7: Commit**

```bash
git add scripts/inject.py tests/test_inject.py tests/fixtures/index_minimo.html
git commit -m "feat: empalme quirurgico del const DATA con raw_decode y escritura atomica"
```

---

### Task 5: Fusión, guardas y reporte

**Files:**
- Create: `scripts/merge.py`
- Create: `tests/test_merge.py`

**Interfaces:**
- Consumes: nada (recibe listas de dicts ya transformadas).
- Produces:
  - `EMPRESAS_ALTAS: dict[str, str]` — código a empresa para las altas.
  - `TOTAL_MINIMO: int` — 1589.
  - `UMBRAL_DERIVA: float` — 0.05.
  - `es_alta(fila: dict) -> bool`
  - `fusionar(actuales: list[dict], snapshot: list[dict], estados_conocidos: set[str], municipios_conocidos: set[str]) -> tuple[list[dict], dict]`
  - `MergeError(RuntimeError)`
  - `render_reporte(informe: dict) -> str`

`fusionar` devuelve `(filas_nuevas, informe)`. El `informe` tiene las claves
`cambios` (lista de dicts con `c`, `campo`, `antes`, `despues`), `altas` (lista de
códigos), `sin_contraparte` (lista de códigos), `deriva_estados` (float),
`candidatos_excluidos` (lista de dicts), `almacenamiento_incoherente` (lista de
códigos), `total` (int).

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_merge.py`:

```python
import pytest

from scripts.merge import (
    MergeError,
    es_alta,
    fusionar,
    render_reporte,
)

ESTADOS = {"Estudio solicitud", "Pendiente documento", "Revisión documento", "De Baja"}
MUNICIPIOS = {"ARACATACA", "FONSECA", "CIENAGA", "BARRANQUILLA"}


def _actual(**extra):
    base = {
        "c": "1", "e": "ACME", "cl": "Cliente Viejo", "p": "PROY_X",
        "ci": "ARACATACA", "co": "ARACATACA", "ve": "RURAL",
        "f": "2024-01-01 10:00", "es": "Estudio solicitud",
        "t": "Solar FV", "tg": "GD menor igual 0.1MVA",
        "la": 10.5, "lo": -74.5, "se": "ECS en proceso", "un": False, "b": "sept1",
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
    filas, _ = _fusionar([_actual()], [_snap()])
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


def test_conserva_el_registro_ausente_del_snapshot():
    filas, informe = _fusionar([_actual(c="1"), _actual(c="2")], [_snap(c="1")])
    assert len(filas) == 2
    assert informe["sin_contraparte"] == ["2"]
    conservada = next(f for f in filas if f["c"] == "2")
    assert conservada["cl"] == "Cliente Viejo"


def test_nunca_elimina_registros():
    filas, _ = _fusionar([_actual(c="1"), _actual(c="2")], [])
    assert {f["c"] for f in filas} == {"1", "2"}


def test_es_alta_solo_para_gd_con_almacenamiento():
    assert es_alta({"al": True, "tg": "GD menor igual 0.1MVA"}) is True
    assert es_alta({"al": True, "tg": "AGPE menor igual 0.1MVA"}) is False
    assert es_alta({"al": True, "tg": "AGPE menor igual 1MVA y mayor 0.1MVA"}) is False
    assert es_alta({"al": False, "tg": "GD menor igual 0.1MVA"}) is False
    assert es_alta({"al": None, "tg": "GD menor igual 0.1MVA"}) is False


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


def test_falla_si_un_alta_no_tiene_empresa_asignada():
    alta = _snap(c="99999", al=True, ak=100.0, ci="FONSECA")
    with pytest.raises(MergeError, match="99999"):
        _fusionar([_actual()], [_snap(), alta])


def test_reporta_el_candidato_excluido_por_la_regla():
    borde = _snap(c="21489", al=True, ak=5.0,
                  tg="AGPE menor igual 1MVA y mayor 0.1MVA", ci="BARRANQUILLA")
    _, informe = _fusionar([_actual()], [_snap(), borde])
    assert [c["c"] for c in informe["candidatos_excluidos"]] == ["21489"]


def test_reporta_almacenamiento_incoherente():
    raro = _snap(c="362", al=True, ak=0.0, tg="AGPE menor igual 0.1MVA")
    _, informe = _fusionar([_actual()], [_snap(), raro])
    assert informe["almacenamiento_incoherente"] == ["362"]


# ---------- guardas ----------

def test_guarda_conteo_aborta_si_falta_algun_registro():
    with pytest.raises(MergeError, match="conteo"):
        _fusionar([_actual()], [_snap()], total_minimo=5)


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


def test_guarda_coordenadas_aborta_si_falta_una():
    with pytest.raises(MergeError, match="coordenadas"):
        _fusionar([_actual()], [_snap(la=None)])


def test_guarda_estados_conocidos_aborta_con_un_estado_nuevo():
    with pytest.raises(MergeError, match="Normalizado"):
        _fusionar([_actual()], [_snap(es="Normalizado")])


def test_guarda_municipios_aborta_con_ciudad_sin_departamento():
    with pytest.raises(MergeError, match="DEPT_MAP"):
        _fusionar([_actual()], [_snap(ci="EL PI¿ON")])


def test_render_reporte_declara_los_bloques():
    _, informe = _fusionar([_actual()], [_snap()])
    texto = render_reporte(informe)
    assert "# Reporte de cambios" in texto
    assert "Cliente Nuevo" in texto
    assert "Deriva de estados" in texto
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_merge.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'scripts.merge'`

- [ ] **Step 3: Escribir la implementación**

`scripts/merge.py`:

```python
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
                    municipios_conocidos: set[str], total_minimo: int) -> None:
    if len(filas) < total_minimo:
        raise MergeError(
            f"guarda de conteo: quedaron {len(filas)} registros y se esperaban "
            f"al menos {total_minimo}. Revisar el snapshot antes de reintentar."
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

    desconocidos = sorted({f["es"] for f in filas if f["es"] not in estados_conocidos})
    if desconocidos:
        raise MergeError(
            f"guarda de estados conocidos: {desconocidos} no estan en "
            "ESTADO_ORDER. Entrarian sin color en el mapa y sin chip en el "
            "filtro. Agregarlos a la UI antes de incorporarlos."
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
            salida.append(dict(actual))
            continue

        fila = dict(actual)
        for campo in CAMPOS_DE_AIRE:
            antes, despues = actual.get(campo), fresco[campo]
            if antes != despues:
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

    informe = {
        "fecha": date.today().isoformat(),
        "cambios": cambios,
        "altas": altas,
        "sin_contraparte": sin_contraparte,
        "deriva_estados": (estados_movidos / len(actuales)) if actuales else 0.0,
        "candidatos_excluidos": candidatos_excluidos,
        "almacenamiento_incoherente": [
            f["c"] for f in snapshot if f.get("al") is True and f.get("ak") == 0
        ],
        "total": len(salida),
        "universo_aire": len(snapshot),
        "con_almacenamiento_aire": sum(1 for f in snapshot if f.get("al") is True),
    }

    _valida_guardas(salida, informe, estados_conocidos, municipios_conocidos, total_minimo)
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
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_merge.py -v`
Expected: PASS, 18 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/merge.py tests/test_merge.py
git commit -m "feat: fusion con 7 guardas, regla de altas GD y reporte de cambios"
```

---

### Task 6: CLI de build

**Files:**
- Create: `scripts/build_data.py`
- Create: `data/reports/.gitkeep`
- Modify: `index.html` (solo el tramo del `const DATA`)

**Interfaces:**
- Consumes: `scripts.inject.leer_data`, `scripts.inject.reemplazar_data`, `scripts.inject.escribir_atomico`, `scripts.merge.fusionar`, `scripts.merge.render_reporte`.
- Produces: `estados_de_ui(html: str) -> set[str]`, `municipios_de_ui(html: str) -> set[str]`, `main(argv) -> int`.

Las dos primeras extraen `ESTADO_ORDER` y las claves de `DEPT_MAP` del propio `index.html`, para que las guardas 6 y 7 se validen contra lo que la UI realmente conoce y no contra una copia que se desincroniza.

- [ ] **Step 1: Escribir la implementación**

`scripts/build_data.py`:

```python
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

from scripts.inject import escribir_atomico, leer_data, reemplazar_data
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

    html = args.index.read_text(encoding="utf-8")
    actuales = leer_data(html)
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
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
```

- [ ] **Step 2: Correr en seco y leer el reporte**

Run: `python -m scripts.build_data --snapshot data/snapshots/aire-2026-09-10.json --dry-run`

Expected: el build **aborta** con la guarda de municipios, nombrando `EL PI¿ON`. Eso es correcto: `DEPT_MAP` todavía no tiene esa clave, y la tarea 7 la agrega. Anotar el mensaje exacto.

Si en cambio aborta por la guarda de estados nombrando `Normalizado`, revisar: ningún registro de la BD tiene ese estado, así que significaría que un alta indebida entró por la regla.

- [ ] **Step 3: Commit**

```bash
git add scripts/build_data.py data/reports/
git commit -m "feat: CLI de build con dry-run y guardas leidas de la propia UI"
```

---

### Task 7: DEPT_MAP y filtro de almacenamiento

**Files:**
- Modify: `index.html:398` (`DEPT_MAP`)
- Modify: `index.html:279` (sección de filtros del sidebar)
- Modify: `index.html:466-483` (`state` y `passesOtherFilters`)
- Modify: `index.html:974-984` (`clearFilters`)
- Modify: `index.html:497-508` (`refresh`)
- Create: `tests/test_ui_contract.py`

**Interfaces:**
- Consumes: `scripts.build_data.municipios_de_ui`, `scripts.build_data.estados_de_ui`.
- Produces: en el JS, `state.soloAlmacenamiento: boolean`, el elemento `#soloAlmacenamiento`, el contador `#almacenamientoCount`, y la función `updateAlmacenamientoCount()`.

No hay toolchain JS en el repo, así que el contrato de la UI se verifica con asserts sobre el texto de `index.html` más una lista de comprobación manual contra el servidor local.

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_ui_contract.py`:

```python
from pathlib import Path

import pytest

from scripts.build_data import estados_de_ui, municipios_de_ui

INDEX = Path(__file__).resolve().parent.parent / "index.html"


@pytest.fixture(scope="module")
def html():
    return INDEX.read_text(encoding="utf-8")


def test_dept_map_cubre_el_pinon_corrupto(html):
    # air-e trae 'EL PI¿ON' (bytes C2 BF) en lugar de 'EL PIÑÓN'. La clave debe
    # usar la forma corrupta o el lookup falla y salen 'Sin clasificar'.
    municipios = municipios_de_ui(html)
    assert "EL PI¿ON" in municipios
    assert municipios["EL PI¿ON"] if isinstance(municipios, dict) else True


def test_dept_map_cubre_los_municipios_del_magdalena_que_faltaban(html):
    municipios = municipios_de_ui(html)
    for nombre in ("SABANAS DE SAN ANGEL", "ZAPAYAN", "ARIGUANI", "PEDRAZA",
                   "PUEBLO VIEJO"):
        assert nombre in municipios, nombre


def test_dept_map_cubre_los_municipios_de_las_altas(html):
    municipios = municipios_de_ui(html)
    for nombre in ("FONSECA", "CIENAGA"):
        assert nombre in municipios, nombre


def test_estado_order_sigue_teniendo_los_siete_estados(html):
    assert len(estados_de_ui(html)) == 7


def test_el_state_tiene_la_bandera_de_almacenamiento(html):
    assert "soloAlmacenamiento:false" in html.replace(" ", "")


def test_passes_other_filters_considera_el_almacenamiento(html):
    inicio = html.index("function passesOtherFilters")
    cuerpo = html[inicio : html.index("function passesFilter")]
    assert "state.soloAlmacenamiento" in cuerpo
    assert "d.al" in cuerpo


def test_existe_el_control_del_filtro(html):
    assert 'id="soloAlmacenamiento"' in html
    assert 'id="almacenamientoCount"' in html


def test_clear_filters_resetea_el_almacenamiento(html):
    inicio = html.index("document.getElementById('clearFilters')")
    cuerpo = html[inicio : inicio + 900]
    assert "soloAlmacenamiento" in cuerpo


def test_refresh_actualiza_el_contador(html):
    inicio = html.index("function refresh()")
    cuerpo = html[inicio : html.index("// ---------- table view ----------")]
    assert "updateAlmacenamientoCount()" in cuerpo
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_ui_contract.py -v`
Expected: FAIL en los 9 tests

- [ ] **Step 3: Agregar las entradas a DEPT_MAP**

En `index.html:398`, dentro del objeto `DEPT_MAP`, agregar estas seis claves. Todas son del Magdalena. La primera arregla los 6 registros que hoy salen como «Sin clasificar»; las otras cinco evitan que futuras incorporaciones caigan ahí.

```javascript
"EL PI¿ON":"Magdalena","SABANAS DE SAN ANGEL":"Magdalena","ZAPAYAN":"Magdalena","ARIGUANI":"Magdalena","PEDRAZA":"Magdalena","PUEBLO VIEJO":"Magdalena"
```

`FONSECA` y `CIENAGA` ya existen, así que no hay que tocarlas.

- [ ] **Step 4: Agregar el control al sidebar**

En `index.html`, justo antes de `<p class="section-label">Fecha de solicitud</p>` (línea 279), insertar:

```html
      <p class="section-label">Almacenamiento de energía</p>
      <label class="check-row" for="soloAlmacenamiento">
        <input type="checkbox" id="soloAlmacenamiento">
        <span>Solo con almacenamiento</span>
        <b class="check-count" id="almacenamientoCount">0</b>
      </label>
    </div>

    <div class="section">
```

Y en el bloque `<style>`, junto a las reglas de `.section-label`:

```css
.check-row{ display:flex; align-items:center; gap:8px; cursor:pointer; font-size:.86rem; }
.check-row input{ margin:0; }
.check-row .check-count{ margin-left:auto; font-variant-numeric:tabular-nums; color:var(--text-muted); }
```

- [ ] **Step 5: Extender el estado y el filtrado**

En `index.html:466`, agregar la bandera al `state`:

```javascript
const state = { search:'', estados:new Set(ESTADO_ORDER), empresas:new Set(), ciudades:new Set(), anio:'', mes:'', soloAlmacenamiento:false, selected:null };
```

En `passesOtherFilters`, después de la comprobación de `state.mes` y antes de la de `state.search`:

```javascript
  if(state.soloAlmacenamiento && d.al !== true) return false;
```

Va en `passesOtherFilters` y no en `passesFilter` para que alimente por igual el mapa, la lista, la vista Tabla, Análisis y los conteos de los chips de estado.

- [ ] **Step 6: Agregar el contador y engancharlo**

Después de `updateEstadoChipCounts` (línea 495), agregar:

```javascript
function updateAlmacenamientoCount(){
  // Cuenta sobre los visibles por los demas filtros, ignorando este, para que
  // el numero diga "cuantos se ven si lo activo".
  const previo = state.soloAlmacenamiento;
  state.soloAlmacenamiento = false;
  const n = DATA.filter(d=>state.estados.has(d.es) && passesOtherFilters(d) && d.al===true).length;
  state.soloAlmacenamiento = previo;
  document.getElementById('almacenamientoCount').textContent = n.toLocaleString('es-CO');
}
```

En `refresh()`, después de `updateEstadoChipCounts();`:

```javascript
  updateAlmacenamientoCount();
```

Al lado de los listeners de `anioBox` y `mesBox` (línea 973):

```javascript
document.getElementById('soloAlmacenamiento').addEventListener('change', (e)=>{ state.soloAlmacenamiento=e.target.checked; refresh(); });
```

Y dentro de `clearFilters`, junto a `state.anio=''`:

```javascript
  state.soloAlmacenamiento=false;
  document.getElementById('soloAlmacenamiento').checked=false;
```

- [ ] **Step 7: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_ui_contract.py -v`
Expected: PASS, 9 tests

- [ ] **Step 8: Correr el build en seco de nuevo**

Run: `python -m scripts.build_data --snapshot data/snapshots/aire-2026-09-10.json --dry-run`

Expected: ahora **no aborta**. El reporte debe mostrar 1.589 registros resultantes, 3 altas (`25857`, `22637`, `26761`), deriva de estados `0.00%`, un único cambio de campo (`ve` del código `23465`, de `'VDA  CHARCO LATA'` a `'VDA CHARCO LATA'`), 0 sin contraparte, y una tabla de candidatos excluidos encabezada por `21489`.

Si la deriva no es 0 o aparecen registros sin contraparte, **parar y revisar el snapshot** antes de escribir.

- [ ] **Step 9: Commit**

```bash
git add index.html tests/test_ui_contract.py
git commit -m "feat: filtro de almacenamiento en el sidebar y DEPT_MAP para El Pinon"
```

---

### Task 8: Almacenamiento en la ficha y en Análisis

**Files:**
- Modify: `index.html:809-832` (`selectPoint`)
- Modify: `index.html:362-366` (markup de la vista Análisis)
- Modify: `index.html:598-659` (`buildAnalysisSkeleton`)
- Modify: `index.html:497-508` (`refresh`)
- Modify: `tests/test_ui_contract.py`

**Interfaces:**
- Consumes: `state`, `getFiltered`, `setView`, `selectPoint`, `escAttr`, `DEPT_MAP`.
- Produces: `renderAlmacenamiento()`, `almacenamientoTexto(d)`, y los elementos `#almbody`, `#almcnt`, `#almkwh`, `.almacenamiento-section`.

- [ ] **Step 1: Agregar los tests que fallan**

Añadir al final de `tests/test_ui_contract.py`:

```python
def test_la_ficha_muestra_el_almacenamiento(html):
    inicio = html.index("function selectPoint")
    cuerpo = html[inicio : html.index("document.getElementById('detailClose')")]
    assert "Almacenamiento" in cuerpo
    assert "almacenamientoTexto" in cuerpo


def test_almacenamiento_texto_distingue_sin_dato(html):
    inicio = html.index("function almacenamientoTexto")
    cuerpo = html[inicio : inicio + 400]
    assert "Sin dato" in cuerpo
    # 'No' solo debe salir cuando al es exactamente false, no cuando es null.
    assert "=== false" in cuerpo or "===false" in cuerpo


def test_existe_la_seccion_de_analisis(html):
    assert "almacenamiento-section" in html
    assert 'id="almbody"' in html
    assert 'id="almcnt"' in html
    assert 'id="almkwh"' in html


def test_la_tabla_de_analisis_tiene_las_nueve_columnas(html):
    inicio = html.index("almacenamiento-section")
    cuerpo = html[inicio : inicio + 1800]
    for columna in ("Código", "Empresa", "Cliente", "Municipio",
                    "Tipo de generación", "Estado air-e", "Estado Sheet",
                    "Fecha solicitud", "Capacidad"):
        assert columna in cuerpo, columna


def test_render_almacenamiento_se_llama_desde_refresh(html):
    inicio = html.index("function refresh()")
    cuerpo = html[inicio : html.index("// ---------- table view ----------")]
    # No puede depender de renderAnalysis: esa funcion tiene un return temprano
    # cuando no hay cambios de estado.
    assert "renderAlmacenamiento()" in cuerpo


def test_render_almacenamiento_ordena_por_capacidad(html):
    inicio = html.index("function renderAlmacenamiento")
    cuerpo = html[inicio : inicio + 2200]
    assert "sort" in cuerpo
    assert "b.ak" in cuerpo or "ak - a.ak" in cuerpo.replace(" ", "")


def test_render_almacenamiento_tiene_estado_vacio(html):
    inicio = html.index("function renderAlmacenamiento")
    cuerpo = html[inicio : inicio + 2200]
    assert "alm-empty" in cuerpo
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_ui_contract.py -v`
Expected: FAIL en los 7 tests nuevos, PASS en los 9 anteriores

- [ ] **Step 3: Agregar el helper y la línea en la ficha**

Antes de `function selectPoint` (línea 809), agregar:

```javascript
function almacenamientoTexto(d){
  if(d.al === true) return 'Sí — '+Number(d.ak||0).toLocaleString('es-CO')+' kWh';
  if(d.al === false) return 'No';
  return 'Sin dato';
}
```

Dentro de `selectPoint`, en el `<dl class="dl">`, después de la fila de Tecnología:

```javascript
      '<dt>Almacenamiento</dt><dd>'+almacenamientoTexto(d)+'</dd>'+
```

- [ ] **Step 4: Agregar los estilos**

En el bloque `<style>`, junto a las reglas de `.changes-table`:

```css
.alm-head{ display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; }
.alm-total{ font-size:.82rem; color:var(--text-muted); font-variant-numeric:tabular-nums; }
.alm-scroll{ max-height:340px; overflow:auto; }
.alm-table td.kwh, .alm-table th.kwh{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
.alm-empty{ padding:14px; font-size:.86rem; color:var(--text-muted); }
```

- [ ] **Step 5: Agregar la sección al esqueleto de Análisis**

En `buildAnalysisSkeleton`, después del bloque `changes-section` (línea 616) y antes de `html += years.map(...)`:

```javascript
  html += '<section class="analysis-batch almacenamiento-section">'+
      '<div class="analysis-batch-head alm-head">'+
        '<h2 class="analysis-batch-title">Proyectos con almacenamiento</h2>'+
        '<span class="analysis-batch-count" id="almcnt"></span>'+
        '<span class="alm-total" id="almkwh"></span>'+
      '</div>'+
      '<p class="section-note">Capacidad declarada en la solicitud CREG030. Respeta los filtros activos.</p>'+
      '<div class="table-scroll alm-scroll">'+
        '<table class="changes-table alm-table">'+
          '<thead><tr>'+
            '<th>Código</th><th>Empresa</th><th>Cliente</th><th>Municipio</th>'+
            '<th>Tipo de generación</th><th>Estado air-e</th><th>Estado Sheet</th>'+
            '<th>Fecha solicitud</th><th class="kwh">Capacidad (kWh)</th>'+
          '</tr></thead>'+
          '<tbody id="almbody"></tbody>'+
        '</table>'+
      '</div>'+
    '</section>';
```

- [ ] **Step 6: Escribir el render**

Después de `renderAnalysis` (línea 712), agregar:

```javascript
function renderAlmacenamiento(){
  const rows = getFiltered().filter(d=>d.al===true).sort((a,b)=>Number(b.ak||0)-Number(a.ak||0));
  const kwh = rows.reduce((acc,d)=>acc+Number(d.ak||0), 0);
  document.getElementById('almcnt').textContent = '('+rows.length.toLocaleString('es-CO')+' solicitud'+(rows.length===1?'':'es')+')';
  document.getElementById('almkwh').textContent = kwh.toLocaleString('es-CO')+' kWh en total';

  const body = document.getElementById('almbody');
  const tabla = document.querySelector('.almacenamiento-section .alm-table');
  document.querySelector('.alm-empty')?.remove();
  if(!rows.length){
    tabla.hidden = true;
    body.innerHTML = '';
    document.querySelector('.alm-scroll').insertAdjacentHTML('beforeend',
      '<div class="alm-empty">Ninguna solicitud visible cuenta con almacenamiento.</div>');
    return;
  }
  tabla.hidden = false;
  body.innerHTML = rows.map(d=>
    '<tr data-code="'+escAttr(d.c)+'">'+
      '<td class="code">#'+d.c+'</td>'+
      '<td title="'+escAttr(d.e||'')+'">'+(d.e||'—')+'</td>'+
      '<td title="'+escAttr(d.cl||'')+'">'+(d.cl||'—')+'</td>'+
      '<td>'+(d.ci||'—')+'</td>'+
      '<td>'+(d.tg||'—')+'</td>'+
      '<td>'+(d.es||'—')+'</td>'+
      '<td>'+(d.se || '—')+'</td>'+
      '<td class="mono">'+(d.f||'—')+'</td>'+
      '<td class="kwh">'+Number(d.ak||0).toLocaleString('es-CO')+'</td>'+
    '</tr>'
  ).join('');
  body.querySelectorAll('tr').forEach(tr=>{
    tr.addEventListener('click', ()=>{
      const d = DATA.find(x=>x.c===tr.dataset.code);
      if(!d) return;
      setView('map');
      selectPoint(d);
    });
  });
}
```

- [ ] **Step 7: Llamarlo desde refresh**

En `refresh()`, después de `renderAnalysis();`:

```javascript
  renderAlmacenamiento();
```

Va en `refresh` y no dentro de `renderAnalysis` porque esa función tiene un `return` temprano cuando no hay cambios de estado, y el render quedaría muerto en ese camino.

- [ ] **Step 8: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_ui_contract.py -v`
Expected: PASS, 16 tests

- [ ] **Step 9: Commit**

```bash
git add index.html tests/test_ui_contract.py
git commit -m "feat: almacenamiento en la ficha y tabla de proyectos en Analisis"
```

---

### Task 9: Ejecutar el build, verificar y cerrar

**Files:**
- Modify: `index.html` (`const DATA` y el footer)
- Create: `data/snapshots/aire-2026-09-10.json` (ya existe de la tarea 3)
- Create: `data/reports/cambios-2026-09-10.md`
- Create: `scripts/README.md`

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: el `index.html` final con 1.589 registros.

- [ ] **Step 1: Actualizar el footer**

En `index.html`, en el `div.sidebar-foot`, cambiar la fecha:

```html
<div class="sidebar-foot">Fuente: servicios.air-e.com/CREG030 &middot; Actualizado 2026-09-10</div>
```

- [ ] **Step 2: Correr la suite completa**

Run: `python -m pytest -v`
Expected: PASS, 50 tests (7 + 16 + 7 + 18 + 16 sobre `index.html` antes del build)

- [ ] **Step 3: Correr el build de verdad**

Run: `python -m scripts.build_data --snapshot data/snapshots/aire-2026-09-10.json`
Expected: `1589 registros escritos en index.html` y `reporte en data/reports/cambios-2026-09-10.md`

- [ ] **Step 4: Verificar el resultado**

Run:

```bash
python -c "
from pathlib import Path
from scripts.inject import leer_data
filas = leer_data(Path('index.html').read_text(encoding='utf-8'))
por_codigo = {f['c']: f for f in filas}
print('total:', len(filas))
print('con almacenamiento:', sum(1 for f in filas if f.get('al') is True))
print('kWh:', sum(float(f.get('ak') or 0) for f in filas if f.get('al') is True))
print('altas presentes:', all(c in por_codigo for c in ('25857','22637','26761')))
print('empresa 25857:', por_codigo['25857']['e'], '| se:', repr(por_codigo['25857']['se']))
print('vereda 23465:', repr(por_codigo['23465']['ve']))
print('golden 21941:', por_codigo['21941']['f'], por_codigo['21941']['es'], por_codigo['21941']['al'])
print('empresas preservadas OTACC:', sum(1 for f in filas if f['e']=='OTACC'))
print('sin coords:', sum(1 for f in filas if f.get('la') is None))
"
```

Expected: `total: 1589`; `con almacenamiento: 5`; `kWh: 12947.0`; `altas presentes: True`; `empresa 25857: GECELCA | se: ''`; `vereda 23465: 'VDA CHARCO LATA'`; `golden 21941: 2024-10-30 14:32 Estudio solicitud False`; `empresas preservadas OTACC: 469`; `sin coords: 0`.

Si `OTACC` no da 469, los campos propios se perdieron: revisar `CAMPOS_PROPIOS` en `merge.py`.

- [ ] **Step 5: Leer el reporte de cambios**

Run: `cat data/reports/cambios-2026-09-10.md`

Confirmar que declara: 1.589 registros, deriva `0.00%`, 3 altas, un solo cambio de campo, 0 sin contraparte, `21489` entre los candidatos excluidos, y los 3 códigos con almacenamiento incoherente.

- [ ] **Step 6: Verificación manual en el navegador**

Levantar el servidor si no está corriendo:

Run: `python -m http.server 8080 --directory . --bind 127.0.0.1`

Abrir `http://127.0.0.1:8080/` y comprobar:

1. El contador del sidebar dice `1.589 resultados`.
2. `Solo con almacenamiento` muestra el contador en `5`; al activarlo el mapa queda con 5 marcadores y el contador de resultados dice `5 resultados`.
3. Con el filtro activo, la pestaña **Análisis** muestra `Proyectos con almacenamiento (5 solicitudes)` y `12.947 kWh en total`, con `25857` primero.
4. La columna `Estado Sheet` muestra `—` en las tres altas.
5. Clic en una fila de esa tabla lleva al mapa y abre la ficha.
6. La ficha de `25857` muestra `Almacenamiento: Sí — 6.517 kWh`, y la de `21941` muestra `No`.
7. `GECELCA` aparece en el filtro de empresas.
8. En Análisis, `Departamentos más movidos` **no** muestra `Sin clasificar` con 6 registros.
9. `Limpiar filtros` desactiva el check y vuelve a 1.589.
10. La vista Tabla sigue con sus 7 columnas y sin columna de almacenamiento.

- [ ] **Step 7: Documentar cómo se corre**

`scripts/README.md`:

```markdown
# Pipeline de datos del radar

Dos comandos. El primero habla con air-e, el segundo toca `index.html`.

```bash
# 1. Bajar el historico completo y escribir el snapshot
python -m scripts.fetch_aire

# 2. Revisar el diff SIN escribir nada
python -m scripts.build_data --snapshot data/snapshots/aire-<fecha>.json --dry-run

# 3. Si el reporte se ve bien, escribir
python -m scripts.build_data --snapshot data/snapshots/aire-<fecha>.json
```

Correr los tests: `python -m pytest`

## Cosas que hay que saber

- **La ventana de fechas es semiabierta.** `FECHAFIN` es exclusivo a las 00:00,
  así que cerrar en el último día del mes pierde todo lo creado ese día. En el
  histórico completo eso ocultaba 272 registros.
- **air-e responde UTF-8.** Se decodifica desde bytes con `.decode("utf-8")`.
  Recodificar desde Latin-1 corrompe cada acento y produce cambios fantasma.
- **`EL PI¿ON`** es cómo air-e escribe El Piñón. La clave de `DEPT_MAP` usa la
  forma corrupta a propósito.
- **Las altas necesitan empresa asignada a mano** en `EMPRESAS_ALTAS`. Si la
  regla de almacenamiento captura un código nuevo sin empresa, el build falla y
  lo pide: no inventa el valor.
- Las 7 guardas abortan sin escribir. Si una se dispara, el mensaje dice qué
  revisar.
```

- [ ] **Step 8: Commit**

```bash
git add index.html data/snapshots data/reports scripts/README.md
git commit -m "feat: 1.589 registros validados contra air-e con almacenamiento

Primera corrida del pipeline. El diff contra air-e es de un solo campo: la
vereda del 23465 pierde un espacio doble. Los otros 1.585 registros ya
coincidian, asi que esta corrida certifica la BD en lugar de corregirla.

Altas: 25857 y 22637 (GECELCA, Fonseca, ~6 MWh cada uno) y 26761
(GreenYellow, Cienaga, 215 kWh). Total 1.589.

DEPT_MAP gana EL PI¿ON y cinco municipios del Magdalena, con lo que 6
registros dejan de aparecer como Sin clasificar."
```

---

## Self-Review

**Cobertura del spec.** Cada sección tiene tarea: fuente de datos y ventana
semiabierta en la 1; encoding en la 1; mapeo, normalización, huso y redondeo en
la 2; snapshot slim en la 3; reinyección en la 4; reglas de fusión, altas,
campos propios y las 7 guardas en la 5; orquestación y reporte en la 6; sidebar,
`DEPT_MAP` y el filtro en la 7; ficha y tabla de Análisis en la 8; footer,
verificación y documentación en la 9. Los goldens `21941` y `22810` están en la
tarea 2 y se revalidan en la 9. Los reportes de códigos del sheet sin
contraparte y del universo no incorporado salen de `render_reporte` en la 5.

**Un hueco consciente:** el reporte del universo air-e no incorporado por
tipo/estado/mes no tiene tarea propia. `render_reporte` incluye los candidatos
excluidos con almacenamiento, que es la parte que alimenta una decisión
inmediata; el desglose completo del universo es un análisis aparte y no bloquea
esta entrega. Queda como nota para la siguiente iteración.

**Placeholders.** Ninguno. Cada paso de código lleva el código real, cada `Run:`
lleva su salida esperada, y los valores verificables (1.589, 5, 12.947 kWh,
`VDA CHARCO LATA`, 469 de OTACC) vienen de la medición, no de una estimación.

**Consistencia de tipos.** `c` es string en todo el recorrido: `to_row` lo
fuerza con `str()`, `merge` indexa por él y el JS compara `x.c===tr.dataset.code`.
`al` es `True`/`False`/`None` en Python y `true`/`false`/`null` en JS, y tanto
`almacenamientoTexto` como `passesOtherFilters` comparan con `=== true` /
`=== false` para no confundir `null` con `No`. `ak` es float en Python y number
en JS. `municipios_de_ui` y `estados_de_ui` devuelven `set[str]`, que es lo que
`fusionar` espera en `estados_conocidos` y `municipios_conocidos`.

**Una corrección aplicada durante la revisión:** el test
`test_dept_map_cubre_el_pinon_corrupto` tenía un assert de más que dependía de si
`municipios_de_ui` devolvía dict o set. Como devuelve `set[str]`, el segundo
assert es ruido; al implementar la tarea 7, dejar solo
`assert "EL PI¿ON" in municipios`.
