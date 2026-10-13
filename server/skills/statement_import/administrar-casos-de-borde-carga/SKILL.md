---
name: "administrar-casos-de-borde-carga"
description: "Diagnostica y propone; no decide ni escribe maestros (crear un producto/serie es decisión de"
metadata:
  author: opencompany
  version: "1.0"
  category: "statement_import"

---

# Administrar casos de borde de carga

Diagnostica y propone; **no decide ni escribe maestros** (crear un producto/serie es decisión de
negocio del equipo Tax). Todas las lecturas de diagnóstico son `search_read` (solo lectura) por la
tool `odoo_jsonrpc`.

Entrada (`fileRead`): las `lineas_error` del `context` (resultado de la pre-validación o inserción de
`importa-a-odoo`). Salida: propuesta al workspace (`fileModify`) + pendientes al COORD.

## Clasificar cada rechazo (confírmalo con `search_read`)

| Categoría | Error Odoo | Diagnóstico / acción |
|---|---|---|
| Payload mal construido | R1 / "mandatory field" | Falta `financial_instrument_name` derivado del `default_code`, o `id`+nombre no van juntos → NO es maestro faltante; devuelve a `importa-a-odoo` (paso construir payload). |
| Instrumento inexistente | R1 | Producto no existe para (admin, cuenta) o `default_code` no casa. Verifica con `product.product`; si falta de verdad, propuesta de alta. |
| Admin/cuenta/107/serie no cuadran | #12.2–12.5 | `administrator_id`≠custodio, `account_number`≠account, `article_107_flag` mal derivado, o `series` distinta. Corrige el payload leyendo el producto. |
| Moneda no coincide | #8 | `currency_id`≠`investment_currency_id` del producto. |
| Sin tipo de cambio | R2 | Falta `res.currency.rate` cubriendo `operation_date` y la línea no trae `exchange_rate_manual` (P-07). |
| Período cerrado | — | `operation_date` en período contable cerrado; no se resuelve reintentando, requiere decisión contable. |
| Otro | — | Cualquier rechazo no cubierto; descríbelo con el mensaje literal de Odoo. |

## Procedimiento

1. Por línea en error, clasifica con la tabla y confirma con `search_read` contra los maestros.
2. Redacta una propuesta específica por categoría (p.ej. "definir `res.currency.rate` de USD al
   DD/MM" o "corregir serie a 'B' en el payload"), **sin ejecutarla**.
3. Devuélvelas al COORD como pendientes accionables (mismo formato de lote). El COORD las surfacea al
   equipo Tax por chat; esta skill no habla con el usuario.
4. Solo tras reasignación con confirmación explícita en el `context`, reintenta **solo las líneas
   afectadas** (no el lote completo; la idempotencia por clave lo protege igual).

## Salida

```json
{
  "casos_de_borde_path": "payload/2025-12-casos-borde.json",
  "casos_de_borde": [{
    "clave_idempotencia": "42-12345-2025-12-mov-3",
    "categoria": "serie_no_cuadra",
    "propuesta_resolucion": "El producto 'FONDO XYZ' tiene serie 'B' en Odoo; el payload envía 'A'. Corregir a 'B'.",
    "estado": "pendiente_confirmacion"
  }]
}
```

## Casos de borde

- **El mismo motivo se repite en muchas líneas/cartolas del mismo custodio**: es un problema
  estructural de configuración de Odoo, no de esta cartola. Repórtalo como tal para que
  `importa-a-odoo` (paso notificar) lo eleve y se resuelva una vez a nivel de maestro.
