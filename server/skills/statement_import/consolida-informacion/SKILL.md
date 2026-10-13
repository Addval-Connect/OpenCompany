---
name: "consolida-informacion"
description: "Pipeline de 5 pasos en orden sobre el cartola.json de A2 (ruta en el context, fileRead)."
metadata:
  author: opencompany
  version: "1.0"
  category: "statement_import"
  icon: "🧮"
  color: "#6366F1"

---

# Consolidar información (runbook A3)

Pipeline de 5 pasos en orden sobre el `cartola.json` de A2 (ruta en el `context`, `fileRead`).
Enriquece el JSON con `fileModify` y devuelve UN resultado al COORD. Odoo se consulta con la tool
`odoo_jsonrpc` (host/db/credenciales fijos en el nodo, invisibles); la aritmética exacta en
`javascriptExecutor`. No reinterpretas la cartola (eso es A2): si sospechas mala extracción, levanta
pendiente, no corrijas el JSON.

Skills adicionales, solo si aplican: `armar-lote-de-pendientes` (consolidar dudas para el usuario) y
`aplicar-respuestas-al-json` (tras respuestas del usuario).

## Cómo llamar a Odoo (`odoo_jsonrpc`)

Solo eliges la llamada de negocio; nunca URL/credenciales. `method`: `search_read` (con `domain`,
`fields`, `limit`), `read` (con `ids`), `search`, `search_count`, `fields_get`. Todas las consultas
de A3 son SOLO LECTURA. Resultado en `result`; si `ok:false`, lee `error` y corrige la llamada.

## Paso 1 — Obtener maestros (cachear, no re-consultar)

El plan tiene ~500 instrumentos; trae en bloque lo que la sesión necesita y cachéalo en
`cartola/maestros_odoo.json` (`fileModify`). Los pasos siguientes lo leen del cache, no re-consultan.

1. **Custodio**: `res.partner` por `is_financial_administrator=True` + `vat` (RUT) o nombre;
   `fields=["id","name","vat","currency_id"]`.
2. **Instrumentos** del custodio+cuenta en bloque:
   `product.product` `domain=[["is_investment_product","=",true],["administrator_id","=",<id>],["account_number","=",<acc>]]`,
   `fields=["id","name","default_code","series","investment_currency_id","account_number","nationality","legal_disposition"]`.
   Guarda el `default_code` **completo** de cada uno (A4 deriva de ahí el nombre de API).
3. **Monedas**: `res.currency` por `name in [...]`, `fields=["id","name","decimal_places"]`,
   `context={"active_test": false}`. **`decimal_places` importa** (CLP=0, no 2).

Error/timeout de Odoo → no asumas maestros vacíos (produce falsos negativos); devuelve `"error de
conexión a Odoo"` y detén hasta reintentar.

## Paso 2 — Resolver cliente titular (bloqueante)

Si el cliente está mal, cada línea queda bien formada pero en la cuenta equivocada — ni el esquema
ni la cuadratura lo detectan. Cruza nombre + RUT contra los candidatos; **el RUT manda** sobre el
nombre.
- Único candidato con RUT coincidente → confianza alta, resuelto (`fileModify`
  `cartola.cliente_resuelto`).
- Sin RUT visible + nombre exacto único → confianza media, continúa con alerta.
- Dos o más plausibles, o cero → **no decidas por texto ni crees cliente**. Pendiente bloqueante
  `cliente_ambiguo`; ningún otro paso avanza hasta resolverlo.

## Paso 3 — Emparejar cada instrumento

Por cada línea de destino 1, resuelve el `product.product` (usa el cache del paso 1; solo búsquedas
puntuales van a Odoo) y persiste TODOS estos campos (A4 los necesita; si falta uno, A4 itera a
ciegas):

| Campo persistido | Origen |
|---|---|
| `producto_odoo_id` | `product["id"]` (entero; será `financial_instrument_id`). |
| `default_code` | `product["default_code"]` **completo verbatim**. |
| `serie` | `product["series"][1]`. |
| `currency_id` / `currency_name` | `investment_currency_id[0]` / `[1]`. |
| `account_number` | `product["account_number"]`. |
| `article_107_flag` | `(nationality=="national" AND legal_disposition=="article_107")`. |

`financial_instrument_id` es el **id entero**, NO el `default_code`. Indexa el maestro por
`(name, series, currency)` normalizado (acentos plegados, espacios colapsados, minúsculas) — no por
el `default_code` crudo. Prioridad: (1) identificador externo (ISIN/CUSIP/nemotécnico; en Ameris el
nemotécnico de VEHÍCULO se cruza primero contra las posiciones de la misma cartola), (2) triple
normalizado, (3) similitud nombre+serie con umbral (menos confiable → refléjalo en confianza).
Banchile no publica identificador (separa por el literal "Serie"). Sin match → pendiente
`instrumento_sin_match`, no lo fuerces. Nunca subas la confianza por presión de completar.

## Paso 4 — Validar y calcular totales (en `javascriptExecutor`, NO el LLM)

- `total_sistema = cantidad × precio_unitario`; `fee = total_cartola − total_sistema` (registra con
  su signo, no lo fuerces a cero; no se carga al Kárdex — línea contable P-04).
- **Redondea `unit_price` a 4dp PRIMERO**, luego `total_amount = round(cantidad × precio, decimales
  de la moneda)` (CLP=0). Validar con precio sin redondear provoca total-mismatch en A4.
- **Santander** no imprime precio: deriva `precio = total_cartola / cantidad` (4dp) y marca para
  confirmación humana.
- **Ameris**: líneas USD que parecen venir en CLP → valida contra la posición; inconsistencia →
  alerta de moneda, no la corrijas. "Flujo Neto" es neto de entradas/salidas, no cuadres contra
  compras/ventas por separado.
- Contrasta `totales_control` (R16) vs suma de movimientos de esa cuenta+moneda.
- Moneda extranjera sin FX explícito → no sustituyas; señala que en A4 requerirá
  `exchange_rate_manual`.

## Paso 5 — Detectar carga duplicada (solo lectura)

Segunda barrera tras el hash de A1. Modelos: `kardex.import.log` (header) y `kardex.import.line`
(operaciones vía `log_id`); no existe `kardex.import`. `kardex.import.log.name` es "..." — clave
natural `(custodian_id, account, kardex_period)`.

**Campos EXACTOS para el search (no los inventes — el header NO tiene `partner_id` ni `client_id`):**
- `kardex.import.log`: `custodian_id` (m2o res.partner, es el custodio), `account` (char),
  `kardex_period` (char "YYYY/MM"), `state`. NO existen `partner_id`/`client_id`/`nro_documento`.
- `kardex.import.line`: `log_id` (m2o al header), `financial_instrument_id`, `operation_date`,
  `movement_type`, `quantity`, `unit_price`.

1. Localiza primero el header del slot: `kardex.import.log` `search_read`
   `domain=[["custodian_id","=",<id>],["account","=",<acc>],["kardex_period","=","<YYYY/MM>"]]`,
   `fields=["id","state"]`. Sin header → no hay duplicado, termina el paso. Con header, toma su `id`
   y busca sus líneas: `kardex.import.line` `search_read`
   `domain=[["log_id","=",<log_id>]]`, `fields=["financial_instrument_id","operation_date","movement_type","quantity","unit_price"]`.
2. Cruza cada línea emparejada de la cartola contra esas líneas por
   `(financial_instrument_id, operation_date, movement_type, quantity)`. Coincidencia →
   `duplicado_confirmado`, exclúyela, registra el id de la `kardex.import.line` existente.
2. Consolidada (Ameris): verifica si otra sesión del período ya cargó ese instrumento desde el
   custodio tercero. No asumas la fuente de verdad — sin poder determinarla, pendiente `otro` con
   ambas fuentes; no cargues ninguna. Corrección legítima del custodio (mismo mov, montos
   distintos) → alerta, deja que Tax decida; A3 nunca escribe al Kárdex.

## Salida (un resultado al COORD)

El `cartola.json` enriquecido en el workspace + resumen: cliente resuelto, instrumentos emparejados
con `producto_odoo_id`/`default_code`/`serie`/`currency_id`/`article_107_flag`, totales/fees,
duplicados detectados, y `pendientes[]`. El COORD decide: pendientes → usuario; limpio → A4.

## Casos de borde

- **Cero instrumentos para el custodio+cuenta**: señala búsqueda vacía; no sigas la consolidación
  normal.
- **Serie ausente en la cartola**: usa el default del producto (no inventes), sin bloquear, con
  constancia.
- **`precio ≈ 0` y `monto ≈ 0`**: no es transacción (traspaso/ajuste); debió ir a excluidos en A2.
  No lo fuerces a destino 1.
