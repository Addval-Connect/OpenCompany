---
name: "interpreta-cartola"
description: "Pipeline de 4 pasos en orden. El context de la taskmanager trae rutas"
metadata:
  author: opencompany
  version: "1.0"
  category: "assistant"
  icon: "📊"
  color: "#10B981"

---

# Interpretar cartola (runbook A2)

Pipeline de 4 pasos en orden. El `context` de la `task_manager` trae rutas
workspace-relativas: el índice de páginas de A1 (`sesion/indice_paginas.json`), el directorio de
páginas (`.txt`/`.jpeg`) y `pagina_1.json`. Estado en la TeamTask + archivos del workspace, no en
memoria. Un solo resultado de tarea al final; acumula en `sesion/cartola_base.json` →
`sesion/cartola.json`.

Dos reglas transversales de todo el runbook:
- **El LLM no calcula.** No multipliques cuotas×precio, no conviertas moneda, no sumes totales.
  Transcribe cantidad/precio/monto tal como aparecen; el cálculo lo hace A3.
- **Lectura por imagen sin OCR.** Si una página no tiene texto confiable, lee el `.jpeg` con
  `file_read` (visión del LLM) — ver la skill `leer-tabla-desde-imagen` para los dos escenarios.

## Paso 1 — Identificar custodio (solo página 1)

Lee la página 1 (`pagina_1.json` → `.txt` o `.jpeg`) con `file_read`. Cortes previos:
- `context` sin índice/páginas o índice vacío → `custodio: null` + `"no se recibio cartola"`. Para.
- `texto_disponible_global: false` y la imagen de p.1 tampoco deja leer el membrete →
  `custodio: null`, `texto_disponible: false`, `"cartola sin capa de texto: requiere lectura por
  imagen"` (esperable en BCI/UBS/Moneda escaneadas). Para.

Clasifica por señales de la página 1:

| Señales | Código |
|---|---|
| "Banchile", banchileinversiones.cl, "ESTADO DE TUS INVERSIONES" | `BANCHILE` |
| "Itaú", "Informe Mensual de Cartera" | `ITAU` |
| "BICE Inversiones", biceinversiones.cl | `BICE` |
| "BCI", "Cartola Inversiones", "Fondos Mutuos" | `BCI` |
| "Ameris Capital", ameris.cl, "Estado de Cuenta" | `AMERIS` |
| "Moneda Corredores de Bolsa", "Pershing", cuenta "NSP-" | `MONEDA` |
| "Merrill Lynch", "MLPF&S", "WCMA", "Account Number: XXX-XXXXX" | `MERRILL` |
| "Banco Santander International", Miami | `SANTANDER` |
| "UBS Financial Services", "Account number: 3J..." | `UBS` |

Sin coincidencia → `null`, confianza baja (no inventes un décimo custodio). Atributos:
`multi_cuenta` (más de una cuenta del mismo titular), `consolidada` (agrupa custodios terceros —
Ameris consolida BICE/Security/Compass). Alertas obligatorias: consolidada → `"cartola consolidada:
verificar regla de precedencia..."`; multi_cuenta → `"cada movimiento debe llevar su propio
numero_cuenta"`.

## Paso 2 — Recuperar el diccionario del custodio (lectura íntegra, no transcripción)

Pedirle al modelo que "transcriba" la ficha omite secciones en silencio: recupérala como archivo
entero. Las fichas viven en `diccionarios/` (sembradas por Tax), con nombre
`Diccionario Extractor Cartola <custodio>.md`.

**Localízalas por glob, nunca por título exacto.** Los nombres reales tienen variaciones que un
match exacto no tolera: `cartola` en minúscula (Itaú), y caracteres del título que no pueden existir
en un nombre de archivo (`MONEDA / Pershing` está en disco como `MONEDA Pershing`). Un glob por el
código de custodio también absorbe versiones futuras (`... UBS-v2.md`) sin tocar este skill.

El glob **distingue mayúsculas** (`fs_search` usa `rglob`), así que usa la clave de la tabla tal
cual está escrita — son las capitalizaciones que existen en disco. Si una ficha nueva llega con otra
capitalización, el glob no la verá: eso es un corte duro (ficha no encontrada), no un fallback.

`fs_search` mode=`glob`, path=`diccionarios`, pattern=`*<clave>*` (ver tabla) → `file_read` del
archivo completo. Si el glob devuelve más de una ficha, usa la de mayor versión.

| Código | Clave de glob (respeta mayúsculas) |
|---|---|
| `BANCHILE` | `*Banchile*` |
| `ITAU` | `*Itau*` |
| `BICE` | `*BICE*` |
| `BCI` | `*BCI*` |
| `AMERIS` | `*Ameris*` |
| `MONEDA` | `*MONEDA*` |
| `MERRILL` | `*MERRILL*` |
| `SANTANDER` | `*Santander*` |
| `UBS` | `*UBS*` |

Al abrir, verifica que la primera línea diga `DICCIONARIO DEL CUSTODIO: <NOMBRE>` y que ese nombre
empiece por el `Código` de la tabla (MONEDA declara `MONEDA / PERSHING`). Con búsqueda por glob este
chequeo es la única garantía de que abriste la ficha correcta: no lo omitas. Extrae
`jurisdiccion_custodio` de la sección IDENTIFICACIÓN. Persiste el diccionario como
`sesion/diccionario_vigente.md` (o referencia su ruta) — **nunca lo resumas ni reescribas**.

Cortes duros (preceden a todo):
- **Ficha no encontrada** → `diccionario_recuperado: false`, `custodio.codigo: null`, confianza
  baja, `"ficha no encontrada en repositorio para custodio <nombre>"`. NO adaptes el diccionario de
  otro custodio parecido.
- **Nombre de archivo ≠ cuerpo** (el glob trajo otra ficha) → `custodio.codigo: null`,
  `"ficha inconsistente: titulo y cuerpo no coinciden"`.
- **Sin `jurisdiccion_custodio` en la ficha** → tabla de respaldo (BANCHILE/ITAU/BICE/BCI/AMERIS →
  `nacional`; MONEDA → `nacional_custodia_extranjera`; MERRILL/SANTANDER/UBS → `extranjero`) +
  `"jurisdiccion no declarada: se usa tabla de respaldo"`. Si `nacional_custodia_extranjera` →
  además `"jurisdiccion ambigua: requiere definicion de Tax"`.

## Paso 3 — Extraer y clasificar movimientos en 4 destinos

Lee el diccionario íntegro (`file_read`) antes de empezar. Navega páginas con `fs_search` (por
palabras clave, tipo `grep -iln` sobre los `.txt`) — no cargues la cartola completa al contexto.
Acumula en `sesion/cartola_base.json` (`file_modify`) a medida que clasificas.

| Destino | Contenido | Efecto |
|---|---|---|
| **1 · `movimientos`** | Compras/ventas que mueven el Kárdex | Se cargan a Odoo |
| **2 · `movimientos_contables`** | Intereses, dividendos, comisiones | Se registran, NO al Kárdex |
| **3 · `requiere_confirmacion`** | Disminución de capital, reinversión en cuotas, códigos no documentados | Pendientes al usuario |
| **4 · `excluidos`** | Caja, traspasos internos, saldos, agregados de posiciones | Se descartan con motivo |

El diccionario define qué descripción/código va a cada destino — no inventes criterios propios.
Reglas de negocio:
- **Fecha de valor/liquidación, nunca fecha de apunte/solicitud** (el diccionario dice cuál columna).
- **Identificador externo (R3)**: si el diccionario dice que no hay identificador único (Banchile:
  nombre + serie separados por el literal "Serie"), deja `identificador_externo: null` y
  `tipo_identificador: null` explícitos.
- **Totales de control (R16)**: transcribe líneas de totalización tal cual; sin ellas,
  `totales_control: []` (nunca inventes).
- Advertencias del diccionario son bloqueantes (ej. Ameris VEHÍCULO=CAJA con códigos `REUS`/`DIUS`
  no documentados → destino 3, `cuenta_contable_propuesta: null`, no inferir).
- Layout que se desalinea en texto plano (página 5 Banchile) → usa `leer-tabla-desde-imagen` para
  esa página.
- Dividendo reinvertido en cuotas: aumenta cuotas (parece destino 1) pero se origina en dividendo →
  destino 3 con observación `"reinversion"`, salvo que el diccionario indique otro tratamiento.
- Por línea de destino 1, propón `instrumento_propuesto`/`serie_propuesta` con
  `confianza_instrumento` (A3 lo empareja contra Odoo).

## Paso 4 — Validar contra el esquema estricto y emitir

`file_read` de `cartola_base.json`; valida y escribe `sesion/cartola.json` (`file_modify`). Reglas:
- `tipo_movimiento` solo `COMPRA`/`VENTA` en destino 1; `cantidad_cuotas > 0`.
- Fechas ISO 8601 dentro del período ±5 días hábiles. Fuera de rango: no corrijas, alerta + deja
  para revisión.
- `identificador_externo`/`tipo_identificador` en par (uno null → ambos null).
- `totales_control` siempre arreglo (vacío si no publica), nunca null ni omitido.

Fallo de validación: **1er fallo** reintenta la generación UNA vez indicando qué regla falló (puede
requerir rehacer el paso 3). **2do fallo** → pendiente `REQUIERE_USUARIO` con el JSON crudo; el
COORD lo lleva al usuario.

## Salida (un resultado de tarea al COORD)

```json
{
  "ruta_json_cartola": "sesion/cartola.json",
  "json_cartola": {
    "cartola": {"cliente_nombre": "…", "custodio": "BANCHILE", "periodo_desde": "…", "periodo_hasta": "…"},
    "movimientos": [], "movimientos_contables": [], "requiere_confirmacion": [],
    "excluidos": [], "totales_control": []
  },
  "custodio": {"codigo": "BANCHILE", "jurisdiccion": "nacional", "diccionario_id": "diccionario-banchile-v1", "confianza": "alta"},
  "alertas": []
}
```
El COORD avanza la sesión a `INTERPRETADA` y delega a A3.

## Casos de borde

- **Cero movimientos de destino 1 pero con `movimientos_contables`** (Itaú, BICE, Merrill): emisión
  válida, emite igual.
- **Cartola consolidada (Ameris)**: extrae tal como viene; el cruce de doble contabilización lo
  resuelve A3 (`consolida-informacion`), no aquí.
- **Ambigüedad entre dos interpretaciones plausibles**: no elijas arbitrariamente → destino 3
  (`requiere_confirmacion`) motivo `otro` con la pregunta específica.
- **Custodio sin diccionario** (no debería llegar aquí): todo `confianza_instrumento: baja` +
  `"custodio sin diccionario — requiere revision manual completa"`.
