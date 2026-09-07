---
name: convencion-ids-externos
description: >-
  Convención de IDs externos (xmlid) que hace idempotente toda la carga a Odoo: formato, clave
  natural, cabeceras nativas del importador y referencias entre archivos. Lee esto antes de generar
  una plantilla, validar una columna id o cargar cualquier archivo.
metadata:
  agente: TODOS
  tipo: DET
  prioridad: P0
  uso: referencia_compartida
  icon: "🔑"
  author: addval
  version: "1.0"
  category: odoo_impl
---

# Convención de IDs externos

El ID externo (xmlid) es la única columna que convierte una carga destructiva en una carga
repetible. Con `id`, `load()` **actualiza** el registro existente; sin `id`, **duplica**. Todo el
proceso descansa en esto: si la columna falta o cambia entre corridas, la segunda carga ensucia la
base y no hay vuelta atrás salvo restaurar.

## Formato

```
<prefijo_proyecto>.<objeto_corto>_<clave_natural>
```

| Parte | Regla | Ejemplo |
|---|---|---|
| `prefijo_proyecto` | Fijo por proyecto, declarado en `blueprint.yaml` como `prefijo_xmlid`. Nunca `base`, nunca el nombre de un módulo de Odoo. | `adv_acme` |
| `objeto_corto` | Abreviatura estable del modelo (tabla abajo). | `partner` |
| `clave_natural` | Dato **inmutable** del registro, normalizado. NO un contador. | `761234567` |

Ejemplos válidos:

```
adv_acme.partner_761234567          res.partner (RUT sin puntos ni guion)
adv_acme.categ_insumos_metal        product.category (slug de la ruta)
adv_acme.prod_tmpl_perno_m8x40      product.template (slug del código interno)
adv_acme.tax_iva_19_venta           account.tax
adv_acme.journal_fact_electronica   account.journal
adv_acme.wh_santiago                stock.warehouse
adv_acme.bom_ensamble_puerta_v1     mrp.bom
```

## Por qué la clave natural y no un contador

`adv_acme.partner_001` parece más limpio y es la trampa más cara del proceso. El consultor reordena
las filas del CSV entre una corrida y la siguiente — ordena por nombre, inserta una fila arriba — y
`partner_001` pasa a apuntar a otra empresa. La segunda carga **renombra registros existentes** en
silencio: los movimientos, facturas y stock ya asociados siguen colgando del registro equivocado.
Con la clave natural (RUT, código interno, código de bodega) el xmlid viaja con el dato y el reorden
es inocuo.

Si no hay dato inmutable, se construye uno determinístico a partir de los campos que definen la
identidad del registro (ej. bodega + ubicación) — nunca a partir de la posición en el archivo.

## Normalización (obligatoria, sin excepciones)

- Solo `[a-z0-9_.]`. Minúsculas siempre.
- Sin acentos ni ñ: `categ_logistica`, no `categ_logística`.
- Espacios, guiones y `/` → `_`. Nunca dos `_` seguidos; nunca `_` al final.
- RUT chileno: sin puntos, sin guion, **con** dígito verificador → `76.123.456-7` → `761234567`.
  El DV es parte de la clave; omitirlo colisiona con otro RUT válido.
- Máximo razonable 60 caracteres; si el slug natural es más largo, córtalo por palabra completa.

Un xmlid se asigna **una vez y no se cambia jamás**. Cambiarlo no renombra: crea un registro nuevo y
deja huérfano al anterior. Si un xmlid quedó mal, la corrección es una tarea explícita del backlog
con confirmación humana, no una edición de plantilla.

## Abreviaturas por modelo

| Modelo | `objeto_corto` | Modelo | `objeto_corto` |
|---|---|---|---|
| `res.partner` | `partner` | `stock.warehouse` | `wh` |
| `res.partner.bank` | `partner_bank` | `stock.location` | `loc` |
| `res.company` | `company` | `stock.picking.type` | `picking_type` |
| `res.users` | `user` | `stock.route` | `route` |
| `account.account` | `account` | `stock.rule` | `rule` |
| `account.tax` | `tax` | `stock.putaway.rule` | `putaway` |
| `account.journal` | `journal` | `product.pricelist` | `pricelist` |
| `account.fiscal.position` | `fiscal_pos` | `product.pricelist.item` | `pricelist_item` |
| `account.payment.term` | `payment_term` | `crm.team` | `team` |
| `l10n_latam.document.type` | `doc_type` | `mrp.workcenter` | `workcenter` |
| `product.category` | `categ` | `mrp.routing.workcenter` | `op` |
| `product.template` | `prod_tmpl` | `mrp.bom` | `bom` |
| `product.product` | `prod` | `product.supplierinfo` | `supplierinfo` |
| `uom.uom` | `uom` | `product.attribute` | `attr` |
| `uom.category` | `uom_categ` | `product.attribute.value` | `attr_val` |

Modelo no listado → deriva la abreviatura quitando el prefijo del módulo y acortando la última
palabra (`account.analytic.account` → `analytic`), y **anótala acá** para que el resto del proyecto
use la misma.

## Cabeceras nativas del importador

Odoo interpreta el sufijo de la cabecera. Estas son las que se usan; no inventes otras.

| Cabecera | Significado | Ejemplo de celda |
|---|---|---|
| `id` | xmlid de **este** registro. Primera columna, siempre. | `adv_acme.partner_761234567` |
| `<campo>/id` | many2one por xmlid del destino | `categ_id/id` → `adv_acme.categ_insumos` |
| `<campo>/id` (many2many) | lista separada por comas | `taxes_id/id` → `adv_acme.tax_iva_19_venta,adv_acme.tax_esp` |
| `<campo>/.id` | many2one por **id numérico** de base de datos | evítalo: rompe la portabilidad entre entornos |
| `<sub>/<campo>` | one2many anidado: filas siguientes con `id` vacío pertenecen a la anterior | `seller_ids/partner_id/id` |
| `<campo>` | escalar (char, float, boolean, selection, date) | `name`, `list_price`, `active` |

Reglas de referencia:

- **Toda referencia entre archivos es por xmlid**, nunca por nombre ni por id numérico. Un `name`
  ambiguo empareja el registro equivocado sin error; un id numérico difiere entre staging y
  producción.
- Se puede referenciar un xmlid **nativo de Odoo** cuando el destino ya existe en la instancia
  (`base.CL`, `uom.product_uom_unit`, `l10n_cl.…`). El nombre exacto se confirma con la
  introspección, nunca de memoria — es el origen más frecuente del error `E300`.
- La celda vacía en un `<campo>/id` significa "sin valor", no "por defecto". Si el campo es
  obligatorio, es `E200`.
- Un one2many anidado ocupa varias filas: la primera trae el `id` del padre y las siguientes lo
  dejan vacío. Ordenar o filtrar ese CSV rompe la relación — el `INSTRUCTIVO.md` debe advertirlo.

## Selecciones y booleanos

- `selection`: se carga el **valor técnico**, no la etiqueta traducida (`out_invoice`, no "Factura de
  cliente"). El catálogo válido sale de `fields_get` y viaja en el `catalogos` del sidecar
  `.meta.json`.
- `boolean`: `1`/`0` o `True`/`False`. Vacío = falso. Un `boolean` como `"sí"` es `E210`.
- `date` / `datetime`: `YYYY-MM-DD` y `YYYY-MM-DD HH:MM:SS` en UTC. Cualquier otro formato es `E210`.

## Verificación antes de cargar

1. La columna `id` existe, es la primera y no tiene celdas vacías.
2. Todos los `id` del archivo son únicos (duplicado → `E310`).
3. Todos empiezan con el `prefijo_xmlid` del `blueprint.yaml`.
4. Todos cumplen `^[a-z0-9_]+\.[a-z0-9_]+$`.
5. Cada `<campo>/id` referenciado existe: en un archivo anterior del mismo lote, o en la instancia
   (`ir.model.data`, ver `odoo-rpc-en-opencompany`). Si no → `E300`.
6. Ningún archivo referencia un xmlid definido en un archivo con `NN` **mayor** al propio → `E320`.
