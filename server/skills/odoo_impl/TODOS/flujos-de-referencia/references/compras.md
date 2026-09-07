# Flujo: compras

> Esqueleto. Completar siguiendo `_plantilla-flujo.md` y el nivel de detalle de
> `ventas.md`.

## 1. Alcance funcional

Solicitud de cotización → orden de compra → recepción → factura de proveedor → pago.
Incluye reglas de reabastecimiento si el discovery las levanta.

## 2. Módulos requeridos

`purchase`, `stock`, `account`. Recepción de DTE de proveedores vía `l10n_cl_edi`.

## 3. Objetos de configuración

- Política de control de facturas: por cantidades pedidas o recibidas.
- Pasos de recepción: 1, 2 o 3.
- Acuerdos de compra / licitaciones, si aplica.
- Aprobaciones por monto.

## 4. Objetos de carga

| NN | Modelo | Campos mínimos | Trampas |
|----|--------|----------------|---------|
| 20 | `res.partner` (proveedores) | `id, name, vat, supplier_rank` | Un mismo RUT que es cliente y proveedor es **un** partner, no dos |
| 35 | `product.supplierinfo` | `id, partner_id/id, product_tmpl_id/id, price, min_qty, delay` | Varios proveedores por producto: el orden define la prioridad |
| — | reglas de reabastecimiento | `orderpoint` | [COMPLETAR] |

## 5. Reglas de validación propias

- [COMPLETAR] Producto comprable con proveedor y precio de compra.
- [COMPLETAR] Impuesto de compra asignado.
- Plazo de entrega coherente con las reglas de reabastecimiento.

## 6. Casos de QA canónicos

1. Compra simple: OC → recepción → factura de proveedor → pago.
2. Recepción parcial con backorder.
3. Devolución a proveedor con nota de crédito.
4. [COMPLETAR] Reabastecimiento automático disparando OC.

## 7. Preguntas al cliente

- ¿Se controla la factura contra lo pedido o lo recibido?
- ¿Hay aprobación de órdenes de compra? ¿Por qué monto?
- ¿Importaciones con costos en destino (landed costs)?
