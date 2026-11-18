---
name: odoo19-diferencias
description: Nombres de campo y claves de selection que cambiaron entre Odoo 17, 18 y 19 — hipótesis de trabajo; fields_get es la única autoridad.
allowed-tools: odoo_jsonrpc
metadata:
  author: opencompany
  version: "2.0"
  category: compartidos

---

# Diferencias entre Odoo 17, 18 y 19

Nombres de campo y claves de `selection` que han fallado en proyectos anteriores por haber cambiado entre versiones. **Todo lo de este skill es una hipótesis de trabajo**, no una autoridad: dice **dónde mirar primero** y en qué versión, no qué escribir. `fields_get` sobre la instancia real sigue siendo la única autoridad (`odoo-rpc-transporte`).

## Procedencia

Las filas de abajo se verificaron con `fields_get` el **2026-11-17** sobre tres instancias locales (`odoo:17.0`, `18.0` y `19.0`, community), todas con el mismo set de módulos instalados: `base`, `l10n_cl`, `account`, `stock`, `stock_account`, `sale_management`, `purchase`, `mrp`. La columna **Versión** dice dónde se observó cada fila, no dónde "debería" estar.

Dos advertencias que salieron de esa verificación:

- **La ausencia de un campo puede ser ausencia de módulo.** Un `--` en `fields_get` no prueba que el campo no exista en esa versión: el campo viaja con el módulo que lo define. Antes de concluir que un campo desapareció, revisa el `state` del módulo en `ir.module.module` (en una instancia 18 sin `stock`, `product.category.property_valuation` sale ausente aunque exista en 18).
- **Una fila de este skill nunca se copia a un payload sin `fields_get` previo.** La versión sólo prioriza la búsqueda.

## Cómo se usa

1. Un `Invalid field` (`E110`) o un valor rechazado (`E220`): busca el caso abajo, filtra por la versión de la instancia, y confirma con `fields_get` antes de usar el nombre sugerido.
2. Lo que `fields_get` confirme en tu instancia se registra en `08-carga/capacidades-instancia.json` con fecha (CARGA) o en la introspección del flujo. **Si la instancia contradice una fila de este skill, gana la instancia** y la fila se corrige aquí.
3. Una fila nunca se aplica "por si acaso": cada una lleva su procedencia y su versión.

## Campos que no están donde se espera

| Querías | Dónde está | Dónde NO está | Versión |
|---|---|---|---|
| Código ISO de una moneda (`USD`) | `res.currency.name` (el valor es `USD`, no `US`) | `res.currency.code` | 17 · 18 · 19 |
| Zona horaria de la compañía | `res.company.tz` (19); `company.partner_id.tz` (17 y 18) | — en 19 es campo propio de la compañía | **19 introduce `res.company.tz`** |
| Grupos de un usuario | `res.users.group_ids` (19); `res.users.groups_id` (17 y 18) | el otro nombre, según la versión | **cambio en 19** |
| Compañía de una cuenta contable | `account.account.company_ids` (m2m, 18 y 19); `company_id` (m2o, 17) | el otro nombre, según la versión | **cambio en 18** |
| Tipo de contribuyente chileno | `res.partner.l10n_cl_sii_taxpayer_type` | `res.partner.l10n_cl_taxpayer_type` | 17 · 18 · 19 (nombre de `l10n_cl`, no de versión) |
| Condición de pago de un contacto | `property_payment_term_id` / `property_supplier_payment_term_id` | `res.partner.payment_term_id` | 17 · 18 · 19 |
| Etiquetas de un contacto | `res.partner.category_id` (m2m, en singular) | `res.partner.category_ids` | 17 · 18 · 19 |
| Aplicabilidad de un plan analítico | `account.analytic.plan.default_applicability` | `account.analytic.plan.applicability` | 17 · 18 · 19 |
| UdM de compra de un producto | `product.template.uom_id` / `uom_ids` (19); `uom_po_id` (17 y 18) | `uom_po_id` ya no existe en 19 | **cambio en 19** |
| Cuentas de entrada/salida de stock | `product.category.property_stock_valuation_account_id` (19); también `property_stock_account_input_categ_id` en 17 y 18 | `property_stock_account_input_categ_id` ya no existe en 19 | **cambio en 19** |
| Modelo de depreciación | `account.asset` con `state='model'` | modelo `account.asset.model` | **no verificable**: `account.asset` no existe en community 17/18/19 |

**El patrón detrás de varias filas:** en Odoo la compañía delega sus datos de contacto en `partner_id`, y varios "códigos" viven en `name`. Cuando un campo obvio no existe, pregúntate **qué modelo es el dueño real del dato** antes de probar otro nombre. Y nunca pruebes un segundo nombre a ojo: haz el `fields_get`.

## Claves de `selection`

Cargar siempre la **clave técnica**, no la etiqueta traducida.

| Modelo.campo | Claves observadas | Nota | Versión |
|---|---|---|---|
| `product.template.type` | `consu`, `service`, `combo` | en 17 la clave es `product`; en 18 pasa a `consu` (+ `is_storable`) y aparece `combo` | **cambio en 18** (`product` en 17) |
| `product.category.property_valuation` | `periodic`, `real_time` | en 17 y 18 la clave es `manual_periodic`; `manual` no es clave en ninguna versión | **cambio en 19** (`manual_periodic` en 17 y 18) |
| `stock.warehouse.delivery_steps` | `ship_only`, `pick_ship`, `pick_pack_ship` | no existe `one_step` acá; `reception_steps` **sí** usa `one_step`: las claves de entrada y salida no son simétricas | 17 · 18 · 19 |
| `res.partner.type` | `contact`, `invoice`, `delivery`, `other` | no confundir con `l10n_cl_sii_taxpayer_type` (`1` a `4`) | 17 · 18 · 19 |
| `account.asset.method_period` | `1`, `12` | son strings | **no verificable**: `account.asset` no existe en community |

## Qué hacer con una fila desactualizada

Si `fields_get` contradice una fila, no la dejes "por si acaso": corrígela con la fecha, la versión y la instancia verificada, o bórrala. Una hipótesis envejecida que nadie revisa es peor que ninguna.

## Nunca

- Escribir un campo de esta tabla en un payload sin haberlo visto en `fields_get`.
- Dar una fila por vigente porque "ya funcionó antes" o porque la instancia es más nueva.
- Concluir que un campo no existe en una versión porque falta en una instancia: puede faltar el **módulo**.
- Copiar aquí un hecho de **una** instancia como si fuera de la versión: eso va a `capacidades-instancia.json`.
