# Análisis XM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "Análisis XM" section to the radar's existing Análisis view, built from a periodic XM promoters export, that categorizes projects as minigranjas/GD (≤1MW) vs proyectos mayores (>1MW), shows a timeline of MW entering operation, breaks down by zone/promoter, and flags which projects likely already have a matching air-e request.

**Architecture:** A new Python ingestion pipeline (`xm_transform.py` + `build_xm.py`) mirrors the existing air-e pipeline's shape — CSV in, transform, inject a second embedded array `XM_DATA` into `index.html` alongside the existing `DATA` — but skips air-e's merge/guard machinery entirely, since each run fully replaces `XM_DATA` rather than merging into a curated base. `inject.py` is generalized to splice any named `const X = [...]` block instead of only `DATA`. The air-e cross-reference is computed client-side in JS at render time (reading both `DATA` and `XM_DATA` already in the page), not baked into the Python pipeline, so it never goes stale between the two data sources' independent refresh cycles.

**Tech Stack:** Python 3.12 stdlib (`csv`, `json`, `argparse`, `datetime`, `re`), pytest; vanilla JS in `index.html` reusing existing CSS classes and helpers (no new frontend dependencies).

**Spec:** `docs/superpowers/specs/2026-09-25-analisis-xm-design.md`

## Global Constraints

- Categorization threshold: `mw <= 1` → minigranja/GD, `mw > 1` → proyecto mayor. Computed on the fly in JS from `mw`, never stored as a redundant field.
- Timeline date: use `Fecha de Puesta en Operación Oficial` when present; otherwise fall back to `FPO` (free-text Spanish date). Every `XM_DATA` record carries `fpoc` (`true` = confirmed/Oficial, `false` = estimated/FPO texto) so the UI can distinguish them.
- The 3 garbage rows in the XM CSV (2 fully blank + 1 Excel filter-metadata row) are identified by `CEN [MW]` failing to parse as a float — never by `Código` being non-empty.
- Air-e cross-reference only evaluates XM projects with `ar == "Caribe"` and `sa` in `{Atlantico, Bolivar, GCM}` (the only XM subáreas overlapping air-e's `DEPT_MAP` coverage: Atlántico, Bolívar, Cesar, La Guajira, Magdalena). Everything else is `sin match` by construction, never evaluated against `DATA`.
- The cross-reference is a client-side JS computation only. It never writes to or mutates `DATA`.
- `inject.py`'s public functions default to `nombre="DATA"` so every existing caller (`build_data.py`) keeps working unchanged.
- All file I/O against `index.html` goes through `leer_html`/`escribir_atomico` (preserves CRLF, atomic write) — never open/write it directly.

## Review Focus

- Blank or filter-metadata CSV rows (no numeric `CEN [MW]`) must never appear as phantom projects with `mw == 0`.
- Projects without a `Fecha de Puesta en Operación Oficial` (190 of 386 today, mostly minigranjas) must still appear in the timeline via the `FPO` texto fallback — not silently dropped.
- Cross-reference badges must never show "Alta confianza" (or any confidence) for an XM project outside `Área operativa == "Caribe"` or in a subárea with no department overlap (`Cordoba_Sucre`, `Cerromatoso`) — those must always render `sin-match` without evaluating against `DATA`.
- A project with no `Puntos de Conexión` (8 of 386 today) must render as `—` in the table and must not throw when the place-extraction heuristic runs on `null`.
- Re-running `build_xm.py` with a newer CSV must fully replace `XM_DATA` (no duplicate/stale entries left behind) and must leave `DATA` (air-e) byte-identical.

---

## Task 1: `xm_transform.py` — filtrado de filas basura

**Files:**
- Create: `scripts/xm_transform.py`
- Test: `tests/test_xm_transform.py`

**Interfaces:**
- Produces: `is_valid_row(row: dict) -> bool`, module constants `COL_CODIGO`, `COL_PROYECTO`, `COL_MW`, `COL_FPO_TEXTO`, `COL_AREA`, `COL_SUBAREA`, `COL_PROMOTOR`, `COL_PUNTO_CONEXION`, `COL_OEF`, `COL_FECHA_OFICIAL` (the raw CSV column header strings).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_xm_transform.py
from scripts.xm_transform import COL_MW, is_valid_row


def test_is_valid_row_acepta_fila_con_mw_numerico():
    assert is_valid_row({COL_MW: "19.5"}) is True


def test_is_valid_row_rechaza_fila_vacia():
    assert is_valid_row({COL_MW: ""}) is False


def test_is_valid_row_rechaza_fila_de_metadata_del_filtro():
    # La exportacion de Excel agrega una fila cuyo "Codigo" es la
    # descripcion del filtro aplicado, sin CEN [MW].
    fila = {
        "Código": "Filtros aplicados: \nEstado del proyecto_x es En trámite",
        COL_MW: "",
    }
    assert is_valid_row(fila) is False


def test_is_valid_row_rechaza_mw_no_numerico():
    assert is_valid_row({COL_MW: "n/a"}) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_xm_transform.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.xm_transform'`

- [ ] **Step 3: Write the implementation**

```python
# scripts/xm_transform.py
"""Conversion de la exportacion de promotores de XM al esquema del radar.

Funciones puras: sin red, sin I/O. La exportacion de Excel trae basura que no
son proyectos (filas vacias, una fila de metadata del filtro aplicado); este
modulo filtra eso antes de transformar.
"""

from __future__ import annotations

COL_CODIGO = "Código"
COL_PROYECTO = "Proyecto"
COL_MW = "CEN [MW]"
COL_FPO_TEXTO = "FPO"
COL_AREA = "Área operativa"
COL_SUBAREA = "Subárea operativa"
COL_PROMOTOR = "Promotor"
COL_PUNTO_CONEXION = "Puntos de Conexión"
COL_OEF = "OEF"
COL_FECHA_OFICIAL = "Fecha de Puesta en Operación Oficial"


def is_valid_row(row: dict) -> bool:
    """True si `CEN [MW]` parsea como numero.

    Filtra dos tipos de fila basura que trae la exportacion de Excel: filas
    completamente vacias, y una fila de metadata del filtro aplicado (su
    `Codigo` es la descripcion del filtro, no un codigo real, y no tiene
    `CEN [MW]`). Ninguna de las dos tiene un `CEN [MW]` numerico, asi que
    filtrar por eso -y no por `Codigo` vacio- descarta ambas de una vez.
    """
    try:
        float(row.get(COL_MW, ""))
        return True
    except ValueError:
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_xm_transform.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/xm_transform.py tests/test_xm_transform.py
git commit -m "feat: filtrado de filas basura para la exportacion de XM"
```

---

## Task 2: `xm_transform.py` — resolución de la fecha FPO

**Files:**
- Modify: `scripts/xm_transform.py`
- Test: `tests/test_xm_transform.py`

**Interfaces:**
- Consumes: `COL_FECHA_OFICIAL`, `COL_FPO_TEXTO` from Task 1.
- Produces: `parse_fecha_oficial(value: str) -> str`, `parse_fpo_texto(value: str) -> str`, `resolve_fpo(row: dict) -> tuple[str, bool]` (fecha `YYYY-MM-DD`, `True` si vino de Oficial).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_xm_transform.py (agregar al final)
import pytest

from scripts.xm_transform import parse_fecha_oficial, parse_fpo_texto, resolve_fpo


def test_parse_fecha_oficial_golden_prog00107():
    assert parse_fecha_oficial("06/20/2026 00:00:00") == "2026-06-20"


def test_parse_fecha_oficial_rechaza_formato_desconocido():
    with pytest.raises(ValueError):
        parse_fecha_oficial("2026-06-20")


def test_parse_fpo_texto_golden_prog05157():
    assert parse_fpo_texto("lunes, junio 01, 2026") == "2026-06-01"


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("sábado, junio 20, 2026", "2026-06-20"),
        ("viernes, febrero 28, 2025", "2025-02-28"),
        ("martes, diciembre 30, 2025", "2025-12-30"),
        ("domingo, enero 1, 2027", "2027-01-01"),
    ],
)
def test_parse_fpo_texto_cubre_los_doce_meses_en_espanol(texto, esperado):
    assert parse_fpo_texto(texto) == esperado


def test_parse_fpo_texto_rechaza_formato_desconocido():
    with pytest.raises(ValueError, match="FPO no reconocido"):
        parse_fpo_texto("2026-06-20")


def test_parse_fpo_texto_rechaza_mes_desconocido():
    with pytest.raises(ValueError, match="mes no reconocido"):
        parse_fpo_texto("lunes, mesinventado 01, 2026")


def test_resolve_fpo_prefiere_oficial_cuando_existe():
    row = {
        "FPO": "sábado, junio 20, 2026",
        "Fecha de Puesta en Operación Oficial": "06/20/2026 00:00:00",
    }
    assert resolve_fpo(row) == ("2026-06-20", True)


def test_resolve_fpo_cae_a_fpo_texto_si_oficial_esta_vacia():
    # Caso real: PROG05157, sin Fecha Oficial.
    row = {"FPO": "lunes, junio 01, 2026", "Fecha de Puesta en Operación Oficial": ""}
    assert resolve_fpo(row) == ("2026-06-01", False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_xm_transform.py -v`
Expected: FAIL — `parse_fecha_oficial`, `parse_fpo_texto`, `resolve_fpo` no existen.

- [ ] **Step 3: Write the implementation**

```python
# scripts/xm_transform.py (agregar)
import re
from datetime import datetime

_MESES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
}
_FPO_TEXTO = re.compile(
    r"^[a-záéíóúñ]+,\s*([a-záéíóúñ]+)\s+(\d{1,2}),\s*(\d{4})$", re.IGNORECASE
)


def parse_fecha_oficial(value: str) -> str:
    """'06/20/2026 00:00:00' -> '2026-06-20'."""
    momento = datetime.strptime(value.strip(), "%m/%d/%Y %H:%M:%S")
    return momento.strftime("%Y-%m-%d")


def parse_fpo_texto(value: str) -> str:
    """'lunes, junio 01, 2026' -> '2026-06-01'."""
    coincidencia = _FPO_TEXTO.match(value.strip())
    if coincidencia is None:
        raise ValueError(f"FPO no reconocido: {value!r}")
    mes_nombre, dia, anio = coincidencia.groups()
    mes = _MESES_ES.get(mes_nombre.lower())
    if mes is None:
        raise ValueError(f"mes no reconocido: {mes_nombre!r}")
    return f"{int(anio):04d}-{mes:02d}-{int(dia):02d}"


def resolve_fpo(row: dict) -> tuple[str, bool]:
    """Fecha de entrada en operacion y si es confirmada (Oficial) o estimada.

    `Fecha de Puesta en Operacion Oficial` solo esta poblada para proyectos
    grandes/con obligacion firme (196 de 386 en la exportacion de sept-2026).
    El resto -casi todo minigranjas- solo tiene la estimacion del promotor en
    `FPO`. Usar solo Oficial dejaria a la mayoria de las minigranjas fuera de
    la linea de tiempo.
    """
    oficial = row.get(COL_FECHA_OFICIAL, "").strip()
    if oficial:
        return parse_fecha_oficial(oficial), True
    return parse_fpo_texto(row.get(COL_FPO_TEXTO, "")), False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_xm_transform.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/xm_transform.py tests/test_xm_transform.py
git commit -m "feat: resolucion de fecha FPO con fallback a texto libre"
```

---

## Task 3: `xm_transform.py` — ensamblado y filtrado completo

**Files:**
- Modify: `scripts/xm_transform.py`
- Test: `tests/test_xm_transform.py`

**Interfaces:**
- Consumes: `is_valid_row` (Task 1), `resolve_fpo` (Task 2), all `COL_*` constants.
- Produces: `XM_FIELDS: tuple[str, ...]`, `to_row(row: dict) -> dict`, `filtrar_y_transformar(rows: list[dict]) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_xm_transform.py (agregar al final)
from scripts.xm_transform import XM_FIELDS, filtrar_y_transformar, to_row


def test_to_row_mapea_el_registro_completo():
    row = {
        "Código": "PROG00107",
        "Proyecto": "Prosperidad",
        "CEN [MW]": "19.5",
        "FPO": "sábado, junio 20, 2026",
        "Área operativa": "Caribe",
        "Subárea operativa": "Atlantico",
        "Promotor": "LA PROSPERIDAD SOLAR S.A.S.",
        "Puntos de Conexión": "Salamina 34.5 kV",
        "OEF": "NO",
        "Fecha de Puesta en Operación Oficial": "06/20/2026 00:00:00",
    }
    out = to_row(row)
    assert out["co"] == "PROG00107"
    assert out["pr"] == "Prosperidad"
    assert out["mw"] == 19.5
    assert out["fpo"] == "2026-06-20"
    assert out["fpoc"] is True
    assert out["ar"] == "Caribe"
    assert out["sa"] == "Atlantico"
    assert out["pm"] == "LA PROSPERIDAD SOLAR S.A.S."
    assert out["pc"] == "Salamina 34.5 kV"
    assert out["oef"] is False
    assert set(out) == set(XM_FIELDS)


def test_to_row_punto_conexion_vacio_es_none():
    row = {
        "Código": "PROG00002", "Proyecto": "Dos", "CEN [MW]": "0.9",
        "FPO": "lunes, marzo 02, 2026", "Área operativa": "Caribe",
        "Subárea operativa": "GCM", "Promotor": "PROMOTOR DOS SAS",
        "Puntos de Conexión": "", "OEF": "NO",
        "Fecha de Puesta en Operación Oficial": "",
    }
    out = to_row(row)
    assert out["pc"] is None
    assert out["fpoc"] is False
    assert out["fpo"] == "2026-03-02"


def test_to_row_oef_si_da_true():
    row = {
        "Código": "X", "Proyecto": "Y", "CEN [MW]": "1",
        "FPO": "lunes, marzo 02, 2026", "Área operativa": "Caribe",
        "Subárea operativa": "GCM", "Promotor": "Z", "Puntos de Conexión": "",
        "OEF": "SI", "Fecha de Puesta en Operación Oficial": "",
    }
    assert to_row(row)["oef"] is True


def test_filtrar_y_transformar_descarta_basura_y_ordena_por_codigo():
    rows = [
        {
            "Código": "PROG00002", "Proyecto": "Dos", "CEN [MW]": "0.9",
            "FPO": "lunes, marzo 02, 2026", "Área operativa": "Caribe",
            "Subárea operativa": "GCM", "Promotor": "DOS SAS",
            "Puntos de Conexión": "", "OEF": "NO",
            "Fecha de Puesta en Operación Oficial": "",
        },
        {
            "Código": "PROG00001", "Proyecto": "Uno", "CEN [MW]": "19.5",
            "FPO": "sábado, junio 20, 2026", "Área operativa": "Caribe",
            "Subárea operativa": "Atlantico", "Promotor": "UNO SAS",
            "Puntos de Conexión": "Salamina 34.5 kV", "OEF": "NO",
            "Fecha de Puesta en Operación Oficial": "06/20/2026 00:00:00",
        },
        {"Código": "", "Proyecto": "", "CEN [MW]": ""},
        {"Código": "Filtros aplicados: ...", "CEN [MW]": ""},
    ]
    filas = filtrar_y_transformar(rows)
    assert [f["co"] for f in filas] == ["PROG00001", "PROG00002"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_xm_transform.py -v`
Expected: FAIL — `XM_FIELDS`, `to_row`, `filtrar_y_transformar` no existen.

- [ ] **Step 3: Write the implementation**

```python
# scripts/xm_transform.py (agregar)
XM_FIELDS = ("co", "pr", "mw", "fpo", "fpoc", "ar", "sa", "pm", "pc", "oef")


def to_row(row: dict) -> dict:
    """Fila cruda del CSV de XM a esquema del radar. Asume `is_valid_row`."""
    fpo, confirmada = resolve_fpo(row)
    punto_conexion = row.get(COL_PUNTO_CONEXION, "").strip()
    return {
        "co": row[COL_CODIGO].strip(),
        "pr": row[COL_PROYECTO].strip(),
        "mw": float(row[COL_MW]),
        "fpo": fpo,
        "fpoc": confirmada,
        "ar": row[COL_AREA].strip(),
        "sa": row[COL_SUBAREA].strip(),
        "pm": row[COL_PROMOTOR].strip(),
        "pc": punto_conexion or None,
        "oef": row.get(COL_OEF, "").strip() == "SI",
    }


def filtrar_y_transformar(rows: list[dict]) -> list[dict]:
    """Filtra filas basura, transforma las validas y ordena por codigo."""
    filas = [to_row(r) for r in rows if is_valid_row(r)]
    filas.sort(key=lambda f: f["co"])
    return filas
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_xm_transform.py -v`
Expected: PASS (17 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/xm_transform.py tests/test_xm_transform.py
git commit -m "feat: ensamblado de filas XM y filtrado end-to-end"
```

---

## Task 4: `xm_transform.py` — resumen y reporte

**Files:**
- Modify: `scripts/xm_transform.py`
- Test: `tests/test_xm_transform.py`

**Interfaces:**
- Consumes: la forma de fila que produce `to_row` (Task 3).
- Produces: `resumen(filas: list[dict]) -> dict`, `render_reporte(resumen_: dict, *, fecha: str) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_xm_transform.py (agregar al final)
from scripts.xm_transform import render_reporte, resumen

_FILAS_EJEMPLO = [
    {"co": "A", "mw": 0.9, "ar": "Caribe", "pc": None, "fpoc": False},
    {"co": "B", "mw": 19.5, "ar": "Caribe", "pc": "Salamina 34.5 kV", "fpoc": True},
    {"co": "C", "mw": 60.0, "ar": "Suroccidental", "pc": "Popayán 110 kV", "fpoc": True},
]


def test_resumen_separa_minigranjas_de_mayores():
    r = resumen(_FILAS_EJEMPLO)
    assert r["total"] == 3
    assert r["minigranjas"] == 1
    assert r["mw_minigranjas"] == 0.9
    assert r["mayores"] == 2
    assert r["mw_mayores"] == 79.5


def test_resumen_cuenta_por_area():
    r = resumen(_FILAS_EJEMPLO)
    assert r["por_area"] == {"Caribe": 2, "Suroccidental": 1}


def test_resumen_cuenta_sin_punto_de_conexion_y_fecha_estimada():
    r = resumen(_FILAS_EJEMPLO)
    assert r["sin_punto_conexion"] == 1
    assert r["fecha_confirmada"] == 2
    assert r["fecha_estimada"] == 1


def test_render_reporte_incluye_los_totales():
    r = resumen(_FILAS_EJEMPLO)
    texto = render_reporte(r, fecha="2026-09-25")
    assert "2026-09-25" in texto
    assert "**3**" in texto
    assert "Caribe" in texto
    assert "Suroccidental" in texto
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_xm_transform.py -v`
Expected: FAIL — `resumen`, `render_reporte` no existen.

- [ ] **Step 3: Write the implementation**

```python
# scripts/xm_transform.py (agregar)
def resumen(filas: list[dict]) -> dict:
    minigranjas = [f for f in filas if f["mw"] <= 1]
    mayores = [f for f in filas if f["mw"] > 1]
    por_area: dict[str, int] = {}
    for f in filas:
        por_area[f["ar"]] = por_area.get(f["ar"], 0) + 1
    return {
        "total": len(filas),
        "mw_total": round(sum(f["mw"] for f in filas), 1),
        "minigranjas": len(minigranjas),
        "mw_minigranjas": round(sum(f["mw"] for f in minigranjas), 1),
        "mayores": len(mayores),
        "mw_mayores": round(sum(f["mw"] for f in mayores), 1),
        "por_area": por_area,
        "sin_punto_conexion": sum(1 for f in filas if f["pc"] is None),
        "fecha_confirmada": sum(1 for f in filas if f["fpoc"]),
        "fecha_estimada": sum(1 for f in filas if not f["fpoc"]),
    }


def render_reporte(resumen_: dict, *, fecha: str) -> str:
    lineas = [
        f"# Análisis XM — {fecha}",
        "",
        f"- Proyectos: **{resumen_['total']}**",
        f"- MW total: **{resumen_['mw_total']}**",
        f"- Minigranjas/GD (≤1MW): {resumen_['minigranjas']} · "
        f"{resumen_['mw_minigranjas']} MW",
        f"- Proyectos mayores (>1MW): {resumen_['mayores']} · "
        f"{resumen_['mw_mayores']} MW",
        f"- Sin punto de conexión: {resumen_['sin_punto_conexion']}",
        f"- Fecha confirmada (Oficial): {resumen_['fecha_confirmada']}",
        f"- Fecha estimada (FPO texto): {resumen_['fecha_estimada']}",
        "",
        "## Por área operativa",
        "",
        "| Área | Proyectos |",
        "|---|---|",
    ]
    for area, n in sorted(resumen_["por_area"].items(), key=lambda kv: -kv[1]):
        lineas.append(f"| {area} | {n} |")
    lineas.append("")
    return "\n".join(lineas)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_xm_transform.py -v`
Expected: PASS (21 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/xm_transform.py tests/test_xm_transform.py
git commit -m "feat: resumen agregado y reporte en texto para Analisis XM"
```

---

## Task 5: `inject.py` — generalizar el nombre de la constante

**Files:**
- Modify: `scripts/inject.py`
- Modify: `tests/fixtures/index_minimo.html`
- Test: `tests/test_inject.py`

**Interfaces:**
- Produces (nueva forma): `_limites(html: str, nombre: str = "DATA") -> tuple[int, int]`, `leer_data(html: str, *, nombre: str = "DATA") -> list[dict]`, `reemplazar_data(html: str, filas: list[dict], *, nombre: str = "DATA") -> str`.
- Todo caller existente (`build_data.py`, que llama `leer_data(html)` y `reemplazar_data(html, filas)` posicionalmente, sin el tercer argumento) sigue funcionando sin cambios gracias al default.

- [ ] **Step 1: Add `const XM_DATA = [];` to the shared fixture**

Edit `tests/fixtures/index_minimo.html`, adding a line right after the existing `const DATA = [...]` line:

```html
<!doctype html>
<html><body>
<div id="map"></div>
<script>
const DATA = [{"c":"1","e":"ACME","es":"Estudio solicitud","la":10.5,"lo":-74.5},{"c":"2","e":"OTRA","es":"De Baja","la":11.0,"lo":-75.0}];
const XM_DATA = [];
const ESTADO_ORDER = ["Estudio solicitud", "De Baja"];
function refresh(){ return DATA.length; }
</script>
</body></html>
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_inject.py (agregar al final)
def test_leer_data_con_nombre_personalizado_lee_xm_data():
    filas = leer_data(_html(), nombre="XM_DATA")
    assert filas == []


def test_leer_data_con_nombre_personalizado_no_se_confunde_con_data():
    # DATA tiene 2 filas, XM_DATA tiene 0: si el prefijo no fuera exacto,
    # buscar "XM_DATA" podria encontrar el sufijo "DATA" de la otra constante.
    assert len(leer_data(_html())) == 2
    assert len(leer_data(_html(), nombre="XM_DATA")) == 0


def test_reemplazar_data_con_nombre_personalizado_no_toca_data():
    original = _html()
    nuevas_xm = [{"co": "PROG00001", "mw": 19.5}]

    salida = reemplazar_data(original, nuevas_xm, nombre="XM_DATA")

    assert leer_data(salida, nombre="XM_DATA") == nuevas_xm
    assert leer_data(salida) == leer_data(original)


def test_reemplazar_data_falla_si_no_encuentra_el_prefijo_personalizado():
    with pytest.raises(InjectError, match="const XM_DATA"):
        reemplazar_data("<html><body>sin xm data</body></html>", [], nombre="XM_DATA")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_inject.py -v`
Expected: FAIL — `leer_data()`/`reemplazar_data()` no aceptan `nombre=`.

- [ ] **Step 4: Write the implementation**

Replace the top of `scripts/inject.py` (the `PREFIJO` constant and the three functions that use it):

```python
def _prefijo(nombre: str) -> str:
    return f"const {nombre} = ["


def _limites(html: str, nombre: str = "DATA") -> tuple[int, int]:
    """Indices [inicio, fin) del tramo `const <nombre> = [...]`."""
    prefijo = _prefijo(nombre)
    inicio = html.find(prefijo)
    if inicio == -1:
        raise InjectError(
            f"no se encontro {prefijo!r} en el archivo. "
            "Verificar que sea el index.html del radar."
        )
    corchete = inicio + len(prefijo) - 1
    try:
        _, fin = json.JSONDecoder().raw_decode(html, corchete)
    except json.JSONDecodeError as exc:
        raise InjectError(
            f"el array {nombre} no parsea como JSON: {exc}. "
            "Puede haber quedado a medio escribir por una corrida anterior."
        ) from exc
    return inicio, fin


def leer_data(html: str, *, nombre: str = "DATA") -> list[dict]:
    """Devuelve las filas del `const <nombre>` actual."""
    inicio, fin = _limites(html, nombre)
    corchete = inicio + len(_prefijo(nombre)) - 1
    return json.loads(html[corchete:fin])


def reemplazar_data(html: str, filas: list[dict], *, nombre: str = "DATA") -> str:
    """Devuelve el html con el array `<nombre>` reemplazado por `filas`."""
    inicio, fin = _limites(html, nombre)
    payload = json.dumps(filas, ensure_ascii=False, separators=(",", ":"))
    return html[:inicio] + f"const {nombre} = " + payload + html[fin:]
```

Delete the old module-level `PREFIJO = "const DATA = ["` constant — nothing outside this module imports it (verified: `build_data.py` and `test_inject.py` only import the functions).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_inject.py tests/test_build_data.py tests/test_ui_contract.py -v`
Expected: PASS, including every pre-existing test in these three files (regression check on the default-argument backward compatibility).

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest`
Expected: PASS, all tests (125 pre-existing + new ones so far).

- [ ] **Step 7: Commit**

```bash
git add scripts/inject.py tests/test_inject.py tests/fixtures/index_minimo.html
git commit -m "feat: generalizar inject.py para empalmar cualquier const X = [...]"
```

---

## Task 6: `build_xm.py` — orquestación del pipeline

**Files:**
- Create: `scripts/build_xm.py`
- Create: `tests/fixtures/xm_promotores_minimo.csv`
- Test: `tests/test_build_xm.py`

**Interfaces:**
- Consumes: `filtrar_y_transformar`, `resumen`, `render_reporte` (Task 4), `leer_html`, `leer_data`, `reemplazar_data(..., nombre="XM_DATA")`, `escribir_atomico`, `InjectError` (Task 5).
- Produces: `leer_csv(ruta: Path) -> list[dict]`, `main(argv: list[str] | None = None) -> int`. `main` is the `python -m scripts.build_xm` entrypoint.

- [ ] **Step 1: Create the CSV fixture**

Create `tests/fixtures/xm_promotores_minimo.csv` with this exact content (UTF-8, matching the real export's header and quirks — one row uses the confirmed Oficial date, the other only the FPO texto fallback, plus the two garbage-row shapes seen in the real file):

```csv
Código,Proyecto,CEN [MW],FPO,Tipo,OEF,Área operativa,Tipo OEF,Fecha obligación,Subárea operativa,Promotor,Puntos de Conexión,Fecha de Puesta en Operación Oficial
PROG00001,Proyecto Uno,19.5,"sábado, junio 20, 2026",Solar,NO,Caribe,,,Atlantico,PROMOTOR UNO S.A.S.,Salamina 34.5 kV,06/20/2026 00:00:00
PROG00002,Proyecto Dos,0.9,"lunes, marzo 02, 2026",Solar,NO,Caribe,,,GCM,PROMOTOR DOS SAS,,
,,,,,,,,,,,,
"Filtros aplicados: 
Estado del proyecto_x es En trámite",,,,,,,,,,,,
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_build_xm.py
import json
from pathlib import Path

import pytest

from scripts.build_xm import main
from scripts.inject import leer_data

FIXTURE_CSV = Path(__file__).parent / "fixtures" / "xm_promotores_minimo.csv"
FIXTURE_INDEX = Path(__file__).parent / "fixtures" / "index_minimo.html"


def _index_minimo(tmp_path: Path) -> Path:
    destino = tmp_path / "index.html"
    destino.write_text(FIXTURE_INDEX.read_text(encoding="utf-8"), encoding="utf-8")
    return destino


def test_dry_run_no_escribe_nada(tmp_path, capsys):
    index = _index_minimo(tmp_path)
    contenido_antes = index.read_text(encoding="utf-8")
    snapshot = tmp_path / "snap.json"
    reporte = tmp_path / "reporte.md"

    codigo = main([
        "--csv", str(FIXTURE_CSV),
        "--index", str(index),
        "--snapshot", str(snapshot),
        "--reporte", str(reporte),
        "--dry-run",
    ])

    assert codigo == 0
    assert index.read_text(encoding="utf-8") == contenido_antes
    assert not snapshot.exists()
    assert not reporte.exists()
    assert "Proyectos:" in capsys.readouterr().out


def test_corrida_real_escribe_snapshot_y_reporte(tmp_path):
    index = _index_minimo(tmp_path)
    snapshot = tmp_path / "snap.json"
    reporte = tmp_path / "reporte.md"

    codigo = main([
        "--csv", str(FIXTURE_CSV),
        "--index", str(index),
        "--snapshot", str(snapshot),
        "--reporte", str(reporte),
    ])

    assert codigo == 0
    assert snapshot.exists()
    assert reporte.exists()
    filas = json.loads(snapshot.read_text(encoding="utf-8"))
    assert [f["co"] for f in filas] == ["PROG00001", "PROG00002"]


def test_corrida_real_inyecta_xm_data_sin_tocar_data(tmp_path):
    index = _index_minimo(tmp_path)
    data_antes = leer_data(index.read_text(encoding="utf-8"))

    main([
        "--csv", str(FIXTURE_CSV),
        "--index", str(index),
        "--snapshot", str(tmp_path / "snap.json"),
        "--reporte", str(tmp_path / "reporte.md"),
    ])

    html_despues = index.read_text(encoding="utf-8")
    xm_data = leer_data(html_despues, nombre="XM_DATA")
    assert [f["co"] for f in xm_data] == ["PROG00001", "PROG00002"]
    assert leer_data(html_despues) == data_antes


def test_csv_inexistente_falla_con_mensaje_claro(tmp_path):
    with pytest.raises(SystemExit, match="no se encontro el CSV"):
        main([
            "--csv", str(tmp_path / "no-existe.csv"),
            "--index", str(_index_minimo(tmp_path)),
            "--snapshot", str(tmp_path / "snap.json"),
            "--reporte", str(tmp_path / "reporte.md"),
        ])
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_build_xm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.build_xm'`

- [ ] **Step 4: Write the implementation**

```python
# scripts/build_xm.py
"""Construye el XM_DATA a partir de la exportacion de promotores de XM y lo
inyecta en index.html.

Uso:
    python -m scripts.build_xm --csv "../XM/Promotores 17 de Septiembre 2026.xlsm - Export.csv"
    python -m scripts.build_xm --csv ... --dry-run

Con --dry-run no escribe nada: imprime el reporte por stdout. A diferencia de
build_data.py, no hay reglas de fusion ni guardas: cada corrida reemplaza
XM_DATA por completo, porque no existe una base curada que preservar.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

from scripts.inject import InjectError, escribir_atomico, leer_data, leer_html, reemplazar_data
from scripts.xm_transform import filtrar_y_transformar, render_reporte, resumen

RAIZ = Path(__file__).resolve().parent.parent


def leer_csv(ruta: Path) -> list[dict]:
    with open(ruta, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main(argv: list[str] | None = None) -> int:
    hoy = date.today()
    parser = argparse.ArgumentParser(
        description="Reconstruye el XM_DATA del radar desde una exportacion de XM."
    )
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--index", type=Path, default=RAIZ / "index.html")
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=RAIZ / "data" / "xm" / "snapshots" / f"xm-{hoy.isoformat()}.json",
    )
    parser.add_argument(
        "--reporte",
        type=Path,
        default=RAIZ / "data" / "xm" / "reports" / f"xm-{hoy.isoformat()}.md",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        filas_csv = leer_csv(args.csv)
    except FileNotFoundError:
        raise SystemExit(
            f"no se encontro el CSV en {args.csv}. Verificar la ruta con --csv."
        )

    filas = filtrar_y_transformar(filas_csv)
    if not filas:
        raise SystemExit(
            f"el CSV en {args.csv} no produjo ningun proyecto valido. "
            "Verificar que sea la exportacion correcta de promotores de XM."
        )

    print(
        f"filas del CSV: {len(filas_csv)} | proyectos validos: {len(filas)}",
        file=sys.stderr,
    )

    resumen_ = resumen(filas)
    reporte = render_reporte(resumen_, fecha=hoy.isoformat())

    if args.dry_run:
        print(reporte)
        return 0

    try:
        html = leer_html(args.index)
    except FileNotFoundError:
        raise SystemExit(
            f"no se encontro el index.html en {args.index}. Verificar la ruta con --index."
        )

    salida = reemplazar_data(html, filas, nombre="XM_DATA")

    releidas = leer_data(salida, nombre="XM_DATA")
    if len(releidas) != len(filas):
        raise SystemExit(
            f"el XM_DATA reinyectado reparsea a {len(releidas)} filas y se "
            f"esperaban {len(filas)}. No se escribio nada."
        )

    args.snapshot.parent.mkdir(parents=True, exist_ok=True)
    args.snapshot.write_text(
        json.dumps(filas, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    args.reporte.parent.mkdir(parents=True, exist_ok=True)
    args.reporte.write_text(reporte, encoding="utf-8")
    try:
        escribir_atomico(args.index, salida)
    except InjectError as exc:
        args.reporte.unlink(missing_ok=True)
        raise SystemExit(
            f"{exc}\nNo se escribio {args.index}; se elimino el reporte en "
            f"{args.reporte} para que no quede describiendo un cambio que "
            "nunca se aplico."
        )

    print(
        f"{len(filas)} proyectos escritos en {args.index}\n"
        f"snapshot en {args.snapshot}\n"
        f"reporte en {args.reporte}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_build_xm.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest`
Expected: PASS, all tests.

- [ ] **Step 7: Commit**

```bash
git add scripts/build_xm.py tests/test_build_xm.py tests/fixtures/xm_promotores_minimo.csv
git commit -m "feat: pipeline build_xm.py para inyectar XM_DATA en index.html"
```

---

## Task 7: `index.html` — esqueleto de "Análisis XM" y `XM_DATA` vacío

**Files:**
- Modify: `index.html`
- Test: `tests/test_ui_contract.py`

**Interfaces:**
- Produces (JS globals in `index.html`): `const XM_DATA = [];`, `function buildAnalysisXmSkeleton(){...}`.
- Consumes (existing globals/CSS in `index.html`): `const DATA = [...]` (locate via `html.index("const DATA = [")`), `.analysis-scroll#analysisScroll` container, `.stat-row`/`.stat`, `.insights.insights-analysis`/`.insight-col`/`.insight-title`/`.insight-list.tall`, `.changes-table`/`.changes-scroll`, `.table-toolbar`, `buildAnalysisSkeleton()` and the final init block (`buildAnalysisSkeleton(); refresh();`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ui_contract.py (agregar al final)
def test_existe_xm_data_vacio(html):
    assert "const XM_DATA = [];" in html


def test_existe_la_seccion_analisis_xm(html):
    assert "analysis-xm" in html
    assert "Análisis XM" in html
    assert 'id="xmStats"' in html
    assert 'id="xmTimeline"' in html
    assert 'id="xmZonas"' in html
    assert 'id="xmPromotores"' in html
    assert 'id="xmTableBody"' in html


def test_build_analysis_xm_skeleton_se_llama_en_el_init(html):
    inicio = html.index("buildAnalysisSkeleton();")
    cuerpo = html[inicio : inicio + 400]
    assert "buildAnalysisXmSkeleton()" in cuerpo
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ui_contract.py -v -k analisis_xm or xm_data`
Expected: FAIL — nada de esto existe todavia.

- [ ] **Step 3: Add `XM_DATA` next to `DATA`**

Locate the line containing `const DATA = [` (search for that exact string — it is the single 480KB+ line holding the embedded air-e data; do not scroll past it manually, use string search). Immediately after the `];` that closes it, insert:

```js
const XM_DATA = [];
```

- [ ] **Step 4: Add CSS for the match-confidence badge**

In the `<style>` block, right after the existing `.insight-empty{ font-size:.76rem; color:var(--text-muted); }` rule (around line 182), add:

```css
.xm-badge{ display:inline-block; font-size:.68rem; font-weight:700; padding:2px 8px; border-radius:99px; white-space:nowrap; }
.xm-badge.alta{ background:var(--st-good); color:#fff; }
.xm-badge.posible{ background:var(--st-wait); color:#fff; }
.xm-badge.sin-match{ background:var(--surface-2); color:var(--text-muted); }
.xm-toolbar{ flex-wrap:wrap; gap:12px 16px; }
.xm-toolbar label{ font-size:.72rem; color:var(--text-muted); display:flex; align-items:center; gap:6px; }
```

- [ ] **Step 5: Add the skeleton-building function**

Locate `function buildAnalysisSkeleton(){` and insert this new function immediately before it (reuses `.stat-row`/`.stat` from the sidebar, `.insights.insights-analysis` from the existing year blocks, and `.changes-table`/`.changes-scroll` from the other Análisis tables — no new layout primitives beyond the badge/toolbar CSS from Step 4):

```js
function xmZonasDisponibles(){
  return [...new Set(XM_DATA.map(p=>p.ar))].sort();
}
function buildAnalysisXmSkeleton(){
  const container = document.getElementById('analysisScroll');
  const opcionesZona = xmZonasDisponibles()
    .map(z=>'<option value="'+escAttr(z)+'">'+z+'</option>').join('');
  const html =
    '<section class="analysis-batch analysis-xm">'+
      '<div class="analysis-batch-head">'+
        '<h2 class="analysis-batch-title">Análisis XM</h2>'+
        '<span class="analysis-batch-count" id="xmCount"></span>'+
      '</div>'+
      '<p class="section-note">Promotores de generación solar registrados en XM. No depende de los filtros de air-e del panel izquierdo.</p>'+
      '<div class="stat-row" id="xmStats"></div>'+
      '<div class="insights insights-analysis">'+
        '<div class="insight-col">'+
          '<p class="insight-title">MW por mes de entrada en operación</p>'+
          '<div class="insight-list tall" id="xmTimeline"></div>'+
        '</div>'+
        '<div class="insight-col">'+
          '<p class="insight-title">Zonas con más proyectos</p>'+
          '<div class="insight-list tall" id="xmZonas"></div>'+
        '</div>'+
        '<div class="insight-col">'+
          '<p class="insight-title">Promotores con más proyectos</p>'+
          '<div class="insight-list tall" id="xmPromotores"></div>'+
        '</div>'+
      '</div>'+
      '<div class="table-toolbar xm-toolbar">'+
        '<label>Zona <select id="xmFiltroZona"><option value="">Todas</option>'+opcionesZona+'</select></label>'+
        '<label>Categoría <select id="xmFiltroCategoria"><option value="">Todas</option><option value="gd">Minigranja/GD (&le;1MW)</option><option value="mayor">Proyecto mayor (&gt;1MW)</option></select></label>'+
        '<label>FPO desde <input type="date" id="xmFiltroDesde"></label>'+
        '<label>FPO hasta <input type="date" id="xmFiltroHasta"></label>'+
      '</div>'+
      '<div class="table-scroll changes-scroll">'+
        '<table class="changes-table">'+
          '<thead><tr>'+
            '<th>Código</th><th>Proyecto</th><th>MW</th><th>Categoría</th><th>Fecha FPO</th>'+
            '<th>Zona</th><th>Promotor</th><th>Punto de conexión</th><th>air-e</th>'+
          '</tr></thead>'+
          '<tbody id="xmTableBody"></tbody>'+
        '</table>'+
      '</div>'+
    '</section>';
  container.insertAdjacentHTML('afterbegin', html);
  ['xmFiltroZona','xmFiltroCategoria','xmFiltroDesde','xmFiltroHasta'].forEach(id=>{
    document.getElementById(id).addEventListener('change', ()=>renderAnalysisXmTable());
  });
}
```

- [ ] **Step 6: Wire the init call**

Locate the init sequence near the end of the script:

```js
buildEstadoChips();
buildLegend();
buildDatalists();
buildAnalysisSkeleton();
refresh();
```

Change it to:

```js
buildEstadoChips();
buildLegend();
buildDatalists();
buildAnalysisSkeleton();
buildAnalysisXmSkeleton();
refresh();
```

(`renderAnalysisXm()` — added in Task 8 — will be called from inside `buildAnalysisXmSkeleton()` once it exists; for now the skeleton renders with empty lists, which is correct since `XM_DATA` is still `[]`.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_ui_contract.py -v`
Expected: PASS, all tests including the 3 new ones.

- [ ] **Step 8: Manual smoke check**

Run: `python -m http.server 8765` from the repo root, open `http://localhost:8765/index.html`, click the "Análisis" tab. Confirm the "Análisis XM" block renders at the top with empty stat tiles/lists/table and no console errors (`XM_DATA` is still empty at this point — that's expected).

- [ ] **Step 9: Commit**

```bash
git add index.html tests/test_ui_contract.py
git commit -m "feat: esqueleto de la seccion Analisis XM en index.html"
```

---

## Task 8: `index.html` — tarjetas resumen y línea de tiempo

**Files:**
- Modify: `index.html`
- Test: `tests/test_ui_contract.py`

**Interfaces:**
- Consumes: `XM_DATA` (Task 7), `escAttr` (existing helper, defined near `function escAttr(s){`).
- Produces: `categoriaXm(p)`, `renderXmBarList(elId, entries)`, `mwPorMesXm(rows)`, `formatMesXm(mesIso)`, `renderAnalysisXmStats()`, `renderAnalysisXm()` (top-level orchestrator — later tasks extend it).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ui_contract.py (agregar al final)
def test_existe_categoria_xm(html):
    inicio = html.index("function categoriaXm(")
    cuerpo = html[inicio : inicio + 150]
    assert "mw<=1" in cuerpo.replace(" ", "") or "mw <= 1" in cuerpo


def test_existe_render_xm_bar_list(html):
    assert "function renderXmBarList(" in html


def test_mw_por_mes_xm_ordena_cronologicamente_no_por_magnitud(html):
    inicio = html.index("function mwPorMesXm(")
    cuerpo = html[inicio : inicio + 500]
    # Debe ordenar por la clave (mes), no por el valor (MW) como rankBy.
    assert "localeCompare" in cuerpo


def test_render_analysis_xm_stats_usa_xm_data(html):
    inicio = html.index("function renderAnalysisXmStats(")
    cuerpo = html[inicio : inicio + 900]
    assert "XM_DATA" in cuerpo
    assert "xmStats" in cuerpo


def test_render_analysis_xm_llama_a_las_piezas(html):
    inicio = html.index("function renderAnalysisXm(){")
    cuerpo = html[inicio : inicio + 500]
    assert "renderAnalysisXmStats()" in cuerpo
    assert "renderXmBarList('xmTimeline'" in cuerpo.replace(" ", "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ui_contract.py -v -k "categoria_xm or render_xm_bar_list or mw_por_mes or render_analysis_xm"`
Expected: FAIL — ninguna de estas funciones existe todavia.

- [ ] **Step 3: Write the implementation**

Add these functions right after `buildAnalysisXmSkeleton()` (Task 7):

```js
function categoriaXm(p){ return p.mw<=1 ? 'Minigranja/GD' : 'Proyecto mayor'; }

function formatMesXm(mesIso){
  const [anio, mes] = mesIso.split('-');
  const nombres = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
  return nombres[parseInt(mes,10)-1]+' '+anio;
}

function mwPorMesXm(rows){
  const totales = new Map();
  rows.forEach(p=>{
    const mes = p.fpo.slice(0,7);
    totales.set(mes, (totales.get(mes)||0) + p.mw);
  });
  return Array.from(totales.entries())
    .sort((a,b)=>a[0].localeCompare(b[0]))
    .map(([mes,mw])=>[formatMesXm(mes), Math.round(mw*10)/10]);
}

// Barra rankeada generica, mismo look que .insight-row/.insight-bar, pero sin
// el conteo automatico en el titulo ni el clic-a-modal de renderInsightList:
// las filas de XM no tienen la forma que openRankDetail espera (Codigo,
// Municipio, Departamento, Estado air-e, Fecha solicitud, Potencia AC, Mapa).
function renderXmBarList(elId, entries){
  const el = document.getElementById(elId);
  if(!entries.length){ el.innerHTML = '<p class="insight-empty">Sin datos.</p>'; return; }
  const max = Math.max(...entries.map(e=>e[1]));
  el.innerHTML = entries.map(([name,val])=>
    '<div class="insight-row">'+
      '<span class="insight-name" title="'+name+'">'+name+'</span>'+
      '<span class="insight-bar-wrap"><span class="insight-bar" style="width:'+(max?val/max*100:0)+'%"></span></span>'+
      '<span class="insight-count">'+val.toLocaleString('es-CO')+'</span>'+
    '</div>'
  ).join('');
}

function renderAnalysisXmStats(){
  const total = XM_DATA.length;
  const mwTotal = XM_DATA.reduce((s,p)=>s+p.mw, 0);
  const minigranjas = XM_DATA.filter(p=>p.mw<=1);
  const mayores = XM_DATA.filter(p=>p.mw>1);
  const mwMini = minigranjas.reduce((s,p)=>s+p.mw, 0);
  const mwMayor = mayores.reduce((s,p)=>s+p.mw, 0);
  const fmt = n => n.toLocaleString('es-CO',{maximumFractionDigits:1});
  const stats = [
    [fmt(mwTotal), 'MW totales'],
    [String(total), 'Proyectos'],
    [minigranjas.length+' · '+fmt(mwMini)+' MW', 'Minigranjas/GD (≤1MW)'],
    [mayores.length+' · '+fmt(mwMayor)+' MW', 'Proyectos mayores (>1MW)'],
  ];
  document.getElementById('xmStats').innerHTML = stats.map(([v,l])=>
    '<div class="stat"><b>'+v+'</b><span>'+l+'</span></div>'
  ).join('');
  document.getElementById('xmCount').textContent =
    total.toLocaleString('es-CO')+' proyecto'+(total===1?'':'s');
}

function renderAnalysisXm(){
  renderAnalysisXmStats();
  renderXmBarList('xmTimeline', mwPorMesXm(XM_DATA));
  renderXmBarList('xmZonas', rankBy(XM_DATA, p=>p.ar));
  renderXmBarList('xmPromotores', rankBy(XM_DATA, p=>p.pm));
}
```

Then call it once from `buildAnalysisXmSkeleton()`, at the end (after the filter-listener wiring added in Task 7):

```js
  ['xmFiltroZona','xmFiltroCategoria','xmFiltroDesde','xmFiltroHasta'].forEach(id=>{
    document.getElementById(id).addEventListener('change', ()=>renderAnalysisXmTable());
  });
  renderAnalysisXm();
}
```

(`renderAnalysisXmTable` is added in Task 9; calling it from a listener before it exists is fine — the listener body is not evaluated until the user changes a filter, which only happens after Task 9 ships.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ui_contract.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Manual smoke check**

Reload `http://localhost:8765/index.html` (still with `XM_DATA = []`), open the Análisis tab. Confirm the stat tiles show `0` / `0 proyectos` and the two `insight-list`s show "Sin datos." with no console errors.

- [ ] **Step 6: Commit**

```bash
git add index.html tests/test_ui_contract.py
git commit -m "feat: tarjetas resumen y linea de tiempo de Analisis XM"
```

---

## Task 9: `index.html` — tabla filtrable

**Files:**
- Modify: `index.html`
- Test: `tests/test_ui_contract.py`

**Interfaces:**
- Consumes: `categoriaXm`, `renderAnalysisXm` (Task 8), `wireRowActions`, `escAttr` (existing helpers).
- Produces: `xmTableState`, `xmFilteredRows()`, `renderAnalysisXmTable()`. Extends `renderAnalysisXm()` to call `renderAnalysisXmTable()`.
- Note: `coincidenciaAireXm(p)` (used here for the "air-e" column) is stubbed in this task and fully implemented in Task 10 — see Step 3.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ui_contract.py (agregar al final)
def test_existe_render_analysis_xm_table(html):
    assert "function renderAnalysisXmTable(" in html


def test_xm_filtered_rows_respeta_zona_categoria_y_fechas(html):
    inicio = html.index("function xmFilteredRows(")
    cuerpo = html[inicio : html.index("function renderAnalysisXmTable(")]
    assert "xmTableState.zona" in cuerpo
    assert "xmTableState.categoria" in cuerpo
    assert "xmTableState.desde" in cuerpo
    assert "xmTableState.hasta" in cuerpo


def test_render_analysis_xm_table_maneja_punto_conexion_vacio(html):
    inicio = html.index("function renderAnalysisXmTable(")
    cuerpo = html[inicio : inicio + 1200]
    assert "p.pc||" in cuerpo.replace(" ", "") or "p.pc ||" in cuerpo


def test_render_analysis_xm_table_usa_wire_row_actions(html):
    inicio = html.index("function renderAnalysisXmTable(")
    cuerpo = html[inicio : inicio + 1500]
    assert "wireRowActions(" in cuerpo


def test_render_analysis_xm_llama_a_la_tabla(html):
    inicio = html.index("function renderAnalysisXm(){")
    cuerpo = html[inicio : inicio + 500]
    assert "renderAnalysisXmTable()" in cuerpo
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ui_contract.py -v -k xm_table or xm_filtered_rows`
Expected: FAIL — nada de esto existe todavia.

- [ ] **Step 3: Write the implementation**

Add a temporary stub for `coincidenciaAireXm` (Task 10 replaces this with the real heuristic — added now so this task's table can call it without forward-reference errors):

```js
function coincidenciaAireXm(p){
  return { clase:'sin-match', etiqueta:'Sin match' };
}
```

Add the filter state, filter function, and table renderer right after `renderAnalysisXm()`:

```js
const xmTableState = { zona:'', categoria:'', desde:'', hasta:'' };

function xmFilteredRows(){
  return XM_DATA.filter(p=>{
    if(xmTableState.zona && p.ar !== xmTableState.zona) return false;
    if(xmTableState.categoria === 'gd' && p.mw > 1) return false;
    if(xmTableState.categoria === 'mayor' && p.mw <= 1) return false;
    if(xmTableState.desde && p.fpo < xmTableState.desde) return false;
    if(xmTableState.hasta && p.fpo > xmTableState.hasta) return false;
    return true;
  });
}

function renderAnalysisXmTable(){
  xmTableState.zona = document.getElementById('xmFiltroZona').value;
  xmTableState.categoria = document.getElementById('xmFiltroCategoria').value;
  xmTableState.desde = document.getElementById('xmFiltroDesde').value;
  xmTableState.hasta = document.getElementById('xmFiltroHasta').value;

  const rows = xmFilteredRows();
  const tbody = document.getElementById('xmTableBody');
  if(!rows.length){
    tbody.innerHTML = '<tr><td colspan="9" class="changes-empty">Sin proyectos para este filtro.</td></tr>';
    return;
  }
  const fmtMw = n => n.toLocaleString('es-CO',{maximumFractionDigits:1});
  tbody.innerHTML = rows.map(p=>{
    const match = coincidenciaAireXm(p);
    return '<tr data-code="'+escAttr(p.co)+'">'+
      '<td class="code">'+p.co+'</td>'+
      '<td>'+p.pr+'</td>'+
      '<td>'+fmtMw(p.mw)+'</td>'+
      '<td>'+categoriaXm(p)+'</td>'+
      '<td>'+p.fpo+(p.fpoc?'':' (estimada)')+'</td>'+
      '<td>'+p.ar+' · '+p.sa+'</td>'+
      '<td>'+p.pm+'</td>'+
      '<td>'+(p.pc||'—')+'</td>'+
      '<td><span class="xm-badge '+match.clase+'">'+match.etiqueta+'</span></td>'+
    '</tr>';
  }).join('');
  wireRowActions(tbody);
}
```

Extend `renderAnalysisXm()` (Task 8) to call the table:

```js
function renderAnalysisXm(){
  renderAnalysisXmStats();
  renderXmBarList('xmTimeline', mwPorMesXm(XM_DATA));
  renderXmBarList('xmZonas', rankBy(XM_DATA, p=>p.ar));
  renderXmBarList('xmPromotores', rankBy(XM_DATA, p=>p.pm));
  renderAnalysisXmTable();
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ui_contract.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Manual smoke check**

Reload the local server, open Análisis. Confirm the table shows "Sin proyectos para este filtro." (still empty `XM_DATA`) and no console errors when changing the zona/categoría/fecha filters.

- [ ] **Step 6: Commit**

```bash
git add index.html tests/test_ui_contract.py
git commit -m "feat: tabla filtrable de Analisis XM"
```

---

## Task 10: `index.html` — cruce con air-e

**Files:**
- Modify: `index.html`
- Test: `tests/test_ui_contract.py`

**Interfaces:**
- Consumes: `DATA`, `DEPT_MAP` (existing globals), `XM_DATA` (Task 7).
- Produces (replaces the Task 9 stub): `XM_SUBAREA_DEPTOS`, `normalizarTextoXm(s)`, `lugarDePuntoConexionXm(pc)`, `coincidenciaAireXm(p)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ui_contract.py (agregar al final)
def test_xm_subarea_deptos_solo_cubre_las_tres_subareas_con_overlap(html):
    inicio = html.index("const XM_SUBAREA_DEPTOS")
    cuerpo = html[inicio : html.index("}", inicio) + 1]
    assert "'Atlantico'" in cuerpo or '"Atlantico"' in cuerpo
    assert "'Bolivar'" in cuerpo or '"Bolivar"' in cuerpo
    assert "'GCM'" in cuerpo or '"GCM"' in cuerpo
    # Sin overlap real con DEPT_MAP (air-e no cubre Cordoba/Sucre): no deben
    # tener traduccion, o el cruce los evaluaria contra un universo que no
    # existe en DATA.
    assert "Cordoba_Sucre" not in cuerpo
    assert "Cerromatoso" not in cuerpo


def test_coincidencia_aire_xm_descarta_fuera_de_caribe_sin_evaluar(html):
    inicio = html.index("function coincidenciaAireXm(")
    cuerpo = html[inicio : inicio + 700]
    assert "'Caribe'" in cuerpo or '"Caribe"' in cuerpo
    assert "sin-match" in cuerpo


def test_lugar_de_punto_conexion_xm_maneja_null(html):
    inicio = html.index("function lugarDePuntoConexionXm(")
    cuerpo = html[inicio : inicio + 300]
    assert "if(!pc)" in cuerpo.replace(" ", "") or "if (!pc)" in cuerpo


def test_normalizar_texto_xm_quita_sufijos_legales(html):
    inicio = html.index("function normalizarTextoXm(")
    cuerpo = html[inicio : inicio + 500]
    assert "SAS" in cuerpo
    assert "ESP" in cuerpo


def test_xm_badge_tiene_las_tres_clases_de_confianza(html):
    assert ".xm-badge.alta" in html
    assert ".xm-badge.posible" in html
    assert ".xm-badge.sin-match" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ui_contract.py -v -k xm_subarea or coincidencia_aire or lugar_de_punto or normalizar_texto_xm`
Expected: FAIL — `XM_SUBAREA_DEPTOS`, `normalizarTextoXm`, `lugarDePuntoConexionXm` no existen; `coincidenciaAireXm` sigue siendo el stub de la Tarea 9.

- [ ] **Step 3: Write the implementation**

Replace the Task 9 stub for `coincidenciaAireXm` with the real heuristic, and add its three helpers right before it:

```js
// Solo estas 3 de las 5 subareas del Caribe de XM tienen overlap real con
// DEPT_MAP (air-e solo cubre Atlantico, Bolivar, Cesar, La Guajira,
// Magdalena): Cordoba_Sucre y Cerromatoso quedan fuera a proposito, sin
// entrada aqui, para que el cruce las descarte sin evaluar nada.
const XM_SUBAREA_DEPTOS = {
  'Atlantico': ['Atlántico'],
  'Bolivar': ['Bolívar'],
  'GCM': ['Cesar', 'La Guajira', 'Magdalena'],
};

function normalizarTextoXm(s){
  return String(s||'')
    .toUpperCase()
    .normalize('NFD').replace(/[̀-ͯ]/g,'')
    .replace(/[.,]/g,' ')
    .replace(/\b(SAS|S A S|ESP|E S P|SA|S A|LTDA|BIC)\b/g,' ')
    .replace(/\s+/g,' ')
    .trim();
}

function lugarDePuntoConexionXm(pc){
  if(!pc) return '';
  const sinCircuito = pc.replace(/\bcircuito\b/i,' ');
  const coincidencia = sinCircuito.match(/^[^\d]+/);
  const lugar = (coincidencia ? coincidencia[0] : sinCircuito).replace(/[-,]+$/,'').trim();
  return normalizarTextoXm(lugar);
}

function coincidenciaAireXm(p){
  const deptos = XM_SUBAREA_DEPTOS[p.sa];
  if(p.ar !== 'Caribe' || !deptos){
    return { clase:'sin-match', etiqueta:'Sin match' };
  }
  const promotorNorm = normalizarTextoXm(p.pm);
  const lugarNorm = lugarDePuntoConexionXm(p.pc);
  let promotorCoincideAlgunaVez = false;
  let deptoYlugarCoinciden = false;
  for(const d of DATA){
    const clienteNorm = normalizarTextoXm(d.cl);
    const coincideNombre = !!promotorNorm && !!clienteNorm &&
      (clienteNorm.includes(promotorNorm) || promotorNorm.includes(clienteNorm));
    const deptoDeAire = DEPT_MAP[d.ci];
    const coincideDepto = !!deptoDeAire && deptos.includes(deptoDeAire);
    if(coincideNombre && coincideDepto){
      return { clase:'alta', etiqueta:'Alta confianza' };
    }
    if(coincideNombre) promotorCoincideAlgunaVez = true;
    if(coincideDepto && lugarNorm && d.ci && d.ci.includes(lugarNorm)){
      deptoYlugarCoinciden = true;
    }
  }
  if(promotorCoincideAlgunaVez || deptoYlugarCoinciden){
    return { clase:'posible', etiqueta:'Posible' };
  }
  return { clase:'sin-match', etiqueta:'Sin match' };
}
```

Delete the Task 9 stub (`function coincidenciaAireXm(p){ return { clase:'sin-match', etiqueta:'Sin match' }; }`) — this replaces it, not adds alongside it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ui_contract.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Manual smoke check**

Reload the local server. With `XM_DATA` still `[]` there's nothing to visually check yet for the badges — confirm instead, via the browser console, that `coincidenciaAireXm({ar:'Suroccidental', sa:'Valle', pm:'X', pc:null})` returns `{clase:'sin-match', etiqueta:'Sin match'}` and that calling it with an XM-shaped object with `sa:'Cordoba_Sucre'` also returns `sin-match` without throwing.

- [ ] **Step 6: Commit**

```bash
git add index.html tests/test_ui_contract.py
git commit -m "feat: cruce heuristico XM contra air-e por promotor/departamento/lugar"
```

---

## Task 11: Corrida real, verificación end-to-end y despliegue

**Files:**
- No source changes — this task runs the pipeline built in Tasks 1–10 against the real data and commits the result.

**Interfaces:** none (integration/validation task).

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest`
Expected: PASS — every test from Tasks 1–10 plus the pre-existing suite (125+ tests).

- [ ] **Step 2: Dry-run against the real CSV**

Run (from the repo root, `radar-solar-web/`):

```bash
python -m scripts.build_xm --csv "../XM/Promotores 17 de Septiembre 2026.xlsm - Export.csv" --dry-run
```

Expected output: a report showing **386 proyectos**, **10.027 MW total** (approximately — matches the numbers profiled in the spec), the área breakdown table (Caribe 207, Suroccidental 73, Nordeste 64, Oriental 22, Antioquía-Chocó 20), `sin_punto_conexion: 8`, `fecha_confirmada: 196`, `fecha_estimada: 190`. Read this report before proceeding — if any number is off from the spec's profiling, stop and investigate before writing.

- [ ] **Step 3: Real run**

```bash
python -m scripts.build_xm --csv "../XM/Promotores 17 de Septiembre 2026.xlsm - Export.csv"
```

Expected: writes `data/xm/snapshots/xm-<hoy>.json`, `data/xm/reports/xm-<hoy>.md`, and updates `index.html` with 386 `XM_DATA` records.

- [ ] **Step 4: Re-run the full test suite against the real, populated `index.html`**

Run: `python -m pytest`
Expected: PASS. (`test_ui_contract.py`'s tests read the real `index.html`, not a fixture, so this is the first run that exercises the real 386-row `XM_DATA`.)

- [ ] **Step 5: Manual browser verification**

Start the local server and open the Análisis tab:

```bash
python -m http.server 8765
```

Visit `http://localhost:8765/index.html`, click "Análisis", and confirm:
- The "Análisis XM" block shows the stat tiles with real numbers (≈10.027 MW, 386 proyectos, the minigranja/mayor split).
- The timeline shows bars from 2022 through 2029 with 2027 as the tallest (per the spec's profiling, ≈4.312 MW that year).
- Zona and promotor rankings are populated and scrollable.
- The table shows 386 rows; changing the "Zona" filter to "Caribe" narrows it to 207; changing "Categoría" to "Minigranja/GD" narrows it further.
- At least one row in a Caribe/Atlantico or Caribe/GCM zone shows a non-"Sin match" badge (spot-check a promotor name that also appears as an air-e `cl`, e.g. a Unergy-related XM row against `DATA`).
- No errors in the browser console.

- [ ] **Step 6: Commit the generated data**

```bash
git add index.html data/xm/snapshots data/xm/reports
git commit -m "feat: primera corrida de Analisis XM, 386 proyectos de la exportacion de sept-2026"
```

- [ ] **Step 7: Push and deploy (only after explicit go-ahead)**

This step is intentionally **not** run automatically as part of this plan — pushing to `main` and deploying to Vercel production are the kind of visible, hard-to-reverse actions that need a fresh explicit confirmation from the person running this plan, the same way the air-e refresh pipeline does. Once confirmed:

```bash
git push origin main
vercel --prod --yes
```

Then verify `https://radar-solar-web.vercel.app/` responds 200 and shows the new section.
