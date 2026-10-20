# Flujo: ventas

## 1. Alcance funcional

Cotización → orden de venta → entrega → factura → cobro. Incluye catálogo comercial,
listas de precios, condiciones de pago y política de facturación. No incluye CRM
(pipeline de oportunidades) salvo que el discovery lo levante explícitamente.

## 2. Módulos requeridos

| Módulo | Para qué |
|--------|----------|
| `sale_management` | Cotizaciones y órdenes de venta |
| `stock` | Entregas |
| `account` | Facturación |
| `l10n_cl_edi` | Facturación electrónica chilena — ver `l10n-cl.md` |

## 3. Objetos de configuración

- Política de facturación por defecto: cantidades pedidas vs. entregadas. Decisión de
  negocio, no técnica, y cambia el flujo completo de facturación parcial.
- Pasos de entrega: 1, 2 o 3. Afecta tipos de operación y el QA.
- Equipos de venta y asignación por defecto.
- Plantillas de cotización, si el cliente las usa.
- Términos de pago.

## 4. Objetos de carga

| NN | Modelo | Campos mínimos | Trampas |
|----|--------|----------------|---------|
| 20 | `res.partner` | `id, name, vat, l10n_cl_sii_taxpayer_type` [VERIFICAR] | Clientes con sucursales: cada dirección de entrega es un contacto hijo, no un partner nuevo |
| 27 | `product.category` | `id, name, parent_id/id` | Si hay valorización automática, la categoría arrastra cuentas contables: definirlas antes de cargar productos |
| 31 | `product.template` | `id, name, default_code, type, categ_id/id, uom_id/id, list_price, taxes_id/id` | `type` mal puesto (servicio vs. almacenable) obliga a rehacer productos y rompe el QA de stock |
| 50 | `product.pricelist` | `id, name, currency_id/id` | — |
| 51 | `product.pricelist.item` | `id, pricelist_id/id, applied_on, product_tmpl_id/id, compute_price, fixed_price` | El campo que aplica la regla depende de `applied_on`; una fila con `applied_on` de categoría y producto lleno es ambigua |

## 5. Reglas de validación propias

- Todo producto vendible tiene impuesto de venta asignado. Sin impuesto, la factura
  sale sin IVA y el error aparece recién en contabilidad.
- `default_code` único. Es la clave natural del xmlid; si se repite, dos productos
  distintos colisionan.
- Cliente con `l10n_cl_sii_taxpayer_type` coherente con el tipo de documento que se
  le va a emitir.
- Precio de lista mayor a cero salvo que el producto sea explícitamente gratuito.

## 6. Casos de QA canónicos

1. **Venta simple**: cotización a cliente con lista estándar → confirmar → validar
   entrega → facturar → registrar pago. Aserciones: estado `sale`, un `stock.picking`
   en `done`, `account.move` en `posted`, saldo del cliente en cero.
2. **Venta con lista de precios**: mismo recorrido con cliente mayorista. Aserción
   sobre el precio unitario aplicado, no solo sobre el total.
3. **Entrega parcial**: confirmar 10, entregar 6, facturar. Aserciones sobre backorder
   creado y cantidad facturada.
4. **Nota de crédito**: sobre factura emitida. En Chile requiere tipo de documento y
   referencia al documento original — ver `l10n-cl.md`.

## 7. Preguntas al cliente

- ¿Se factura por lo pedido o por lo entregado?
- ¿Cuántos pasos de entrega tiene la bodega?
- ¿Hay descuentos por línea, por cliente, por volumen? ¿Quién los autoriza?
- ¿Hay aprobación de cotizaciones por monto o por margen?
- ¿Los precios se manejan con IVA incluido o neto?
