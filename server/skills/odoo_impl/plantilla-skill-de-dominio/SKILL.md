---
name: plantilla-skill-de-dominio
description: Estructura canónica de un skill de dominio flujos/<flujo> — guía para escribir los cuatro skills de dominio; no la carga ningún agente.
allowed-tools: odoo_jsonrpc
metadata:
  author: opencompany
  version: "1.0"
  category: flujos

---

# Plantilla de skill de dominio: `flujos/<flujo>`

Cada flujo (`financiero`, `ventas_servicios`, `compras_aprobaciones`, `inventario_fabricacion`) tiene **un** skill de dominio con esta estructura. Los skills de procedimiento (`flujo-entendimiento`, `flujo-configuracion`, `flujo-implementacion`, `introspeccion-odoo-solo-lectura`) le piden exactamente estas secciones por nombre; si falta una, el agente no la inventa: escribe una definición abierta. Es **conocimiento**, no procedimiento: no repitas aquí cómo se hace una misión.

**Regla de procedencia.** Todo hecho de Odoo (nombre de campo, clave de `selection`, xmlid, comportamiento de una versión) lleva su estado: `[verificado: <instancia>, <fecha>]` o `[hipótesis]`. Una hipótesis se confirma con `fields_get` antes de usarla y nunca se escribe como dato. `fields_get` sigue siendo la única autoridad.

## 1. Alcance y sub-alcance

Qué cubre el flujo, cuáles son sus sub-alcances declarables (por ejemplo, para `financiero`: contabilidad, tesorería, facturación) y qué queda explícitamente fuera.

## 2. Mapa de modelos

Una fila por modelo. Esta tabla es la **fuente de las opciones de `modelo_principal`** en JEV (hasta 255), y del `depende_de` típico.

| Modelo | Descripción en una línea (apta para JEV) | Dueño por defecto | ¿Ancla? | Fuente típica | `depende_de` típico | Módulo requerido |
|---|---|---|---|---|---|---|

## 3. Preguntas de indagación mínimas (G1)

Una por decisión de dominio. Cada una con el formato del contrato, para que el agente la copie al cuestionario:

- **Pregunta** cerrada.
- **Opciones** sin sugerir una.
- **Propuesta por defecto**, con el motivo.
- **Qué se rompe si se supone** (una línea).
- **Cuándo es `BLOQUEANTE`**.

## 4. Decisiones de diseño (G2)

Lo que se decide al aprobar el diseño y que depende del dominio: qué objetos son `configuracion`, cuáles son `plantilla` y cuáles `derivado` en este flujo, y por qué. Incluye los objetos `ancla` si el flujo es `financiero`.

## 5. Columnas y dueños típicos por plantilla

Por cada plantilla habitual: columnas obligatorias, quién suele llenarlas (rol del cliente, no persona) y las columnas que otro flujo suele pedir (`requiere_de` frecuente).

## 6. Casos canónicos de QA

Casos que acompañan a este flujo en cualquier proyecto, en el formato de `casos.yaml` del contrato: pasos y aserciones. Cada uno con el criterio de negocio que protege.

## 7. Particularidades de localización

Lo que cambia por país o localización instalada (Chile: RUT y dígito verificador, documentos tributarios, folios, impuestos). Marca qué validaciones aplica la instancia y cuáles no: el validador solo rechaza lo que Odoo rechaza.

## 8. Trampas conocidas

Tabla: qué se espera, qué pasa realmente, cómo se detecta, procedencia. Es el lugar de las tablas de "campos que cambiaron entre versiones". Cada fila con su procedencia (regla de arriba).

## 9. Preguntas de otros flujos que este flujo debe poder responder

Qué suele pedirle cada flujo a este (`requiere_de` frecuente) y cómo se responde, para que `cruzar requiere_de` no empiece de cero.
