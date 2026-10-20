---
name: catalogo-de-flujos
description: Índice ligero de los cuatro flujos para D0 — alcance, sub-alcances y fronteras; se regenera desde los skills de dominio.
allowed-tools: odoo_jsonrpc
metadata:
  author: opencompany
  version: "1.0"
  category: d0

---

# Catálogo de flujos

Índice ligero de los cuatro flujos para D0: qué cubre cada uno, sus sub-alcances y dónde están las fronteras. **No es el conocimiento de dominio**: ese vive en `flujo-<flujo>`. Este catálogo se regenera desde la sección 1 ("Alcance y sub-alcance") de cada skill de dominio cuando esos skills existan; hasta entonces es una versión inicial. Lo marcado `[por confirmar]` es una decisión por defecto que el dueño del proyecto debe validar.

## Los cuatro flujos

| `flujo` | Agente | Sub-alcances (`sub_alcance`) | Qué tipo de historia va aquí |
|---|---|---|---|
| `financiero` | Flujo Financiero | `contabilidad`, `tesoreria`, `facturacion` | Plan de cuentas, impuestos, diarios, posiciones fiscales, monedas, cierres; bancos, pagos, conciliación; emisión y contabilización de documentos tributarios y facturas |
| `ventas_servicios` | Flujo de Ventas y Servicios | `ventas`, `servicios` | Cotizaciones, listas de precios, pedidos de venta, contratos, servicios facturables, la política de cuándo se factura |
| `compras_aprobaciones` | Flujo de Compras y Aprobaciones | `compras`, `aprobaciones` | Solicitudes y órdenes de compra, proveedores, reglas y circuitos de aprobación |
| `inventario_fabricacion` | Flujo de Inventario y Fabricación | `inventario`, `fabricacion` | Bodegas, ubicaciones, stock, rutas, método de costeo, listas de materiales, órdenes de producción |

Un sub-alcance puede quedar fuera sin que el flujo entero lo esté (por ejemplo, un cliente sin fabricación). Se declara en `proyecto.yaml` → `sub_alcance`.

## Fronteras entre flujos

Una historia va al flujo de su **objetivo principal**. Cuando dos flujos tocan lo mismo, estas reglas desempatan:

| Caso frecuente | Va a | Por qué |
|---|---|---|
| La factura como documento contable: emisión, folios, contabilización | `financiero` | Es el documento tributario |
| La política de cuándo se factura un pedido o servicio (al pedido, a la entrega, por hito) | `ventas_servicios` | Es una regla del proceso comercial |
| Método de costeo y valorización del inventario | `inventario_fabricacion` | Es una decisión del inventario |
| Las **cuentas** contables de valorización de stock | `financiero` | Las cuentas son de contabilidad; el flujo de inventario las pide con `requiere_de` |
| Mecanismo de aprobación (reglas, umbrales, quién aprueba) | `compras_aprobaciones` `[por confirmar]` | Es dueño del mecanismo |
| La **regla de negocio** que dispara una aprobación (un umbral de margen en ventas) | el flujo donde nace la regla `[por confirmar]` | Cada flujo define su regla y pide el mecanismo con `requiere_de` |
| Impuestos aplicados a un producto o a una línea de pedido | `financiero` define el impuesto; el flujo que lo usa lo referencia | El impuesto es del ancla contable |
| Clientes y proveedores como contactos | `res.partner` tiene un único dueño `[por confirmar]` (propuesta: `ventas_servicios`); los demás flujos piden columnas con `requiere_de` | Un modelo, un dueño |
| Productos y unidades de medida | `inventario_fabricacion` `[por confirmar]` | Un modelo, un dueño |

**Si la confianza de JEV es baja justo en una de estas fronteras, es información útil:** va como pregunta al consultor, no como una asignación por defecto.

## Dueños de modelos compartidos (propuesta por defecto)

Se confirma con el consultor en las definiciones de proyecto (G0) y queda en `proyecto.yaml` → `duenos_modelos`.

| Modelo | Dueño propuesto |
|---|---|
| `res.partner` | `ventas_servicios` |
| `product.template`, `product.product`, `product.category`, `uom.*` | `inventario_fabricacion` |
| `account.*`, `res.company`, `res.currency` (núcleo contable) | `financiero` |

## El ancla contable

Todo proyecto tiene un ancla: el núcleo contable (compañía, localización, plan de cuentas, impuestos, diarios, posiciones fiscales, monedas), que cierra el flujo `financiero`. **Un proyecto sin historias financieras sigue necesitando el ancla**: el flujo financiero la verifica y la declara cumplida con evidencia. D0 lo menciona como pregunta cuando el material no trae nada de contabilidad.
