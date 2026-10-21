---
name: odoo19-diferencias
description: Nombres de campo y claves de selection que cambiaron en Odoo 19 — hipótesis de trabajo; fields_get es la única autoridad.
allowed-tools: odoo_jsonrpc
metadata:
  author: addval
  version: "1.0"
  category: odoo_migracion

---

# Odoo 19: diferencias observadas

Nombres de campo y claves de `selection` que han fallado en proyectos anteriores por haber cambiado entre versiones. **Todo lo de este skill es una hipótesis de trabajo**, no una autoridad: viene de errores observados en proyectos previos, sin fecha ni instancia registradas. `fields_get` sobre la instancia real sigue siendo la única autoridad (`odoo-rpc-transporte`). Úsalo para saber **dónde mirar primero**, no para escribir un nombre sin verificarlo.

## Cómo se usa

1. Un `Invalid field` (`E110`) o un valor rechazado (`E220`): mira si el caso aparece abajo, y confirma con `fields_get` antes de usar el nombre sugerido.
2. Lo que `fields_get` confirme en tu instancia se registra en `08-carga/capacidades-instancia.json` con fecha (CARGA) o en la introspección del flujo. **Si la instancia contradice una fila de este skill, gana la instancia** y la fila se corrige aquí.
3. Una fila nunca se aplica "por si acaso": cada una lleva su procedencia.

## Campos que no están donde se espera

Procedencia de toda la tabla: `[observado en proyecto, sin fecha; verificar con fields_get]`.

| Querías | Dónde NO está | Dónde se observó |
|---|---|---|
| Código ISO de una moneda (`USD`) | `res.currency.code` | `res.currency.name`, y el valor es `USD`, no `US` |
| Zona horaria de la compañía | `res.company.tz` | `res.partner.tz` / `res.users.tz` (vía `company.partner_id`) |
| Grupos de un usuario | `res.users.groups_id` | `res.users.group_ids` |
| Compañía de una cuenta contable | `account.account.company_id` | `account.account.company_ids` (m2m) |
| Tipo de contribuyente chileno | `res.partner.l10n_cl_taxpayer_type` | `res.partner.l10n_cl_sii_taxpayer_type` |
| Condición de pago de un contacto | `res.partner.payment_term_id` | `property_payment_term_id` / `property_supplier_payment_term_id` |
| Etiquetas de un contacto | `res.partner.category_ids` | `res.partner.category_id` (m2m, en singular) |
| Aplicabilidad de un plan analítico | `account.analytic.plan.applicability` | `default_applicability` |
| UdM de compra de un producto | `product.template.uom_po_id` | no observado en 19; la UdM aparece como `uom_id` / `uom_ids` |
| Modelo de depreciación | modelo `account.asset.model` | modelo `account.asset` con `state='model'` |
| Cuentas de entrada/salida de stock | `product.category.property_stock_account_input_categ_id` | no observadas en 19; queda `property_stock_valuation_account_id` |

**El patrón detrás de varias filas:** en Odoo la compañía delega sus datos de contacto en `partner_id`, y varios "códigos" viven en `name`. Cuando un campo obvio no existe, pregúntate **qué modelo es el dueño real del dato** antes de probar otro nombre. Y nunca pruebes un segundo nombre a ojo: haz el `fields_get`.

## Claves de `selection`

Procedencia: `[observado en proyecto, sin fecha; verificar con fields_get]`. Cargar siempre la **clave técnica**, no la etiqueta traducida.

| Modelo.campo | Claves observadas | Nota |
|---|---|---|
| `product.template.type` | `consu`, `service`, `combo` | `product` no se observó; almacenable = `consu` + `is_storable` |
| `product.category.property_valuation` | `periodic`, `real_time` | `manual` se observó como `periodic` |
| `stock.warehouse.delivery_steps` | `ship_only`, `pick_ship`, `pick_pack_ship` | `one_step` se observó como `ship_only`; `reception_steps` **sí** usa `one_step`: las claves de entrada y salida no son simétricas |
| `res.partner.type` | `contact`, `invoice`, `delivery`, `other` | no confundir con `l10n_cl_sii_taxpayer_type` (`1` a `4`) |
| `account.asset.method_period` | `1`, `12` | son strings |

## Qué hacer con una fila desactualizada

Si `fields_get` contradice una fila, no la dejes "por si acaso": corrígela con la fecha y la instancia verificada, o bórrala. Una hipótesis envejecida que nadie revisa es peor que ninguna.

## Nunca

- Escribir un campo de esta tabla en un payload sin haberlo visto en `fields_get`.
- Dar una fila por vigente porque "ya funcionó antes".
- Copiar aquí un hecho de **una** instancia como si fuera de la versión: eso va a `capacidades-instancia.json`.
