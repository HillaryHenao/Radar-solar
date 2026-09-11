# Pendiente: filtro por cliente e incorporación de Unergy 2026

**Fecha:** 2026-09-10
**Estado:** diseño acordado, falta una decisión y la implementación
**Punto de partida:** `main` en `8975cbe`, 98 tests en verde, 1.589 registros

## Qué disparó esto

Al filtrar el radar por año 2026 y Unergy aparecían 5 resultados, mientras la hoja
Sept 9 del sheet mostraba decenas de códigos activos de Unergy para 2026.

## Diagnóstico: eran tres causas distintas

Filtrando la hoja por cliente Unergy + `initial_date` 2026 + `type_supply` activo
salen **42 códigos**. De esos, **38 sí están en el radar** y 4 no.

### A. Los dos sistemas miden años distintos — CERRADA, no es defecto

De los 38 que están, el radar los ubica en 2025 (25), 2024 (9) y 2026 (4).

El radar usa la **fecha de radicación en air-e** (`FEC_CREA`). La hoja usa
`initial_date`, que es la fecha del **proceso ECS interno**. Un proyecto radicado
en agosto de 2025 puede entrar al pipeline en 2026.

**Decisión del usuario:** la fecha válida es la que sale del portal de air-e. El
radar está bien; no se incorpora `initial_date` al modelo. Causa cerrada.

### B. El campo `empresa` no es el cliente — PENDIENTE

`empresa` (`e`) es la cuenta que radicó ante air-e, no el dueño del proyecto. De
los 38, **35 tienen `e = GMAIL`**. Por eso el filtro de empresas no los encuentra;
el buscador sí, porque mira también el cliente.

El campo está partido para un mismo cliente: 168 registros de Unergy dicen `GMAIL`
y otros dicen `Unergy Energía Digital S.A.S`. **Nunca va a dar un conteo confiable
de "proyectos de Unergy".**

`cliente` (`cl`), en cambio, viene de air-e, es confiable y existe para los 10.641
registros del universo.

### C. Registros ausentes — PENDIENTE

| Unergy como cliente | air-e | En el radar |
|---|---|---|
| 2023 | 83 | — |
| 2024 | 386 | — |
| 2025 | 927 | — |
| 2026 | 232 | 5 |
| **Total** | **1.633** | **214** |

Faltan **227 de 2026**, todos `AGPE menor igual 1MVA y mayor 0.1MVA`. No es un
fallo del pipeline: es la decisión aplazada de no incorporar registros nuevos.

## Diseño acordado

El usuario eligió: **filtro por cliente + incorporar los 227 de Unergy 2026**
(radar pasa de 1.589 a 1.816).

### 1. Filtro de cliente en el sidebar

Multiselect junto a empresa y ciudad, reusando `createMultiSelect` (ya trae
buscador). Se integra a `passesOtherFilters`, así alimenta mapa, lista, Tabla y
Análisis por igual. Hay **868 clientes distintos** y sigue habiendo 868 después de
sumar los 227, porque el nombre ya existe.

### 2. Regla de incorporación en `merge.py`

> cliente contiene "unergy" **y** fecha de solicitud desde `2026-01-01`

Anclada en "desde 2026" y no en "año 2026" para que sea automantenida: cuando
llegue 2027 esos proyectos entran solos.

Campos propios de las altas:

| Campo | Valor |
|---|---|
| `e` | `UNERGY` (derivado del cliente, no `GMAIL`) |
| `se` | vacío, se renderiza `—` |
| `p` | vacío |
| `un` | `true` |
| `b` | batch de la corrida |

### 3. Guardas

`TOTAL_MINIMO` pasa de 1.589 a **1.816**. Las demás quedan igual.

**Verificado que los 227 pasan todas las guardas:** 0 municipios fuera de
`DEPT_MAP`, 0 estados fuera de `ESTADO_ORDER`, 0 sin coordenadas, 0 fuera del
bounding box del Caribe. Los 227 comparten el mismo nombre de cliente,
`Unergy Energía Digital S.A.S`.

## LA DECISIÓN QUE FALTA

Al asignar `e = UNERGY` a los nuevos, el filtro de empresas mostrará **tres
entradas para Unergy**: `GMAIL`, `Unergy Energía Digital S.A.S` y `UNERGY`, porque
los 214 existentes conservan su valor. El campo queda más confuso, no menos.

**Opción A** — dejarlo así. El filtro de cliente es el que da el número correcto;
`empresa` queda como está y no se tocan datos preservados.

**Opción B** — normalizar `e` a un solo valor para todos los registros de Unergy,
existentes incluidos. Más limpio, pero modifica un campo preservado, algo que este
pipeline nunca hizo hasta ahora.

## Contexto operativo

- El CSV `Solicitudes ECS de A-ire - Sept 9.csv` está en la raíz del repo y se
  agregó a `.gitignore`: son 1.691 filas con nombres de clientes y coordenadas, y
  `.vercelignore` no lo cubriría. No commitear.
- La herramienta de Google Drive **trunca el sheet**: devuelve unos 275 códigos de
  los 1.691 reales, con el `external_code` más alto en 23898. Para trabajar sobre
  la hoja hay que exportarla a CSV.
- **GitHub sigue sin nada.** `main` local tiene 24 commits que el remoto no tiene.
  El push requiere que lo corra el usuario:
  `git push origin main`
- Hay un preview desplegado en Vercel
  (`radar-solar-lv4f0tmru-hillary-5267s-projects.vercel.app`), pero el proyecto
  entero está detrás del login de Vercel, así que para compartirlo hace falta un
  link de Share desde el dashboard.
