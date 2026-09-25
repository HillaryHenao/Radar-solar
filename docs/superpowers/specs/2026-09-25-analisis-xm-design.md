# Análisis XM: promotores de generación solar registrados en XM

**Fecha:** 2026-09-25
**Estado:** aprobado, pendiente de plan de implementación

## Problema

El radar solar solo conoce las solicitudes CREG030 que ya llegaron a air-e. No
tiene visibilidad de lo que viene: los proyectos de generación solar que ya se
registraron en XM (el operador del mercado eléctrico colombiano) como
promotores, con su capacidad, fecha estimada de entrada en operación y punto de
conexión a la red — antes, muchas veces, de que exista una solicitud en air-e.

Se dispone de una exportación de XM (`XM/Promotores 17 de Septiembre 2026.xlsm
- Export.csv`, 388 filas) con el listado nacional de promotores solares. No
todos caen en la zona de cobertura de air-e (Caribe): hay proyectos en
Suroccidental, Nordeste, Oriental y Antioquía-Chocó. El objetivo es una nueva
sección **"Análisis XM"**, dentro de la vista Análisis existente, que:

1. Separe los proyectos en **minigranjas/GD** (≤1MW) y **proyectos mayores**
   (>1MW).
2. Muestre en qué zonas se ubican y qué promotor tiene cada uno.
3. Arme una línea de tiempo por fecha de puesta en operación, para ver qué
   capacidad entra, cuándo y dónde en los próximos meses.
4. Señale, para los proyectos en zona Caribe, cuáles probablemente ya
   corresponden a una solicitud existente en air-e (`DATA`), usando promotor,
   departamento y punto de conexión como señales — sin necesidad de scraping
   nuevo contra air-e.

## Qué resultó al perfilar el archivo

388 filas totales, de las cuales **2 son basura de la exportación de Excel**
(filas completamente vacías) y **1 es una fila de metadata del filtro
aplicado** (`Código` = `"Filtros aplicados: \nEstado del proyecto_x es En
trámite..."`, con todo lo demás vacío, incluyendo `CEN [MW]`). Ninguna de las
tres tiene un valor numérico en `CEN [MW]`, así que **la regla de filtrado es
"`CEN [MW]` parsea como número"**, no "`Código` no está vacío" — ese segundo
criterio deja pasar la fila de metadata.

Quedan **386 filas válidas**.

| | |
|---|---|
| Capacidad total (`CEN [MW]`) | 10.027 MW |
| Minigranjas/GD (≤1MW) | 183 proyectos, 165,7 MW |
| Proyectos mayores (>1MW) | 203 proyectos, 9.861,3 MW |
| Promotores distintos | 208 |
| Puntos de conexión distintos | 269 (8 filas sin dato) |
| Con obligación firme (`OEF = SI`) | 35 |

### Área y subárea operativa

`Área operativa` es la zona (5 valores). `Subárea operativa` **no es el
departamento** — es una zonificación propia de XM que a veces junta varios
departamentos:

| Área operativa | Filas | Subáreas operativas |
|---|---|---|
| Caribe | 207 | `Atlantico`, `Bolivar`, `Cerromatoso`, `Cordoba_Sucre`, `GCM` |
| Suroccidental | 73 | `Valle`, `CQR`, `Caqueta`, `Cauca-Narino`, `Huila-Tolima` |
| Nordeste | 64 | `Norte de Santander`, `Boyaca-Casanare`, `Santander`, `Arauca` |
| Oriental | 22 | `Bogota`, `Meta` |
| Antioquía - Chocó | 20 | `Antioquia` |

Verificado contra los puntos de conexión de cada subárea: `GCM` es
Guajira-Cesar-Magdalena (ej. Valledupar, Copey, Codazzi, Cuestecitas, La
Jagua), no una sigla arbitraria.

`DEPT_MAP` en `index.html` (el mapeo municipio→departamento que ya usa el
radar) solo cubre **5 departamentos: Atlántico, Bolívar, Cesar, La Guajira,
Magdalena** — la huella real de air-e. Eso fija qué subáreas de XM son
candidatas al cruce:

| Subárea XM | Departamento(s) | ¿Candidata a cruce con air-e? |
|---|---|---|
| `Atlantico` | Atlántico | Sí |
| `Bolivar` | Bolívar | Sí |
| `GCM` | Cesar, La Guajira, Magdalena | Sí |
| `Cordoba_Sucre` | Córdoba, Sucre | No — air-e no cubre esos departamentos |
| `Cerromatoso` | Córdoba | No |

Los proyectos en `Cordoba_Sucre` y `Cerromatoso`, y los de fuera de la zona
Caribe, se muestran igual en la sección (son parte del análisis nacional) pero
**nunca entran al cruce**: no hay universo de air-e contra el cual compararlos.

### Las dos columnas de fecha no cubren lo mismo

`Fecha de Puesta en Operación Oficial` (estructurada, `MM/DD/YYYY`) solo está
poblada en **196 de 386** filas. Las otras **190 no la tienen — y son
justamente las más chicas**: promedian 2,6 MW contra 48,6 MW de las que sí la
tienen, y solo 1 de esas 190 tiene obligación firme (contra 34 de las 196). En
la práctica, "Oficial" es la fecha que XM confirma para proyectos grandes o
con OEF firme; el resto —la mayoría de las minigranjas— solo tiene la
estimación del promotor en el campo `FPO` (texto libre, ej. *"lunes, junio 01,
2026"*).

`FPO` sí está poblado en el 100% de las 386 filas y parsea sin excepciones con
el patrón `<día semana>, <mes>, <día>, <año>` en español.

**Regla de fecha:** usar `Fecha de Puesta en Operación Oficial` cuando existe;
si no, usar `FPO` parseado. Cada registro guarda además si la fecha es
`confirmada` (vino de Oficial) o `estimada` (vino de FPO texto), para que la
UI pueda distinguirlas — perder la mitad de las minigranjas de la línea de
tiempo no es aceptable para lo que se pidió.

## Esquema de datos: `XM_DATA`

Mismo estilo de claves cortas que `DATA`. Un elemento por proyecto:

| Clave | Origen | Notas |
|---|---|---|
| `co` | `Código` | Ej. `"PROG00107"`. Llave. |
| `pr` | `Proyecto` | Nombre del proyecto. |
| `mw` | `CEN [MW]` | Float. |
| `fpo` | `Fecha de Puesta en Operación Oficial` o `FPO` | `YYYY-MM-DD`. Ver regla de fecha arriba. |
| `fpoc` | — | `true` si `fpo` vino de la fecha Oficial (confirmada), `false` si vino del texto libre (estimada). |
| `ar` | `Área operativa` | |
| `sa` | `Subárea operativa` | Tal cual la da XM (`GCM`, `Cordoba_Sucre`, etc.), sin traducir a departamento — la traducción vive en la heurística de cruce, no en el dato. |
| `pm` | `Promotor` | |
| `pc` | `Puntos de Conexión` | `null` si vacío (8 filas). |
| `oef` | `OEF` | Booleano, `SI`→`true`. |

La categoría (minigranja/GD ≤1MW vs proyecto mayor >1MW) **no se guarda**: se
calcula en JS como `mw <= 1`, igual de barato que leerla y sin riesgo de que
quede desincronizada del valor real de `mw`.

## Cruce con air-e

Se calcula **en el navegador**, leyendo `DATA` y `XM_DATA` ya embebidos en
`index.html`, no en el pipeline Python. Motivo: `DATA` se refresca con
frecuencia semanal-ish desde air-e; `XM_DATA` se refresca cuando llega una
nueva exportación de XM, en un ciclo independiente. Si el cruce se horneara en
el momento de construir `XM_DATA`, quedaría desactualizado apenas `DATA`
avance sin que nadie vuelva a correr el pipeline de XM. Calculándolo en
render, siempre lee la versión más reciente de ambos lados.

**Alcance del cruce:** solo proyectos XM con `ar = "Caribe"` y `sa` en
`{Atlantico, Bolivar, GCM}` (ver tabla arriba). El resto se marca
`sin match` sin evaluar nada — no hay universo de air-e con el que comparar.

**Señales, en este orden:**

1. **Promotor.** Normalizar `pm` (XM) y `cl` (air-e): mayúsculas, sin tildes,
   sin puntuación, sin sufijos legales (`S.A.S`, `S.A`, `E.S.P`, `LTDA`, `SAS
   BIC`, `ESP`, etc.). Coincide si son iguales o si uno contiene al otro tras
   normalizar.
2. **Departamento.** `sa` de XM traducido con la tabla fija de arriba
   (`GCM`→{Cesar, La Guajira, Magdalena}, etc.) contra `DEPT_MAP[ci]` de air-e.
3. **Municipio en el punto de conexión.** Se extrae el nombre de lugar de `pc`
   (la porción de texto antes de "kV", "Circuito", dígitos) y se compara,
   normalizado, contra `ci` de air-e como substring.

**Confianza resultante:**

- **Alta** — promotor coincide y departamento coincide.
- **Posible** — promotor coincide sin coincidencia de departamento, o
  departamento coincide y el municipio del punto de conexión aparece en `ci`.
- **Sin match** — ninguna señal, o proyecto fuera del alcance del cruce.

El resultado es una anotación visual (badge) sobre el proyecto de XM. **Nunca
escribe ni modifica `DATA`.**

## Arquitectura del pipeline

Mismo patrón que air-e, sin la capa de red ni las reglas de fusión (XM no
tiene una "base curada" que preservar — cada corrida reemplaza `XM_DATA`
entero):

```
XM/Promotores <fecha>.xlsm - Export.csv   (exportación manual, fuera del repo)
        │
        ▼
scripts/xm_transform.py   funciones puras: filtrar filas basura, parsear
                           fecha (Oficial → fallback FPO texto), categorizar,
                           normalizar nombre de promotor
        │
        ▼
scripts/build_xm.py  ──►  data/xm/snapshots/xm-<fecha>.json  (proyección slim)
                     ──►  index.html (const XM_DATA = [...])
                     ──►  data/xm/reports/xm-<fecha>.md  (resumen: conteos por
                          categoría/zona, filas sin punto de conexión, filas
                          con fecha estimada vs confirmada)
        │
scripts/inject.py    generalizado para aceptar el nombre de la constante
                      (hoy hardcodeado a "const DATA = ["), reutilizado para
                      empalmar tanto DATA como XM_DATA
```

`build_xm.py` acepta `--csv <ruta>` y `--dry-run` (igual que `build_data.py`):
el dry-run muestra el resumen sin escribir. Como no hay guardas de fusión que
puedan abortar (no hay estado previo con el que comparar más allá del propio
conteo de filas), el único chequeo automático es que el conteo de filas
válidas no caiga a 0 — el resto es revisión humana del reporte, igual que con
air-e.

`.vercelignore` ya excluye `data/` completo, así que `data/xm/` no necesita
una entrada nueva.

## Interfaz de usuario

Nueva sección fija dentro de la vista Análisis (`analysisScroll`), **antes**
de los bloques por año de air-e — no depende de los filtros de año/mes del
sidebar, que son conceptos de air-e (`f`), no de XM (`fpo`).

```html
<section class="analysis-batch analysis-xm">
  <h2 class="analysis-batch-title">Análisis XM</h2>
  ...
</section>
```

1. **Tarjetas resumen:** MW total, # minigranjas/GD y su MW, # proyectos
   mayores y su MW.
2. **Línea de tiempo:** barras por mes (patrón `insight-bar` reutilizado) de
   MW entrando en operación según `fpo`, con los próximos 12 meses
   destacados. Cada barra distingue visualmente MW de fecha confirmada vs
   estimada (`fpoc`).
3. **Desglose por zona y por promotor:** dos `insight-list` rankeadas
   (componente ya existente, `renderInsightList`), clicables para abrir el
   detalle de esos proyectos — mismo patrón que el modal de rango que ya usa
   Análisis.
4. **Tabla filtrable:** código, proyecto, MW, categoría, fecha (con indicador
   confirmada/estimada), área/subárea, promotor, punto de conexión, badge de
   coincidencia air-e. Filtros por zona, categoría y rango de fecha.

## Pruebas

- **`xm_transform.py`**: filtrado de las 3 filas basura (2 vacías + 1 de
  metadata de filtro); regla de fecha (Oficial presente, Oficial ausente con
  fallback a FPO texto, parseo de las variantes de mes en español);
  categorización en el límite exacto de 1MW; normalización de nombre de
  promotor (sufijos legales, tildes, mayúsculas).
- **Golden rows**: al menos un proyecto con fecha Oficial (`PROG00107`) y uno
  sin ella que dependa del fallback (`PROG05157`).
- **`inject.py` generalizado**: que siga reemplazando solo el tramo de `DATA`
  sin tocar `XM_DATA` y viceversa; que falle si no encuentra el prefijo pedido.
- **Cruce (JS)**: casos manuales para cada nivel de confianza (alta, posible,
  sin match) y para los dos motivos de exclusión automática (subárea sin
  cobertura air-e, área fuera de Caribe).
- **UI**: extensión de `test_ui_contract.py` para verificar que `XM_DATA` se
  inyecta como JSON válido y que el HTML resultante sigue siendo parseable.

## Entregables

- `scripts/xm_transform.py`, `scripts/build_xm.py`, y sus tests
- `scripts/inject.py` generalizado (parámetro de nombre de constante) + su
  test actualizado
- `data/xm/snapshots/xm-2026-09-25.json`, `data/xm/reports/xm-2026-09-25.md`
- `index.html` con `const XM_DATA = [...]` (386 registros) y la sección
  "Análisis XM" (tarjetas, línea de tiempo, desglose, tabla, cruce con air-e)

## Fuera de alcance

- **Scraping nuevo contra air-e** para traer el punto de conexión real por
  solicitud (el "documento emergente" que aparece al consultar manualmente).
  El cruce de esta primera versión usa solo promotor + departamento + nombre
  de lugar en el punto de conexión de XM, sin tocar el pipeline de air-e.
  Queda como posible fase 2 si la señal actual no resulta suficiente.
- **Geocodificación de subestaciones.** No se ubican coordenadas reales para
  los 269 puntos de conexión de XM; el cruce usa nombres, no distancia.
- **Refresco automático del CSV de XM.** Sigue siendo una exportación manual
  del archivo `.xlsm`; `build_xm.py` la toma como entrada, no la descarga.
