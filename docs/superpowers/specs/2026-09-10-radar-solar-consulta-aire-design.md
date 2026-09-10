# Consulta air-e: refresco de datos oficiales y almacenamiento de energía

**Fecha:** 2026-09-10
**Estado:** aprobado, pendiente de plan de implementación

## Problema

Los 1.586 registros del radar solar (`const DATA` en `index.html`) tienen campos
poco fiables. El sheet interno "Solicitudes ECS de A-ire" tampoco es fuente
autoritativa: contiene información errónea. La única fuente veraz es el portal
CREG030 de air-e.

Falta además un dato que hoy no existe en el radar: si la solicitud cuenta con
almacenamiento de energía y con qué capacidad en kWh. Ese dato tiene que quedar
explotable, no solo almacenado: filtro en el sidebar y una tabla en la vista
Análisis que liste los proyectos con almacenamiento con su fecha, estado,
capacidad y empresa.

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

## Almacenamiento: la medición

Se bajó el histórico completo de air-e una vez para dimensionar la función:
**10.368 solicitudes únicas**, 49 de 49 periodos sin error.

| | Registros | Capacidad |
|---|---|---|
| air-e completo | 10.368 | — |
| Con almacenamiento | 309 (3%) | 44.337 kWh |
| De esos, ya en la BD | **2** | **15 kWh** |

Los dos que ya están son `22742` (10 kWh, C2EFICIENTE, Barranquilla) y `23773`
(5 kWh, GMAIL, Santa Marta): baterías de techo, no proyectos.

El motivo es estructural. De los 309 con almacenamiento, **306 son
`AGPE ≤0.1MVA`**, justo la categoría residencial que el subconjunto curado
excluye. Solo 3 son de escala proyecto, y ninguno estaba en el radar:

| Código | Capacidad | Estado | Cliente | Municipio |
|---|---|---|---|---|
| `25857` | 6.517 kWh | Estudio solicitud | GECELCA | Fonseca |
| `22637` | 6.200 kWh | Revisión documento | GECELCA | Fonseca |
| `26761` | 215 kWh | Estudio solicitud | GreenYellow Solar | Ciénaga |

Esos 3 concentran **12.932 kWh**, cerca del 30% de todo el almacenamiento del
Caribe. Sin ellos, la tabla de análisis nacería con 2 filas de 10 y 5 kWh y la
función sería decorativa.

**Decisión: se agregan esos 3 y solo esos 3.** Los 306 residenciales quedan
documentados en el reporte. Es un crecimiento de +0,2% que no altera el carácter
del mapa ni los rankings de empresas, y mete exactamente lo que el radar quiere
mostrar.

### Codificación verificada a escala

Sobre las 10.368 solicitudes, `TIENE_ALMACENAMIENTO` solo toma los valores `1` y
`2`, y no hay ni un caso de `2` con capacidad mayor que cero. La lectura
`1=Sí / 2=No` queda confirmada más allá del PDF de ejemplo.

Sí existen **3 registros con `1` y capacidad `0`**, la incoherencia que este
diseño anticipaba. Ninguno está en la BD ni entra con esta decisión. Se reportan,
no se interpretan.

## Alcance

Decisiones tomadas:

1. **Refrescar los 1.586 registros existentes** con datos oficiales de air-e, no
   solo los 275 del sheet. El endpoint masivo hace que cueste lo mismo.
2. **Agregar únicamente los 3 registros de escala proyecto con almacenamiento**
   (`25857`, `22637`, `26761`). Total resultante: **1.589**.
3. **Agregar almacenamiento** a todos los registros, con tabla en Análisis y
   filtro en el sidebar.
4. **No incorporar el resto del universo air-e.** Los 5 códigos del sheet que
   faltan no son incorporables, y los 306 residenciales con almacenamiento quedan
   en el reporte.

La decisión 2 cambió dos veces sobre evidencia, y vale registrar por qué. Primero
se planeó agregar `20707` y `20715` del sheet: al verificarlos, no existen en
air-e. Después la medición del almacenamiento mostró que la función nacía vacía
sin los 3 de escala proyecto. Total previsto: 1.588 → 1.586 → 1.589.

### Sobre los registros de air-e que faltan en la BD

Los 1.586 son un subconjunto curado de air-e:

| Mes | air-e | BD | No están en la BD |
|---|---|---|---|
| oct-2024 | 177 | 19 | 158 |
| jun-2025 | 269 | 73 | 196 |

### Los 28 registros de la BD que no existen en air-e

El pull completo reveló que **28 de los 1.586 no aparecen en air-e**. La
extrapolación inicial desde una muestra de un mes daba 0, así que el diseño ya
los contemplaba pero subestimaba el número.

Se conservan sin cambios y se listan en el reporte de forma destacada. No se
eliminan y no se inventan datos para ellos.

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
- **Los 3 registros nuevos** (`25857`, `22637`, `26761`) entran con todos los
  campos de air-e, más los campos propios asignados a mano (ver abajo).
- **Ningún otro registro se agrega.** Los 5 códigos del sheet ausentes de la BD y
  los 306 residenciales con almacenamiento van al reporte, no al `DATA`.
- **Ningún registro se elimina, nunca.**

### Los campos propios de los 3 nuevos

Estos registros no están en el sheet de ECS, así que `e`, `se`, `p` y `un` no
tienen origen. Como son solo 3, se asignan explícitamente en lugar de derivarlos
con una heurística:

| Campo | `25857` | `22637` | `26761` |
|---|---|---|---|
| `e` | `GECELCA` | `GECELCA` | `GREENYELLOW` |
| `se` | vacío | vacío | vacío |
| `p` | vacío | vacío | vacío |
| `un` | `false` | `false` | `false` |
| `b` | `sept10` | `sept10` | `sept10` |

`GREENYELLOW` ya existe como empresa en el sheet, así que el valor es consistente
con lo que la BD ya usa. `GECELCA` es nuevo y aparecerá en el filtro de empresas.

**`se` vacío es un estado nuevo en la BD**: hoy los 1.586 tienen `se` poblado. El
vacío significa «sin seguimiento en el sheet de ECS», que es la verdad para estos
3. La UI debe renderizarlo como `—` en la tabla y en la ficha, no como celda en
blanco, y el filtro de texto de esa columna no debe romperse con el vacío.

## Guardas

El modo de falla a prevenir es el de `a2cabc2`: escribir datos incorrectos que
parecen plausibles. Las cuatro guardas **abortan sin escribir nada**:

1. **Indexación por identidad propia.** Cada registro del snapshot se indexa por
   su propio `CONSECUTIVO`. Nunca se asume que una respuesta corresponde a lo
   que se pidió.
2. **Conteo.** Si el resultado final tiene menos de 1.589 registros → abortar.
3. **Deriva de estados.** Ver abajo: umbral del 5% con excepción explícita para
   la corrida inicial.
4. **Coordenadas.** Si algún registro queda sin `la`/`lo` → abortar. Hoy los
   1.586 tienen coordenadas, y los 3 nuevos las traen de air-e.

Un fallo en cualquier mes aborta el build completo. No se escribe un `DATA`
parcial.

### La deriva de estados y la corrida inicial

El umbral original de este diseño era 25%. Dos problemas, ambos detectados al
revisar:

**Es demasiado laxo para el régimen normal.** El commit `550f264` dice *"Update
estado air-e for 11 solicitudes that advanced"*: 11 de 1.586 es **0,7%**. Contra
ese referente, 25% son unos 397 registros y no atajaría casi ningún pull
defectuoso. El umbral en régimen queda en **5%** — unos 79 registros, siete veces
el mayor movimiento real observado, con margen de sobra y capacidad real de
detección.

**No aplica a la primera corrida.** Esta corrida es precisamente una corrección
de datos que hoy están mal, así que puede mover muchos estados con total
legitimidad, y la guarda abortaría justo cuando debe trabajar. Por eso:

- `build_data.py` acepta `--corrida-inicial`, que **reemplaza el aborto por un
  reporte obligatorio**: la deriva se calcula igual, se detalla estado por estado
  en el reporte de cambios, y el build continúa.
- El flag no tiene efecto silencioso: si se pasa, el reporte lo declara en la
  cabecera, para que quede en el historial por qué esa corrida no fue validada
  contra el umbral.
- De la segunda corrida en adelante se usa el umbral del 5% y el aborto.

La revisión humana del reporte es lo que sustituye a la guarda en la corrida
inicial. Ese es el punto donde se compara la deriva contra lo que sabés que pasó
de verdad en air-e.

## Interfaz de usuario

Sobre la estructura que ya existe en `index.html`.

### Sidebar

Check `Solo con almacenamiento (N)`, en la sección de filtros junto a empresa y
ciudad, integrado al mismo pipeline de filtrado que ya alimenta el contador de
resultados, el mapa y la vista Tabla. El contador `(N)` refleja los registros con
almacenamiento **entre los visibles según los demás filtros**, igual que el resto
de los controles del sidebar, no un total fijo.

### Popup del mapa y ficha

Línea `Almacenamiento: Sí — 6.517 kWh`, o `No`. Con `al = null` (dato ausente o
incoherente en air-e) muestra `Sin dato`, nunca `No`: son cosas distintas y
confundirlas falsea la lectura.

### Vista Análisis

Dos piezas:

**Tarjeta resumen** — `Con almacenamiento: N solicitudes · X kWh total`, junto a
los insights actuales.

**Tabla explícita de los proyectos con almacenamiento**, ordenada por capacidad
descendente:

| Columna | Origen |
|---|---|
| Código | `c` |
| Empresa | `e` |
| Cliente | `cl` |
| Municipio | `ci` |
| Tipo de generación | `tg` |
| Estado air-e | `es` |
| Estado Sheet | `se`, con `—` si está vacío |
| Fecha solicitud | `f` |
| **Capacidad (kWh)** | `ak`, alineada a la derecha con `tabular-nums` |

La tabla respeta los filtros activos del sidebar, de modo que sirve tanto de
inventario completo como de vista filtrada por empresa o municipio. Con los
filtros limpios arranca en **5 filas y 12.947 kWh**. Cuando ningún registro
visible tiene almacenamiento, muestra un mensaje de estado vacío en lugar de una
tabla con encabezados sueltos — el mismo patrón que ya usa
`008dcd0 Show empty-state message when no estado changes are detected`.

Con 5 filas no necesita paginación, pero va dentro de un contenedor con scroll
propio, porque si más adelante se incorporan los 306 residenciales pasaría a 309
filas sin que haya que rehacerla.

### Vista Tabla

No se le agrega columna de almacenamiento: sobre los 1.589 registros el dato
aparece en 5, y la columna quedaría vacía en el 99,7% de las filas. La tabla de
Análisis cubre ese caso de uso mejor.

### Footer

`Actualizado 2026-09-10`; hoy dice `2026-09-01`.

## Pruebas

- **Unitarias de `build_data.py`** con fixtures: que preserve `e` y `se`, que no
  pierda registros, que aplique `al` y `ak` correctamente, que cada guarda
  dispare cuando debe, y que `--corrida-inicial` convierta el aborto por deriva
  en reporte sin saltarse el cálculo.
- **Los 3 registros nuevos**: que entren con los campos propios asignados, que
  `se` vacío se renderice `—`, y que `GECELCA` aparezca en el filtro de empresas.
- **La tabla de Análisis**: que ordene por capacidad descendente, que respete los
  filtros del sidebar, y que muestre el estado vacío cuando ningún registro
  visible tiene almacenamiento.
- **Registro golden: 21941**, contra `ejemplo.pdf`. Verificado ya campo por
  campo: `2024-10-30 14:32`, `Estudio solicitud`,
  `Green Yellow Energia de Colombia SAS`, `ARACATACA` / `ARACATACA`,
  `10.63491` / `-74.23092`, `Solar FV`, almacenamiento `No`, `0` kWh.
- **Validación de `al`/`ak`**: la codificación ya se verificó sobre las 10.368
  solicitudes (solo valores `1` y `2`, ningún `2` con capacidad mayor que cero).
  El test fija ese invariante y comprueba que los 3 casos de `al=1` con `ak=0`
  se reporten en vez de interpretarse.
- **Post-build**: reabrir `index.html`, reparsear el `DATA`, verificar conteo y
  muestras. Si el archivo no queda parseable, el build falla.
- **Revisión humana del reporte de cambios** antes de commitear y desplegar.

## Entregables

- `scripts/fetch_aire.py`, `scripts/build_data.py` y sus tests
- `data/snapshots/aire-2026-09-10.json`
- `data/reports/cambios-2026-09-10.md`
- `index.html` con 1.589 registros verificados contra air-e, campos de
  almacenamiento, filtro en el sidebar y tabla en Análisis
- Reporte del universo air-e no incorporado, por tipo/estado/mes, incluidos los
  306 residenciales con almacenamiento
- Reporte de los 5 códigos del sheet sin contraparte en air-e
- Reporte de los 28 registros de la BD que no existen en air-e

## Fuera de alcance

- **Cómo carga la app.** Los datos siguen embebidos en `index.html` como archivo
  único. Sacarlos a `data.json` haría los diffs de git legibles — hoy los 1.586
  registros son una sola línea de 480 KB, de ahí la cadena de commits
  `Backfill` / `Revert` / `Backfill` — pero mezclar un cambio de arquitectura de
  carga con una actualización de datos multiplica el riesgo. Queda como paso
  posterior, pequeño y aislado.
- **Despliegue a Vercel.** Se decide después de revisar el reporte de cambios.
  El `.vercelignore` mantiene `docs/`, `data/`, `scripts/` y `tests/` fuera del
  deployment: el sitio es estático, así que sin esa exclusión el spec y los
  snapshots crudos quedarían alcanzables por URL pública.
- **El resto del universo air-e.** Se incorporan solo los 3 de escala proyecto
  con almacenamiento. Los 306 residenciales con almacenamiento y los ~1.000-1.500
  de escala proyecto sin almacenamiento quedan aplazados, con el reporte como
  insumo.
