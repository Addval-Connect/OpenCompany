# Flujo: inventario

> Esqueleto. Completar siguiendo `_plantilla-flujo.md`.

## 1. Alcance funcional

Estructura de bodegas y ubicaciones, movimientos internos, ajustes de inventario,
trazabilidad y valorización. Es el flujo que más condiciona a los demás: ventas y
compras heredan sus tipos de operación.

## 2. Módulos requeridos

`stock`. `stock_landed_costs` si hay importaciones. Trazabilidad por lote/serie
requiere activarla explícitamente por producto.

## 3. Objetos de configuración

- Cantidad de bodegas y su relación (¿se abastecen entre sí?).
- Ubicaciones internas: nivel de detalle. Sobredimensionar la estructura de
  ubicaciones es un error caro y difícil de revertir.
- Pasos de recepción y entrega.
- Método de valorización y de costeo: estándar, promedio, FIFO. Decisión contable,
  no logística, y hay que tomarla con el contador del cliente.
- Trazabilidad: sin seguimiento, por lote, por número de serie.

## 4. Objetos de carga

| NN | Modelo | Campos mínimos | Trampas |
|----|--------|----------------|---------|
| 40 | `stock.warehouse` | `id, name, code` | El código de bodega aparece en los nombres de tipos de operación; cambiarlo después es sucio |
| 42 | `stock.location` | `id, name, location_id/id, usage` | Odoo ya creó ubicaciones al crear la bodega: introspección antes de cargar |
| 44 | `stock.picking.type` | `id, name, code, warehouse_id/id, sequence_code` | [COMPLETAR] |
| 80 | `stock.quant` | `id, product_id/id, location_id/id, inventory_quantity` | Los saldos iniciales tienen fecha de corte propia; no cargarlos con el resto |

## 5. Reglas de validación propias

- [COMPLETAR] Producto con saldo inicial debe ser de tipo almacenable.
- Ubicación de destino de tipo interno para saldos iniciales.
- [COMPLETAR] Productos con trazabilidad requieren lote o serie en el saldo inicial.

## 6. Casos de QA canónicos

1. Ajuste de inventario y verificación del asiento de valorización.
2. Transferencia interna entre ubicaciones.
3. [COMPLETAR] Recepción con lote y su trazabilidad hasta la entrega.
4. Valorización: comparar el informe de inventario contra la cuenta contable.

## 7. Preguntas al cliente

- ¿Cuántas bodegas físicas y cómo se relacionan?
- ¿Necesita ubicaciones a nivel de estantería o basta la bodega?
- ¿Trazabilidad por lote o serie? ¿En qué productos?
- ¿Valorización automática o manual? ¿Qué método de costeo?
- ¿Fecha de corte para saldos iniciales?
