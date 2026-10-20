---
name: "importa-a-odoo"
description: "Pipeline de 4 pasos sobre el consolidado de A3 (ruta en el context, fileRead). ÚNICO punto de"
metadata:
  author: opencompany
  version: "1.0"
  category: "statement_import"
  icon: "📤"
  color: "#6366F1"

---

# Importar a Odoo (runbook A4)

Pipeline de 4 pasos sobre el consolidado de A3 (ruta en el `context`, `fileRead`). ÚNICO punto de
escritura del sistema — ningún otro agente escribe en Odoo. Odoo por la tool `odoo_jsonrpc`
(host/db/credenciales fijos en el nodo); la aritmética la valida Odoo en escritura (constraints del
módulo carga_kdx) y el read-back la confirma. Skill adicional
solo si hay rechazos: `administrar-casos-de-borde-carga`.

Precondición: no ejecutes si quedan `pendientes[]` con `respuesta: null` o líneas de destino 1 con
`confianza ≠ alta` sin confirmar (el COORD no debe delegar antes).

## Modelos y reglas invariantes (Odoo NO las autocompleta por RPC)

- Header **`kardex.import.log`**, líneas **`kardex.import.line`** (NO `kardex.import.log.line`; no
  existe `kardex.import`). Header + TODAS las líneas en UNA sola llamada `create`, líneas anidadas
  `[0,0,{...}]` en `line_ids`. El `create` es **todo-o-nada**: una línea mala hace rollback de todo.
- **`financial_instrument_id`** = id entero del producto, **Y** **`financial_instrument_name`** =
  segmento de nombre del `default_code` almacenado (quita prefijo `<admin_id>-<account>-` y sufijo
  `-<serie>-<moneda>`). Envía SIEMPRE ambos; cualquiera solo falla. A3 ya entrega el `default_code`.
- **`unit_price` a 4dp PRIMERO, luego `total_amount = round(qty × price, decimales de la moneda)`**
  (CLP=0). Calcular con precio sin redondear → total-mismatch (#7).
- **Nunca `line_ids` vacío u omitido** — header sin líneas bloquea el slot para siempre.
- `name` es "..."; identidad = `log_id` entero; clave natural `(custodian_id, account, kardex_period)`.

## Paso 1 — Construir el payload

Lee el consolidado; por cada movimiento de destino 1 (nunca `movimientos_contables`/`excluidos`)
arma la línea con el mapeo de abajo. Deriva el nombre y calcula precio/total con los redondeos de
abajo; Odoo valida en escritura y el read-back confirma. Clave de idempotencia por línea:
`<custodian_id>-<account>-<period>-mov-<N>`.
Campo obligatorio faltante → devuelve esa línea como pendiente `otro`, no rellenes con default.
`fileModify` del payload.

Header: `kardex_date` (YYYY-MM-DD, no futura, define el período), `custodian_id`, `account`,
`line_ids`. Línea: `financial_instrument_id`, `financial_instrument_name`, `instrument_series`
(=`product.series[1]` verbatim), `article_107_flag` (bool real), `operation_date`
("YYYY-MM-DD HH:MM:SS" UTC, mismo año+mes que el header), `movement_type`
(`purchase`|`sale`|`rescue`|`dividend`; COMPRA→purchase, VENTA→sale), `quantity` (>0), `unit_price`
(4dp), `total_amount`, `currency_id` (=`investment_currency_id[0]`), opcionales
`exchange_rate_manual` / `correction_year` (solo en purchase). Cero movimientos → payload vacío, NO
header vacío; salta al paso 4.

## Paso 2 — Pre-validar contra Odoo (solo lectura; el create es todo-o-nada)

Casi todos los rechazos son decidibles antes leyendo el producto. En pocas llamadas, no una por
línea:
1. Revisión del payload (antes de escribir): id+name presentes, `line_ids` no vacío, `total_amount ==
   round(qty × price, decimales)`, `currency_id` = moneda del instrumento, `article_107_flag` bool,
   `operation_date` no futura y en el mes del header. Las constraints de Odoo (carga_kdx) son la
   validación definitiva en escritura.
2. Odoo (solo lectura): resuelve instrumentos en bloque
   (`product.product` `domain=[["is_investment_product","=",true],["administrator_id","=",<c>],["account_number","=",<a>]]`),
   indexa por `(name,series,currency)` normalizado; toda línea sin match predice R1. FX: para líneas
   fuera de la moneda de la compañía, confirma `res.currency.rate` cubriendo `operation_date` o que
   traiga `exchange_rate_manual` (sin rate → R2).
Líneas que fallan → sepáralas y devuélvelas al COORD para `administrar-casos-de-borde-carga`; no
descartes el lote entero. Todas pasan → continúa.

## Paso 3 — Insertar (create + read-back)

```
odoo_jsonrpc(model="kardex.import.log", method="create",
             values={kardex_date, custodian_id, account, line_ids:[[0,0,{...}], ...]})
  → result = log_id
```
1. **Idempotencia**: antes de crear, `search_read` del slot `(custodian_id, account,
   kardex_period)`. Existe con líneas → no recrees (registra como aplicado, salta a leer). Existe
   vacío → `unlink` y continúa. Cachea claves aplicadas en `payload/<periodo>-aplicadas.json`.
2. `create` con TODAS las líneas nuevas. `ok:false` → lee `error` (rechazo de negocio; corrige el
   payload, NO cambies host).
3. **Read-back obligatorio**: `read` del header (`state`) + `search_read` de `kardex.import.line`
   por `log_id` (`sync_state`, `sync_error_message`, `linked_document`). Un `create` OK no significa
   movimientos creados.
4. `action_create_operations` (crea órdenes/pickings/facturas reales; NO atómico; idempotente) es
   **opcional**: NUNCA en pruebas/demo; en producción solo si la misión lo pide. Tras llamarlo,
   SIEMPRE relee (devuelve `false` aun con errores por línea).

Errores comunes del create (corrígelos en el payload): R1/"mandatory field" (falta el nombre
derivado o id+name juntos), #7 (total con precio sin redondear), #8 (moneda ≠ instrumento), #4 (slot
ya cargado → recupera el id, no es fallo), #12.2–12.5 (admin/cuenta/107/serie no cuadran).

## Paso 4 — Notificar resultado

Compón el informe (no lo envías tú: lo devuelves al COORD, que lo entrega por el canal
configurado — ver `cerrar-y-notificar-sesion`). Resume: líneas
cargadas (`log_id`), excluidas por diseño (destinos 2/4) y por qué, en error, pendientes resueltos,
fees. Referencia registros por `log_id` + modelo `kardex.import.log` (no construyas URL; NUNCA uses
`.name`). `lineas_error > 0` → estado `IMPORTADA_PARCIAL`, nunca completa.

## Salida (un resultado al COORD)

```json
{
  "resultado_carga": {"log_id": 91, "lineas_ok": 14,
    "lineas_error": [{"clave_idempotencia": "42-12345-2025-12-mov-3", "motivo": "..."}],
    "ids_odoo": [501,502], "clave_slot": "42-12345-2025-12"},
  "carga_completa": true,
  "informe": "Importación <custodio> — Cuenta <cuenta> — Período <período> ..."
}
```

## Nunca

- No reintentes ciegamente un rechazo de negocio sin pasar por `administrar-casos-de-borde-carga`.
- No crees maestros (`product.product`, `res.partner`) — alcance exclusivo de casos-de-borde con
  confirmación humana.
- No reportes carga parcial como completa.
