# Flujo: fabricación

> Esqueleto. Completar siguiendo `_plantilla-flujo.md`.

## 1. Alcance funcional

Listas de materiales, órdenes de fabricación, centros de trabajo y órdenes de
trabajo. Depende por completo de que inventario esté configurado antes.

## 2. Módulos requeridos

`mrp`. `mrp_workorder` para órdenes de trabajo y taller. `mrp_subcontracting` si hay
maquila.

## 3. Objetos de configuración

- Pasos de fabricación: 1, 2 o 3.
- ¿Se usan órdenes de trabajo o solo órdenes de fabricación?
- Reglas de abastecimiento: fabricar contra pedido o contra stock.
- Subcontratación.

## 4. Objetos de carga

| NN | Modelo | Campos mínimos | Trampas |
|----|--------|----------------|---------|
| 60 | `mrp.workcenter` | `id, name, resource_calendar_id/id, costs_hour` | [COMPLETAR] |
| 64 | `mrp.bom` | `id, product_tmpl_id/id, product_qty, type` | `type` distingue LdM normal de kit; un kit mal marcado cambia el comportamiento de stock por completo |
| 65 | `mrp.bom.line` | `id, bom_id/id, product_id/id, product_qty` | LdM multinivel: cargar subensambles antes que el producto terminado |

## 5. Reglas de validación propias

- Sin ciclos en las LdM multinivel. Un componente no puede contener a su padre.
- [COMPLETAR] Todo componente existe como producto y es de tipo almacenable o
  consumible.
- Unidad de medida del componente compatible con la del producto.
- [COMPLETAR] Producto fabricable con ruta de fabricación asignada.

## 6. Casos de QA canónicos

1. OF de producto de un nivel: confirmar, consumir componentes, producir. Aserciones
   sobre movimientos de stock y valorización.
2. [COMPLETAR] OF multinivel con subensambles.
3. Fabricación contra pedido disparada desde una venta.
4. [COMPLETAR] Desperdicio y su impacto contable.

## 7. Preguntas al cliente

- ¿Cuántos niveles tienen sus productos?
- ¿Registra tiempos por centro de trabajo?
- ¿Fabrica contra stock o contra pedido?
- ¿Hay procesos subcontratados?
- ¿Las LdM cambian por variante del producto?
