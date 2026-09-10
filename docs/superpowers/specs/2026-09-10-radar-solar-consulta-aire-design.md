# Consulta air-e: validación de datos y almacenamiento de energía

**Fecha:** 2026-09-10
**Estado:** aprobado, pendiente de plan de implementación

## Problema

El radar solar tiene 1.586 registros embebidos como `const DATA` en `index.html`.
El sheet interno "Solicitudes ECS de A-ire" no es fuente autoritativa: contiene
información errónea. La única fuente veraz es el portal CREG030 de air-e, y hasta
ahora no había forma reproducible de contrastar la BD contra él.

Falta además un dato que no existe en el radar: si la solicitud cuenta con
almacenamiento de energía y con qué capacidad en kWh. Ese dato tiene que quedar
explotable, no solo almacenado: filtro en el sidebar y una tabla en la vista
Análisis con fecha, estado, capacidad y empresa.

## Qué resultó al medir

Se bajó el histórico completo de air-e y se comparó campo por campo contra los
1.586. **Los datos del radar ya coinciden con air-e:**

| Campo | Registros que cambian |
|---|---|
| Sin contraparte en air-e | 0 |
| Estado | 0 |
| Cliente | 0 |
| Ciudad / Corregimiento | 0 |
| Fecha de solicitud | 0 |
| Tecnología / Tipo de generación | 0 |
| Coordenadas | 0 |
| Vereda | **1** |

El único cambio es cosmético: el código `23465` tiene `VDA  CHARCO LATA` con
espacio doble y queda `VDA CHARCO LATA`.

Esto **reencuadra el trabajo**. No es una corrección de datos sucios, es una
validación: el entregable de valor es el pipeline reproducible que permite
repetir esta comparación cuando se quiera, más los campos de almacenamiento y su
UI. La primera corrida certifica que los 1.586 están bien hoy.

Conviene registrar por qué el diagnóstico inicial decía lo contrario. Las
mediciones preliminares reportaron 76 cambios de estado, 107 de cliente, 1.558 de
fecha y 28 registros ausentes. **Los cuatro números eran defectos de la
extracción, no de la BD**: una recodificación de encoding equivocada, una ventana
de fechas mal cerrada y falta de normalización de espacios. Las tres causas están
resueltas abajo, cada una con la regla que la evita.

## Fuente de datos

El portal expone un endpoint público, sin autenticación, que devuelve todos los
registros de un rango de fechas en JSON con las descripciones ya resueltas:

```
POST https://servicios.air-e.com/CREG030/form/WFListadoSolicitud.aspx/ListaSolicitudes
Content-Type: application/json; charset=utf-8

{"Objsolicitud": {"FECHAINI": "2024-10-01", "FECHAFIN": "2024-11-01"}}
```

Universo completo: **10.640 solicitudes únicas** en 93 ventanas mensuales
(2019-01 a 2026-09), sin un solo error de red.

### La ventana de fechas es semiabierta

**`FECHAFIN` es exclusivo y se interpreta a las 00:00 de ese día.** Cerrar la
ventana en el último día del mes descarta todo lo creado después de medianoche de
ese día. Con ventanas `[primer día del mes, último día del mes]` se perdían 111
registros solo en 2025, y 272 en todo el histórico — precisamente los "28
registros que no existen en air-e" del diagnóstico inicial, todos con fecha del
último día de algún mes.

La ventana correcta es **`[primer día del mes, primer día del mes siguiente)`**.
Verificado: el código `22810` (creado `2025-01-31 17:37`) no aparece con
`FECHAFIN=2025-01-31` y sí con `FECHAFIN=2025-02-01`.

### El encoding es UTF-8

El servidor responde `Content-Type: application/json; charset=utf-8` y los bytes
lo confirman: `Revisión` llega como `52 65 76 69 73 69 C3 B3 6E`, que es UTF-8
bien formado.

**Los bytes se decodifican como UTF-8, directo.** Aplicar una recodificación
Latin-1 → UTF-8 corrompe cada carácter acentuado, y fue lo que produjo los 76
"cambios de estado" fantasma del diagnóstico inicial: `Revisión documento`
contra sí mismo, mangleado. El cliente HTTP debe leer bytes y decodificarlos
explícitamente, nunca confiar en la deducción de encoding de la librería.

### Vía descartada

Existe una segunda ruta, código por código:
`WFConsulta.aspx/Encryptar` → `form/WFSolicitud.aspx?enc=<token>` →
`form/WFSolicitud.aspx/CargarDatosSolicitud`.

Se descarta por dos razones. Cuesta 3 peticiones por código en vez de 1 por mes.
Y es insegura: si la carga de la página `?enc=` falla, `CargarDatosSolicitud`
devuelve **otra solicitud sin señalar el error**. Verificado: al pedir la `21941`
devolvió la `25657`. Este es con toda probabilidad el origen del commit
`a2cabc2 Revert spurious estado changes caused by an unreliable air-e session`.

El endpoint masivo no tiene ese problema porque cada registro trae su propio
`CONSECUTIVO`.

## Mapeo de campos

| Campo air-e | Campo BD | Notas |
|---|---|---|
| `CONSECUTIVO` | `c` | Llave. `external_code` del sheet. String, como hoy. |
| `FEC_CREA` | `f` | `/Date(<ms epoch>)/` → **UTC-5** → `YYYY-MM-DD HH:mm`. |
| `DESC_ESTADO` | `es` | Nombre ya resuelto, no el código numérico. |
| `NOMBRE_CLI` | `cl` | |
| `DESC_CIUDAD_PRO` | `ci` | Ciudad del inmueble, no la del cliente. |
| `DESC_CORREGIMIENTO_PRO` | `co` | |
| `DESC_VEREDA_PRO` | `ve` | |
| `TECNO_UTILIZADA_DESC` | `t` | |
| `TIPO` | `tg` | Tipo de generación. |
| `LATITUD` | `la` | wgs84. **Redondear a 5 decimales.** |
| `LONGITUD` | `lo` | Igual. |
| `TIENE_ALMACENAMIENTO` | `al` | **Nuevo.** `1 → true`, `2 → false`, otro → `null`. |
| `CAPACIDAD_ALMACENAMIENTO` | `ak` | **Nuevo.** kWh. |

Campos que **no** provienen de air-e y se preservan intactos: `e` (empresa),
`se` (estado sheet), `p` (nombre de proyecto), `un` (bandera Unergy),
`b` (batch de ingreso).

### Normalización de espacios

**Todo campo de texto se normaliza: colapsar cualquier secuencia de espacios en
blanco a un solo espacio, y recortar los extremos.**

air-e devuelve texto con relleno y tabuladores:
`'                              UNIVERSIDAD          DEL NORTE           '`,
`'LICA ENERGÍA RENOVABLE S.A.S\t\t\t\t\t'`, `'GD El Tamarindo '`. La BD los tiene
limpios, así que el pipeline original ya normalizaba, aunque el diseño inicial no
lo registró. Sin esta regla el refresco ensuciaría **107 nombres de cliente**,
rompiendo el layout de la tabla y la búsqueda por texto.

Es también la regla que produce el único cambio real de esta corrida, el espacio
doble del `23465`.

### Precisión de coordenadas

air-e devuelve ruido de punto flotante: para la solicitud `23433` devuelve
`-74.156100000000009`, mientras la BD tiene `-74.1561`. Redondear a 5 decimales
—cerca de un metro, y lo que la BD ya guarda— da **0 cambios de coordenadas**
sobre los 1.586. Sin redondear, el diff tocaría casi todos los registros y
enterraría los cambios reales.

### Por qué `e` y `se` no se pueden recalcular

Están poblados en los 1.586 registros, pero el sheet solo cubre 275 códigos. La
BD contiene empresas que no existen en ese sheet: `OTACC` (469 registros),
`ISRAEL TORRES` (76), `URSAE` (48), `BEEDEV` (28). Derivarlos del sheet borraría
la empresa de 1.316 registros.

Para los 270 códigos que sí están en ambos lados, `se` y `e` coinciden al 100%
con el sheet, así que no hay nada que reconciliar.

## El sheet: estructura real

El sheet tiene **dos tablas, no una**:

| Tabla | Filas | Columnas |
|---|---|---|
| 1 | 275 | `id, external_code, estado, empresa, project_name, customer_name, type_supply, initial_date, end_date` |
| 2 | 225 | las mismas **más `latitud` y `longitud`** |

La tabla 2 es un subconjunto de los códigos de la tabla 1. Unión: **275 códigos
únicos**. Los 225 que aparecen en ambas coinciden al 100% en `estado`, `empresa`
y `project_name`: cero conflictos, así que consolidar por `external_code` es
seguro.

Las columnas `latitud`/`longitud` de la tabla 2 **se ignoran deliberadamente**:
las coordenadas vienen de air-e. De los 275 códigos, 272 son numéricos y 3 no lo
son.

### Los 5 códigos del sheet que no están en la BD

| Código | Situación |
|---|---|
| `C139`, `C153`, `C159` | No son números de solicitud, no se pueden consultar en air-e. Tienen `project_name` con la convención interna de Unergy (`COLATLT6P1_LURUACO_SUR`) y `customer_name` con el valor `nan`, artefacto de un export de pandas. Parecen marcadores internos de proyectos sin número asignado. |
| `20707`, `20715` | **No existen en air-e.** Verificado por dos vías: `ValidaSolicitud` devuelve `false`, igual que un código inventado como `99999` mientras `21941` devuelve `true`; y no aparecen en el pull completo de 10.640 registros. |

Ninguno se agrega. Se listan en el reporte. Es coherente con fiarse de air-e por
encima del sheet: si air-e no conoce un código, no hay datos veraces que poner.

## Almacenamiento

| | Registros | Capacidad |
|---|---|---|
| Universo air-e | 10.640 | — |
| Con almacenamiento | 316 (3%) | 44.436 kWh |
| De esos, ya en la BD | **2** | **15 kWh** |

Los dos que ya están son `22742` (10 kWh, Barranquilla) y `23773` (5 kWh, Santa
Marta), ambos `AGPE ≤0.1MVA`: baterías de techo, no proyectos.

El motivo es estructural: **312 de los 316 son `AGPE ≤0.1MVA`**, la categoría
residencial que el subconjunto curado excluye. Sin registros nuevos, la tabla de
Análisis nacería con 2 filas de 10 y 5 kWh y la función sería decorativa.

### Regla de inclusión

**Se incorporan los registros con `al = true` y `tg` que empieza por `GD` o por
`AG ` (con el espacio final).** air-e tiene cuatro valores de `tg`: `GD`, `AGPE`
(dos variantes por potencia) y `AG` — este ultimo es la clase de mayor
capacidad y, como `GD`, es escala de red/planta, a diferencia de `AGPE`
(autogeneracion a pequena escala, tipicamente techo residencial o comercial).
El espacio en `"AG "` es deliberado: sin el, el prefijo tambien haria match
con `AGPE`, justo la clase que se debe excluir.

Aplicada al universo completo da exactamente 3, ninguno presente en la BD:

| Código | Capacidad | Potencia AC | Estado | Cliente | Municipio |
|---|---|---|---|---|---|
| `25857` | 6.517 kWh | 900 kW | Estudio solicitud | GECELCA | Fonseca |
| `22637` | 6.200 kWh | 1.000 kW | Revisión documento | GECELCA | Fonseca |
| `26761` | 215 kWh | 990 kW | Estudio solicitud | GreenYellow Solar | Ciénaga |

Concentran **12.932 kWh**, cerca del 30% de todo el almacenamiento del Caribe.

La categoría `AG menor igual 5MVA y mayor 1MVA` tiene 105 registros en el
universo air-e y ninguno con almacenamiento hoy, así que incluirla en la regla
no cambia el resultado de esta corrida: sigue dando exactamente las mismas 3
altas. Es autocuidado hacia adelante, no una corrección de esta medición.

La regla se evalúa en cada corrida, no es una lista fija: si air-e registra un
nuevo proyecto GD o AG con almacenamiento, entra solo, y el reporte lo declara
como alta. Eso mantiene el radar al día en lo que motiva esta función.

**Caso de frontera documentado:** `21489` tiene `al = true` y
`tg = AGPE menor igual 1MVA y mayor 0.1MVA`, con 5 kWh y 10 kW AC a nombre de una
persona en Riohacha. No es un proyecto, y por eso la regla se ancla en `GD` y no
en «cualquier cosa que no sea AGPE ≤0.1MVA». Se reporta como candidato excluido,
para poder incorporarlo con un cambio de una línea si se decide otra cosa.

### Codificación verificada a escala

Sobre las 10.640 solicitudes, `TIENE_ALMACENAMIENTO` solo toma los valores `1` y
`2`, y no hay ni un caso de `2` con capacidad mayor que cero. La lectura
`1=Sí / 2=No` queda confirmada más allá del PDF de ejemplo.

Existen **3 registros con `1` y capacidad `0`** (`362`, `1101`, `15908`), la
incoherencia que este diseño anticipaba. Ninguno está en la BD ni entra con la
regla. Se reportan, no se interpretan.

## Alcance

1. **Validar y refrescar los 1.586 registros** contra air-e. Cambio esperado: 1
   vereda.
2. **Agregar los 3 registros GD con almacenamiento.** Total: **1.589**.
3. **Agregar `al` y `ak`** a todos los registros, con filtro en el sidebar y
   tabla en Análisis.
4. **Arreglar `DEPT_MAP`** para `EL PI¿ON` (ver abajo).
5. **No incorporar el resto del universo air-e.** Los 5 códigos del sheet, los
   312 residenciales con almacenamiento y el caso `21489` quedan en el reporte.

### El municipio que rompe la clasificación por departamento

`DEPT_MAP` tiene 56 entradas y **le falta `EL PI¿ON`**, así que 6 registros de la
BD aparecen hoy como «Sin clasificar» en la vista Análisis.

El nombre real es **El Piñón** (Magdalena), y air-e lo tiene corrupto en origen:
los bytes son `45 4C 20 50 49 C2 BF 4F 4E`, donde `C2 BF` es `¿` (U+00BF), no
`Ñ`. Tanto `index.html` como air-e traen exactamente los mismos bytes, así que el
refresco no lo cambia y **la clave de `DEPT_MAP` debe usar la forma corrupta**
para que el lookup funcione.

Se agregan también las entradas de los municipios del Magdalena que hoy faltan y
aparecen en el universo air-e, para que futuras incorporaciones no caigan en
«Sin clasificar»: `SABANAS DE SAN ANGEL`, `ZAPAYAN`, `ARIGUANI`, `PEDRAZA`,
`PUEBLO VIEJO`.

### Sobre el resto del universo air-e

Los 1.586 son un subconjunto curado. La regla original de inclusión no es
deducible: no es por tipo, ni por estado, ni por potencia. En jun-2025 la BD
tiene 68 de 78 «GD ≤0.1MVA» y 5 de 43 «AGPE 0.1–1MVA», con excluidos idénticos a
los incluidos. El primer commit del repo es `e3a8f6d Recover radar-solar-web
project from live Vercel deployment`, así que el script original no existe y esa
regla se perdió.

El diseño **no depende de conocer esa regla**: se validan los que ya están y solo
entran los que cumplen la regla explícita de almacenamiento. Como entregable
aparte, un reporte con el conteo de los faltantes por tipo, estado y mes.

## Arquitectura

```
air-e CREG030
   POST /form/WFListadoSolicitud.aspx/ListaSolicitudes  {FECHAINI, FECHAFIN}
        │  93 ventanas mensuales semiabiertas · 2019-01 → 2026-10
        ▼
scripts/aire_client.py      capa de red: bytes → UTF-8, reintentos
        ▼
scripts/fetch_aire.py  ──►  data/snapshots/aire-2026-09-10.json
        │                   (proyección slim, ordenada por código, 2,6 MB)
        ▼
scripts/transform.py        air-e → esquema del radar (fechas, espacios, redondeo)
scripts/merge.py            reglas de fusión, guardas, reportes
scripts/inject.py           empalme del const DATA en index.html
        ▼
scripts/build_data.py  ──►  index.html
                       └──►  data/reports/cambios-2026-09-10.md
```

Python 3.12, solo biblioteca estándar (`urllib.request`, `json`). `pytest` como
única dependencia de desarrollo.

### Por qué el snapshot es una proyección slim

El registro crudo de air-e tiene 95 campos, casi todos irrelevantes para el radar
(12 meses de proyección de energía, datos del generador, anexos). En crudo el
histórico pesa 27,5 MB; proyectado a los 14 campos que se consumen, 2,6 MB.

El snapshot guarda esa proyección, ordenada por `CONSECUTIVO`, para que quede
commiteable y **diffeable entre corridas**: comparar dos snapshots muestra qué
movió air-e, sin ruido.

## Reglas de fusión

Llave: `c` (`external_code`).

- **Registro presente en el snapshot** → se sobrescriben `f, es, cl, ci, co, ve,
  t, tg, la, lo`; se agregan `al` y `ak`; se preservan `e, se, p, un, b`.
- **Registro ausente del snapshot** → se conserva sin cambios y se reporta de
  forma destacada. No se elimina. Con la ventana corregida esto debe dar 0; si da
  más, hay un problema en la extracción y hay que investigarlo antes de confiar
  en el resultado.
- **Altas por la regla de almacenamiento** → `al = true` y `tg` que empieza por
  `GD`, con los campos propios asignados abajo.
- **Ningún registro se elimina, nunca.**

### Los campos propios de las altas

Estos registros no están en el sheet de ECS, así que `e`, `se`, `p` y `un` no
tienen origen en air-e:

| Campo | Valor | Por qué |
|---|---|---|
| `e` | Empresa asignada a mano | Son pocos y `e` alimenta filtro y rankings; una heurística sobre `NOMBRE_CLI` produciría basura. |
| `se` | vacío | No tienen seguimiento en el sheet de ECS. |
| `p` | vacío | Sin nombre de proyecto interno. |
| `un` | `false` | No son de Unergy. |
| `b` | `sept10` | Batch de esta corrida. |

Para las 3 altas de esta corrida: `GECELCA` para `25857` y `22637`,
`GREENYELLOW` para `26761`. `GREENYELLOW` ya existe como empresa en la BD;
`GECELCA` es nuevo y aparecerá en el filtro de empresas.

Si una corrida futura da un alta por la regla y no hay empresa asignada para ese
código, **el build falla y pide la asignación**. No inventa el valor ni lo deja
vacío.

**`se` vacío es un estado nuevo en la BD**: hoy los 1.586 lo tienen poblado. El
vacío significa «sin seguimiento en el sheet de ECS». La UI debe renderizarlo como
`—` en la tabla y en la ficha, y el filtro de texto de esa columna no debe
romperse con el vacío.

## Guardas

El modo de falla a prevenir es el de `a2cabc2`: escribir datos incorrectos que
parecen plausibles. Todas **abortan sin escribir nada**. Son **10 en total**,
no 7 como decía una versión anterior de este spec: dos viven en la capa de red
(`aire_client.py` / `fetch_aire.py`), siete son los caminos de abort de
`_valida_guardas` en `scripts/merge.py`, y una más, separada, vive en
`fusionar` mismo.

### En la capa de red

1. **Identidad propia.** Cada registro del snapshot se indexa por su propio
   `CONSECUTIVO`. Nunca se asume que una respuesta corresponde a lo que se pidió.
2. **Cobertura de red.** Si alguna de las 93 ventanas falla tras sus
   reintentos, `fetch_aire` aborta con el error de air-e y aclara que el
   comando es idempotente. No se construye con un snapshot parcial.

### En `_valida_guardas` (`scripts/merge.py`)

3. **Conteo.** Si el resultado tiene menos de 1.589 registros, aborta.
4. **No eliminación.** Ningún registro puede desaparecer entre `actuales` y la
   salida fusionada, sin importar cuánto crezca `DATA` más allá de 1.589 (el
   piso estático de la guarda de conteo se queda corto si eso pasa). Es una
   invariante directa e independiente de esa guarda, no alcanzable hoy a
   través de la API pública de `fusionar`, pero defensiva ante un refactor
   futuro.
5. **Sin contraparte.** Si más de un **tope absoluto de 3** registros actuales
   no aparecen en el snapshot, aborta. Es un tope absoluto, no un porcentaje:
   un umbral del 1% tolera 15 desapariciones sobre 1.589 registros, y ese
   margen crece sin límite a medida que la BD crece, cuando en datos reales
   este valor debe ser 0.
6. **Estados conocidos.** Si aparece un `es` que no está en `ESTADO_ORDER`,
   aborta. El universo air-e contiene `Normalizado`, que la UI no conoce: entraría
   sin color en el mapa y sin chip en el filtro. Hoy no afecta a ningún registro
   de la BD, y esta guarda evita que una alta futura rompa la UI en silencio.
   Va antes que la de deriva a propósito: un estado desconocido *es* la causa
   de la deriva, así que el diagnóstico específico debe ganarle a la alarma
   genérica.
7. **Deriva de estados.** Si más del **5%** de los estados cambia en una corrida,
   aborta. El referente: el commit `550f264` movió 11 estados de 1.586, o sea
   0,7%, y esta corrida mueve 0. Un salto masivo significa pull defectuoso.
8. **Coordenadas.** Si algún registro queda con `la`/`lo` fuera de la caja del
   Caribe colombiano (latitud 9,0–12,6, longitud -76,0– -71,5), aborta,
   nombrando los códigos y coordenadas ofensivas. No es un simple chequeo de
   "no es `None`": esa versión no atrapaba el centinela `0.0` (un
   `LATITUD: 0` pondría un pin en el Golfo de Guinea y pasaría todo). El
   registro `11142` del universo air-e declara `LATITUD: 1.10311` para
   "PUERTO COLOMBIA" —en el Amazonas, no el Caribe—; no está entre los 1.589,
   así que hoy la guarda no se dispara, pero sí lo haría si ese código
   entrara algún día.
9. **Municipios clasificados.** Si un registro entra con `ci` fuera de
   `DEPT_MAP`, aborta. Evita que aparezca como «Sin clasificar» sin que nadie lo
   note.

### En `fusionar`

10. **Empresa asignada para un alta.** Si un código cumple la regla de
    inclusión (`GD` o `AG ` con almacenamiento) y no tiene empresa asignada en
    `EMPRESAS_ALTAS`, aborta y pide la asignación a mano. No inventa el valor.

El umbral del 5% no necesita excepción para la corrida inicial: la deriva medida
es 0. Se registró la duda porque el diseño original suponía que esta corrida era
una corrección masiva; la medición mostró que no lo es.

### Reinyección en `index.html`

El `DATA` es la línea 395, una sola línea de 480 KB. La sustitución localiza el
prefijo `const DATA = [` y el `];` que lo cierra, y reemplaza solo ese tramo,
dejando intacto el resto del archivo — **nunca reescribiendo `index.html` completo
desde una plantilla**, que es la forma fácil de perder los 950 renglones de UI.
Se escribe a un temporal y se reemplaza de forma atómica. El JSON se serializa
con `ensure_ascii=False` y UTF-8, para no introducir escapes ni romper las
tildes.

## Interfaz de usuario

### Sidebar

Check `Solo con almacenamiento (N)`, en la sección de filtros junto a empresa y
ciudad, integrado a `passesOtherFilters` para que alimente por igual el contador
de resultados, el mapa, la lista, la vista Tabla y Análisis. El contador `(N)`
refleja los registros con almacenamiento **entre los visibles según los demás
filtros**, igual que los chips de estado. `clearFilters` lo resetea.

### Popup del mapa y ficha

En `selectPoint`, línea `Almacenamiento: Sí — 6.517 kWh` o `No`. Con `al = null`
muestra `Sin dato`, nunca `No`: son cosas distintas y confundirlas falsea la
lectura.

### Vista Análisis

Tarjeta resumen `Con almacenamiento: N solicitudes · X kWh total`, y tabla
explícita ordenada por capacidad descendente:

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
| **Capacidad (kWh)** | `ak`, a la derecha con `tabular-nums` |

Respeta los filtros activos del sidebar, así que sirve de inventario completo y
de vista filtrada. Con los filtros limpios arranca en **5 filas y 12.947 kWh**.
Cuando ningún registro visible tiene almacenamiento, muestra un estado vacío en
lugar de encabezados sueltos, con el patrón de
`008dcd0 Show empty-state message when no estado changes are detected`.

Va en un contenedor con scroll propio: si más adelante entran los 312
residenciales, pasaría a 316 filas sin rehacerla.

**Se renderiza desde `refresh()`, no desde `renderAnalysis()`.** `renderAnalysis`
tiene un `return` temprano cuando no hay cambios de estado (línea 690), y
cualquier render que dependa de él quedaría muerto en ese camino.

### Vista Tabla

No se le agrega columna de almacenamiento: sobre 1.589 registros el dato aparece
en 5, y quedaría vacía en el 99,7% de las filas. La tabla de Análisis cubre ese
caso mejor.

### Footer

`Actualizado 2026-09-10`; hoy dice `2026-09-01`.

## Pruebas

- **`transform.py`**: conversión de `/Date(ms)/` a UTC-5, normalización de
  espacios, redondeo a 5 decimales, mapeo de `al`/`ak`. Cada uno con su caso.
- **Registro golden `21941`**, contra `ejemplo.pdf`: `2024-10-30 14:32`,
  `Estudio solicitud`, `Green Yellow Energia de Colombia SAS`,
  `ARACATACA` / `ARACATACA`, `10.63491` / `-74.23092`, `Solar FV`,
  almacenamiento `No`, `0` kWh.
- **Registro golden `22810`** para la frontera de mes y el huso: `FEC_CREA` a las
  `22:37` UTC debe dar `2025-01-31 17:37`.
- **`merge.py`**: que preserve `e`, `se`, `p`, `un`, `b`; que no pierda
  registros; que aplique la regla de altas; que falle si un alta no tiene empresa
  asignada; y que cada una de las 7 guardas dispare cuando debe.
- **`inject.py`**: que reemplace solo el tramo del `DATA` y deje el resto del
  archivo byte a byte idéntico; que el resultado sea parseable; que falle si no
  encuentra los delimitadores.
- **`aire_client.py`**: que decodifique UTF-8 desde bytes; que detecte la página
  HTML de `Runtime Error` de ASP.NET en lugar de JSON y reintente; que construya
  ventanas semiabiertas.
- **UI**: que el filtro se integre a `passesOtherFilters` y su contador respete
  los demás filtros; que `se` vacío se renderice `—`; que la tabla ordene por
  capacidad descendente y muestre el estado vacío; que `GECELCA` aparezca en el
  filtro de empresas.
- **Post-build**: reabrir `index.html`, reparsear el `DATA`, verificar 1.589
  registros y contrastar los goldens. Si no queda parseable, el build falla.
- **Revisión humana del reporte de cambios** antes de commitear y desplegar.

## Entregables

- `scripts/aire_client.py`, `fetch_aire.py`, `transform.py`, `merge.py`,
  `inject.py`, `build_data.py` y sus tests
- `data/snapshots/aire-2026-09-10.json` (proyección slim, 10.640 registros)
- `data/reports/cambios-2026-09-10.md`
- `index.html` con 1.589 registros validados contra air-e, campos de
  almacenamiento, filtro en el sidebar, tabla en Análisis y `DEPT_MAP` corregido
- Reportes, todos como agregados dentro de `data/reports/cambios-<fecha>.md`
  (nunca como listado fila por fila): el universo air-e no incorporado por
  tipo/estado/mes (sección "Universo air-e no incorporado"); los 312
  residenciales con almacenamiento y el caso `21489` como candidatos excluidos
  por la regla de altas; los 3 registros con `al=true` y `ak=0` como
  almacenamiento incoherente. Los 5 códigos del sheet sin contraparte en air-e
  (`C139`, `C153`, `C159`, `20707`, `20715`) **no** están en ese reporte
  generado — quedan documentados en este spec, en "Los 5 códigos del sheet que
  no están en la BD", porque el pipeline no lee el sheet y no tiene forma de
  producirlos por su cuenta.

## Fuera de alcance

- **Cómo carga la app.** Los datos siguen embebidos en `index.html` como archivo
  único. Sacarlos a `data.json` haría los diffs de git legibles — hoy los
  registros son una sola línea de 480 KB, de ahí la cadena de commits
  `Backfill` / `Revert` / `Backfill` — pero mezclar un cambio de arquitectura de
  carga con una actualización de datos multiplica el riesgo. Paso posterior,
  pequeño y aislado.
- **Despliegue a Vercel.** Se decide después de revisar el reporte de cambios. El
  `.vercelignore` mantiene `docs/`, `data/`, `scripts/` y `tests/` fuera del
  deployment: el sitio es estático, así que sin esa exclusión el spec y los
  snapshots quedarían alcanzables por URL pública.
- **El resto del universo air-e.** Solo entran los que cumplen la regla de
  almacenamiento. Los 312 residenciales y los ~1.000-1.500 de escala proyecto sin
  almacenamiento quedan aplazados, con el reporte como insumo.
