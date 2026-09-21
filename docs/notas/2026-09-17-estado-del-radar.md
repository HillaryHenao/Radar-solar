# Estado del Radar Solar — 2026-09-17

Reemplaza a `2026-09-10-estado-del-radar.md`, que quedó desactualizada tras la
incorporación de minigranjas GD y el backfill de potencia AC.

## Dónde está todo

| | |
|---|---|
| Repo local | `C:\Users\EQUIPO\Documents\Claude\Aire\radar-solar-web`, rama `main` |
| GitHub | `git@github.com:HillaryHenao/Radar-solar.git`, al día |
| **Producción (público, sin login)** | **https://radar-solar-web.vercel.app/** |
| Tests | 125, `python -m pytest` desde la raíz |

### Cuidado con las URLs de Vercel

Vercel entrega dos clases de URL y **solo una sirve para compartir**:

- `https://radar-solar-web.vercel.app/` — dominio estable del proyecto,
  **público**. Este es el que se le pasa a la gente.
- `https://radar-solar-<hash>-hillary-5267s-projects.vercel.app/` — URL por
  deployment, **protegida** por Vercel Authentication, que en plan Hobby viene
  activada por defecto. Pide login aunque el deployment sea de producción.

El CLI devuelve la segunda al desplegar, y es fácil pasarla por error.

## Qué contiene el radar hoy

3.141 registros validados contra el portal CREG030 de air-e.

- 3 con almacenamiento de energía, 12.932 kWh en total
- 445 marcados como cliente Unergy (campo `un`)
- Los 3.141 registros ya tienen potencia AC (`pac`) — se completó el backfill
  que antes dejaba ese campo en `None` para la mayoría
- El detalle de un municipio en "Análisis" ahora abre además un gráfico de
  barras con las empresas de ese municipio, ordenadas de mayor a menor
  solicitud (solo aplica a la dimensión municipio, no a empresa/departamento)

## Qué cambió desde el 10 de sept

| Commit | Qué hizo |
|---|---|
| `fc9b527` | +3.205 registros: incorpora minigranjas GD ~1MW desde 2025 |
| `a8e1253` | fix: quita 64 registros AGPE residencial de techo sin valor → 3.141 |
| `b8f998c` | potencia AC (`pac`) visible y filtrable; backfill en toda la base |
| `b8273e2` | gráfico de barras empresa-vs-municipio en el detalle de Análisis |

Confirmado el 21 de sept: repo local, GitHub y el deploy de Vercel (hace 4
días en ese momento) están sincronizados — mismo tamaño de archivo exacto
(1.099.111 bytes) y el sitio público responde 200.

## Cómo se actualiza

```bash
python -m scripts.fetch_aire                                    # baja air-e
python -m scripts.build_data --snapshot data/snapshots/<f>.json --dry-run
python -m scripts.build_data --snapshot data/snapshots/<f>.json # escribe
vercel --prod --yes                                             # despliega
```

Detalle operativo completo en `scripts/README.md`. Diseño y decisiones en
`docs/superpowers/specs/2026-09-10-radar-solar-consulta-aire-design.md`.

**Correr siempre `--dry-run` primero y leer el reporte** en `data/reports/`. Ocho
guardas abortan antes de escribir si algo se ve mal, pero la revisión humana del
reporte es la que no se puede automatizar.

## Cosas que costó descubrir y no hay que volver a sufrir

**`empresa` no es el cliente.** `e` es la cuenta que radicó ante air-e, no el
dueño del proyecto. Para Unergy suele ser `GMAIL`. El campo está partido: 168
registros dicen `GMAIL`, otros `Unergy Energía Digital S.A.S`, y otros dicen
`UNERGY`. **Nunca da un conteo confiable por empresa.** Por eso se agregó el
filtro de **cliente** (`cl`), que viene de air-e y sí es fiable.

**Los dos sistemas miden años distintos.** El radar usa `FEC_CREA`, la fecha de
radicación en air-e. El sheet usa `initial_date`, la fecha del proceso ECS
interno. Un proyecto radicado en 2025 puede entrar al pipeline en 2026. Decisión
tomada: **la fecha válida es la de air-e**.

**La ventana de fechas del portal es semiabierta.** `FECHAFIN` es exclusivo a las
00:00, así que cerrar en el último día del mes pierde todo lo creado ese día — en
el histórico completo eran 272 registros.

**air-e responde UTF-8.** Decodificar desde Latin-1 corrompe cada acento y produce
cambios fantasma.

**`EL PI¿ON`** es cómo air-e escribe El Piñón: bytes `C2 BF`, no la eñe. La clave
de `DEPT_MAP` usa la forma corrupta a propósito.

**La herramienta de Google Drive trunca el sheet.** Devuelve unos 275 códigos de
los 1.691 reales. Para trabajar sobre la hoja hay que exportarla a CSV. Los `.csv`
están en `.gitignore`: son datos de clientes y no van al repo ni al deployment.

## Decisión abierta

Al incorporar los 227 de la ronda anterior, el filtro de **empresa** quedó con
tres variantes de Unergy: `GMAIL`, `Unergy Energía Digital S.A.S` y `UNERGY`. Se
dejó así a propósito para no modificar campos preservados de los registros
existentes.

Si molesta, normalizar `e` a un solo valor para todos los registros de Unergy es
un cambio chico — pero sería la primera vez que el pipeline reescribe un campo
preservado, y eso merece decidirse conscientemente.

## Pendiente menor

El sitio está **público**: cualquiera con el link ve 3.141 solicitudes con
nombres de clientes y coordenadas. Si se quiere cerrar: Settings → Deployment
Protection.
