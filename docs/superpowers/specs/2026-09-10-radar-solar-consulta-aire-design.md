# Consulta air-e: refresco de datos oficiales y almacenamiento de energía

**Fecha:** 2026-09-10
**Estado:** aprobado, pendiente de plan de implementación

## Problema

Los 1.586 registros del radar solar (`const DATA` en `index.html`) tienen campos
poco fiables. El sheet interno "Solicitudes ECS de A-ire" tampoco es fuente
autoritativa: contiene información errónea. La única fuente veraz es el portal
CREG030 de air-e.

Falta además un dato que hoy no existe en el radar: si la solicitud cuenta con
almacenamiento de energía y con qué capacidad en kWh.

## Fuente de datos

El portal expone un endpoint público, sin autenticación, que devuelve todos los
registros de un rango de fechas en JSON, con las descripciones ya resueltas:

```
POST https://servicios.air-e.com/CREG030/form/WFListadoSolicitud.aspx/ListaSolicitudes
Content-Type: application/json; charset=utf-8

{"Objsolicitud": {"FECHAINI": "2024-10-01", "FECHAFIN": "2024-10-31"}}
```

Devuelve 177 registros para octubre de 2024 (488 KB). El filtro de fechas opera
sobre `FEC_CREA` (fecha de solicitud).

La respuesta llega en Latin-1 y hay que recodificarla a UTF-8.

### Vía descartada

Existe una segunda vía, código por código:
`WFConsulta.aspx/Encryptar` → `form/WFSolicitud.aspx?enc=<token>` →
`form/WFSolicitud.aspx/CargarDatosSolicitud`.

Se descarta por dos razones. Cuesta 3 peticiones por código en vez de 1 por mes.
Y es insegura: si la carga de la página `?enc=` falla, `CargarDatosSolicitud`
devuelve **otra solicitud sin señalar el error**. Verificado en pruebas: al pedir
la 21941 devolvió la 25657. Este es con toda probabilidad el origen del commit
`a2cabc2 Revert spurious estado changes caused by an unreliable air-e session`.

El endpoint masivo no tiene ese problema porque cada registro trae su propio
`CONSECUTIVO`.

## Mapeo de campos

| Campo air-e | Campo BD | Notas |
|---|---|---|
| `CONSECUTIVO` | `c` | Llave. `external_code` del sheet. Se guarda como string, igual que hoy. |
| `FEC_CREA` | `f` | Viene como `/Date(<ms epoch>)/`. Se convierte a **UTC-5** y se formatea `YYYY-MM-DD HH:mm`. |
| `DESC_ESTADO` | `es` | Nombre ya resuelto, no el código numérico. |
| `NOMBRE_CLI` | `cl` | |
| `DESC_CIUDAD_PRO` | `ci` | Ciudad del inmueble, no la del cliente. |
| `DESC_CORREGIMIENTO_PRO` | `co` | |
| `DESC_VEREDA_PRO` | `ve` | |
| `TECNO_UTILIZADA_DESC` | `t` | |
| `TIPO` | `tg` | Tipo de generación. |
| `LATITUD` | `la` | Ubicación georreferenciada wgs84. **Redondear a 5 decimales.** |
| `LONGITUD` | `lo` | Igual. |
| `TIENE_ALMACENAMIENTO` | `al` | **Nuevo.** `1 → true`, `2 → false`, otro → `null`. |
| `CAPACIDAD_ALMACENAMIENTO` | `ak` | **Nuevo.** kWh. |

La codificación `1=Sí / 2=No` de `TIENE_ALMACENAMIENTO` se verificó contra
`ejemplo.pdf` (solicitud 21941: el PDF dice "No", la API devuelve `2`).

### Precisión de coordenadas

air-e devuelve las coordenadas con ruido de punto flotante: para la solicitud
23433 devuelve `-74.156100000000009`, mientras la BD tiene `-74.1561`. Sin
redondear a 5 decimales, el refresco produciría un cambio en casi los 1.586
registros y un diff inútil que además haría imposible ver los cambios reales.
Cinco decimales son ~1 metro de precisión, más que suficiente para el mapa, y
coinciden con lo que la BD ya guarda.

Campos que **no** provienen de air-e y se preservan intactos: `e` (empresa),
`se` (estado sheet), `p` (nombre de proyecto), `un` (bandera Unergy),
`b` (batch de ingreso).

### Por qué `e` y `se` no se pueden recalcular

Están poblados en los 1.586 registros, pero el sheet solo cubre 275 códigos.
La BD contiene empresas que no existen en ese sheet: `OTACC` (469 registros),
`ISRAEL TORRES` (76), `URSAE` (48), `BEEDEV` (28). Derivarlos del sheet
borraría la empresa de 1.316 registros.

Para los 270 códigos que sí están en ambos lados, `se` y `e` coinciden al 100%
con el sheet, así que no hay nada que reconciliar.

## El sheet: estructura real

El sheet "Solicitudes ECS de A-ire" tiene **dos tablas**, no una:

| Tabla | Filas | Columnas |
|---|---|---|
| 1 | 275 | `id, external_code, estado, empresa, project_name, customer_name, type_supply, initial_date, end_date` |
| 2 | 225 | las mismas **más `latitud` y `longitud`** |

La tabla 2 es un subconjunto de los códigos de la tabla 1. Unión: **275 códigos
únicos**, sin repeticiones dentro de cada tabla. Los 225 códigos que aparecen en
ambas coinciden al 100% en `estado`, `empresa` y `project_name`: **cero
conflictos**, así que consolidar por `external_code` es seguro.

Las columnas `latitud`/`longitud` de la tabla 2 **se ignoran deliberadamente**.
Las coordenadas vienen de air-e, que es la fuente veraz.

De los 275 códigos, **272 son numéricos** y 3 no lo son: `C139`, `C153`, `C159`.

### Los 5 códigos del sheet que no están en la BD

| Código | Situación |
|---|---|
| `C139`, `C153`, `C159` | No son números de solicitud. No se pueden consultar en air-e. Tienen `project_name` con la convención interna de Unergy (`COLATLT6P1_LURUACO_SUR`) y `customer_name` con el valor `nan`, artefacto de un export de pandas. Parecen marcadores internos de proyectos sin número de solicitud asignado. |
| `20707`, `20715` | **No existen en air-e.** Verificado por dos vías independientes: `ValidaSolicitud` devuelve `false` (igual que un código inventado como `99999`, mientras que `21941` devuelve `true`), y un barrido de los 12 meses de 2024 no los encuentra. |

Ninguno de los 5 se agrega. Se listan en el reporte para que se revisen a mano.
Esto es coherente con el criterio de fiarse de air-e por encima del sheet: si air-e
no conoce un código, no tenemos datos veraces que poner.

El barrido de 2024 dejó ver además que la secuencia de `CONSECUTIVO` no es densa
(mayo de 2024 salta de `18432` a `21000`), así que la ausencia de `20707`/`20715`
no es un hueco anómalo del listado sino un rango que simplemente no existe.

## Alcance

Decisiones tomadas:

1. **Refrescar los 1.586 registros existentes** con datos oficiales de air-e, no
   solo los 275 del sheet. El endpoint masivo hace que cueste lo mismo.
2. **No incorporar registros nuevos de air-e** en esta iteración. Los 5 códigos
   del sheet que faltan en la BD no son incorporables (ver más abajo), así que el
   total se mantiene en **1.586**.
3. **Agregar almacenamiento** a todos los registros.

La decisión 2 se tomó asumiendo que se agregarían `20707` y `20715`. Al
verificarlos contra air-e resultó que no existen, así que el total previsto pasó
de 1.588 a 1.586. Es un cambio a la baja y sin pérdida de información: los 5
códigos quedan documentados en el reporte.

### Sobre los registros de air-e que faltan en la BD

Los 1.586 son un subconjunto curado de air-e. Todos existen en air-e (0
huérfanos en las muestras), pero air-e tiene bastante más:

| Mes | air-e | BD | No están en la BD |
|---|---|---|---|
| oct-2024 | 177 | 19 | 158 |
| jun-2025 | 269 | 73 | 196 |

La regla original de inclusión no es deducible: no es por tipo, ni por estado, ni
por potencia. En jun-2025 la BD tiene 68 de 78 "GD ≤0.1MVA" y 5 de 43
"AGPE 0.1–1MVA", con excluidos idénticos a los incluidos (mismo estado, misma
potencia de 990 kW). El primer commit del repo es
`e3a8f6d Recover radar-solar-web project from live Vercel deployment`, así que el
script original no existe y esa regla se perdió.

Por eso el diseño **no depende de conocer esa regla**: se refrescan los registros
que ya están y no se agrega ninguno. Como entregable aparte, un reporte con el
conteo real de los faltantes por tipo/estado/mes, para decidirlo después con
datos en la mano.

## Arquitectura

```
air-e CREG030
   POST /form/WFListadoSolicitud.aspx/ListaSolicitudes  {FECHAINI, FECHAFIN}
        │  1 llamada por mes · 2019-03 → 2026-09
        ▼
scripts/fetch_aire.py ──► data/snapshots/aire-2026-09-10.json   (crudo, commiteado)
        │
        ▼
scripts/build_data.py ──► index.html  (const DATA reinyectado)
                     └──► data/reports/cambios-2026-09-10.md
```

Python 3.12, consistente con el proyecto hermano `datos plataforma`.

### `fetch_aire.py`

Única responsabilidad: hablar con air-e y escribir el crudo. No conoce el esquema
del radar.

- Recorre mes a mes desde `2019-03` (fecha de la solicitud más antigua en la BD,
  `2019-03-13`) hasta el mes actual.
- Cachea cada mes en disco, de modo que reintentar tras un fallo no vuelve a
  bajar lo ya obtenido.
- Recodifica Latin-1 → UTF-8.
- Detecta la página HTML de `Runtime Error` de ASP.NET que el servidor devuelve
  en lugar de JSON, reintenta, y si insiste falla.
- Salida: un JSON con los registros crudos, deduplicados por `CONSECUTIVO`, más
  metadatos de la corrida (fecha, rango, conteo por mes).

### `build_data.py`

Función pura `(snapshot, DATA actual, sheet) → (DATA nuevo, reportes)`. Sin red,
por lo que se puede testear completa con fixtures.

El sheet entra solo para generar el reporte de los códigos sin contraparte en
air-e. No alimenta ningún campo del `DATA`: `e`, `se` y `p` se preservan de lo que
ya hay, y el resto viene de air-e.

**Reinyección en `index.html`.** El `DATA` es la línea 395, una sola línea de
480 KB. La sustitución se hace localizando el prefijo `const DATA = [` y el `];`
que lo cierra, reemplazando solo ese tramo y dejando intacto el resto del archivo
—nunca reescribiendo `index.html` completo desde una plantilla, que es la forma
fácil de perder los 950 renglones de UI. Se escribe a un temporal y se reemplaza
de forma atómica. El JSON se serializa con `ensure_ascii=False` y UTF-8, para no
introducir escapes ni romper las tildes.

## Reglas de fusión

Llave: `c` (`external_code`).

- **Registro presente en el snapshot** → se sobrescriben `f, es, cl, ci, co, ve,
  t, tg, la, lo`; se agregan `al` y `ak`; se preservan `e, se, p, un, b`.
- **Registro ausente del snapshot** → se conserva sin cambios y se lista en el
  reporte como "no encontrado en air-e" para revisión manual. No se elimina.
- **No se agregan registros nuevos.** Los 5 códigos del sheet ausentes de la BD
  van al reporte, no al `DATA`.
- **Ningún registro se elimina, nunca.**

El snapshot debe cubrir los 1.586. Si alguno no aparece, es señal de que el
listado por rango de fechas no devuelve todo, y hay que investigarlo antes de
confiar en el resultado — no basta con conservar el registro viejo en silencio.
Por eso va al reporte de forma destacada.

## Guardas

El modo de falla a prevenir es el de `a2cabc2`: escribir datos incorrectos que
parecen plausibles. Las cuatro guardas **abortan sin escribir nada**:

1. **Indexación por identidad propia.** Cada registro del snapshot se indexa por
   su propio `CONSECUTIVO`. Nunca se asume que una respuesta corresponde a lo
   que se pidió.
2. **Conteo.** Si el resultado final tiene menos de 1.586 registros → abortar.
3. **Deriva de estados.** Si más del 25% de los estados cambia en una sola
   corrida → abortar. El movimiento real de estados es gradual; un salto masivo
   indica un pull defectuoso.
4. **Coordenadas.** Si algún registro queda sin `la`/`lo` → abortar. Hoy los
   1.586 tienen coordenadas.

Un fallo en cualquier mes aborta el build completo. No se escribe un `DATA`
parcial.

## Interfaz de usuario

Sobre la estructura que ya existe en `index.html`:

- **Sidebar** — check `Solo con almacenamiento (N)`, en la sección de filtros
  junto a empresa y ciudad, integrado al mismo pipeline de filtrado que alimenta
  el contador de resultados y el mapa.
- **Popup del mapa y ficha** — línea `Almacenamiento: Sí — 250 kWh`, o `No`.
- **Vista Análisis** — tarjeta `Con almacenamiento: N solicitudes · X kWh total`,
  junto a los insights actuales.
- **Footer** — `Actualizado 2026-09-10` (hoy dice `2026-09-01`).

No se agrega columna a la vista Tabla: el almacenamiento aparece en ~2% de las
solicitudes (3 de 177 en oct-2024) y la columna quedaría casi vacía.

## Pruebas

- **Unitarias de `build_data.py`** con fixtures: que preserve `e` y `se`, que no
  pierda registros, que aplique `al` y `ak` correctamente, y que cada guarda
  dispare cuando debe.
- **Registro golden: 21941**, contra `ejemplo.pdf`. Verificado ya campo por
  campo: `2024-10-30 14:32`, `Estudio solicitud`,
  `Green Yellow Energia de Colombia SAS`, `ARACATACA` / `ARACATACA`,
  `10.63491` / `-74.23092`, `Solar FV`, almacenamiento `No`, `0` kWh.
- **Validación de `al`/`ak`**: comprobar contra registros con `al=1` que traigan
  `ak > 0`. Si aparece una incoherencia (`al=1` con `ak=0`), se reporta en vez de
  interpretarla.
- **Post-build**: reabrir `index.html`, reparsear el `DATA`, verificar conteo y
  muestras. Si el archivo no queda parseable, el build falla.
- **Revisión humana del reporte de cambios** antes de commitear y desplegar.

## Entregables

- `scripts/fetch_aire.py`, `scripts/build_data.py` y sus tests
- `data/snapshots/aire-2026-09-10.json`
- `data/reports/cambios-2026-09-10.md`
- `index.html` con 1.586 registros verificados contra air-e y campos de
  almacenamiento
- Reporte del universo air-e no incorporado, por tipo/estado/mes
- Reporte de los 5 códigos del sheet sin contraparte en air-e

## Fuera de alcance

- **Cómo carga la app.** Los datos siguen embebidos en `index.html` como archivo
  único. Sacarlos a `data.json` haría los diffs de git legibles — hoy los 1.586
  registros son una sola línea de 480 KB, de ahí la cadena de commits
  `Backfill` / `Revert` / `Backfill` — pero mezclar un cambio de arquitectura de
  carga con una actualización de datos multiplica el riesgo. Queda como paso
  posterior, pequeño y aislado.
- **Despliegue a Vercel.** Se decide después de revisar el reporte de cambios.
- **Incorporar registros nuevos de air-e.** Decisión aplazada, con el reporte
  como insumo.
