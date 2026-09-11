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
- **Hay dos reglas de inclusión en `merge.py`, con manejo de empresa distinto
  y sin relación entre sí:**
  - `es_alta` — proyectos de escala de red (`GD`/`AG `) con almacenamiento.
    **Necesitan empresa asignada a mano** en `EMPRESAS_ALTAS`. Si la regla
    captura un código nuevo sin empresa, el build falla y lo pide: no inventa
    el valor. Son pocos por corrida, así que asignar a mano es viable.
  - `es_alta_unergy` — cliente contiene "unergy" (sin importar mayúsculas) y
    fecha de solicitud desde 2026-01-01 en adelante (ancla "desde", no "año
    ==", para que sea automantenida cuando llegue 2027). La empresa **se
    deriva de la regla misma**: siempre `UNERGY` (constante `EMPRESA_UNERGY`),
    nunca `EMPRESAS_ALTAS`. Son 227 códigos en la primera corrida — demasiados
    para asignar a mano, y no hace falta: ya se sabe cuál es la empresa porque
    es literalmente lo que la regla filtra. Ver
    `docs/notas/2026-09-10-pendiente-filtro-cliente.md` para el diagnóstico
    completo (por qué `empresa`/`e` no sirve para contar "proyectos de
    Unergy": está partido entre `GMAIL` y `Unergy Energía Digital S.A.S` para
    el mismo cliente).
- Las guardas abortan sin escribir. Son 8 en total, y no las 7 del spec (ese
  numero cuenta identidad propia y cobertura de red, que viven en
  `aire_client.py`/`fetch_aire.py`, no en `merge.py`): `_valida_guardas` en
  `scripts/merge.py` tiene 7 caminos de abort (conteo, no eliminación, sin
  contraparte, estados conocidos, deriva de estados, coordenadas fuera del
  Caribe, municipios sin `DEPT_MAP`), y `fusionar` tiene una octava, separada,
  para un alta de `es_alta` sin empresa asignada (esa guarda no aplica a
  `es_alta_unergy`, que nunca necesita asignación manual). Si una se dispara,
  el mensaje dice qué revisar.
