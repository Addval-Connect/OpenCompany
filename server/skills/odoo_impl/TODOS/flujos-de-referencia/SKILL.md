---
name: flujos-de-referencia
description: >-
  Índice de los paquetes de referencia por flujo funcional (ventas, compras, inventario, fabricacion,
  contabilidad, l10n-cl): alcance, módulos, objetos de configuración y de carga, reglas de validación
  y casos canónicos de QA. Carga esta skill y lee solo el flujo del proyecto con read_resource.
metadata:
  agente: TODOS
  tipo: DET
  prioridad: P1
  uso: referencia_compartida
  icon: "📚"
  author: addval
  version: "1.0"
  category: odoo_impl
---

# Flujos de referencia

Lo que cambia entre ventas, compras, inventario, fabricación y contabilidad son los **datos**: qué
objetos, en qué orden, con qué campos, qué validar y qué probar. Eso vive acá como referencias, no
como skills separadas — agregar un flujo nuevo es agregar un archivo.

**No leas todos.** Cargas esta skill y luego abres con `read_resource` **solo** los flujos que el
`blueprint.yaml` declara en `proyecto.flujos`, más `l10n-cl.md` si el país es CL. Leer los seis
infla el contexto de cada iteración sin aportar nada.

## Recursos disponibles

| Recurso | Contenido |
|---|---|
| `references/ventas.md` | Cotización → orden → entrega → factura. Listas de precios, equipos, condiciones. |
| `references/compras.md` | Solicitud → orden de compra → recepción → factura de proveedor. |
| `references/inventario.md` | Bodegas, ubicaciones, rutas, reglas, ajustes, saldos iniciales. |
| `references/fabricacion.md` | Centros de trabajo, operaciones, BoM multinivel, órdenes de producción. |
| `references/contabilidad.md` | Plan de cuentas, impuestos, diarios, posiciones fiscales, apertura. |
| `references/l10n-cl.md` | Localización chilena. **Transversal: se instala y configura antes de cargar partners y productos.** |
| `references/_plantilla-flujo.md` | Plantilla de 7 secciones para documentar un flujo nuevo. |

Cada archivo tiene la misma estructura de 7 secciones: alcance del flujo, módulos requeridos, objetos
de configuración, objetos de carga (campos mínimos + trampas), reglas de validación propias, casos
canónicos de QA, y preguntas para el cliente.

## Cómo se usan en cada etapa

- **A1 (brechas + introspección):** la sección de módulos requeridos dice qué verificar como
  instalado; las preguntas al cliente alimentan `01-analisis/preguntas-abiertas.md`.
- **A2 (blueprint + backlog):** los objetos de configuración y de carga son el punto de partida de
  `objetos:` en el `blueprint.yaml`, con su `fuente` y su `depende_de`.
- **A3 (plantillas):** los campos mínimos y las trampas son las columnas obligatorias y las
  advertencias del `INSTRUCTIVO.md`.
- **A4 (validación):** las reglas propias del flujo son validaciones adicionales a las genéricas de
  formato y referencia.
- **A5 (carga + QA):** los casos canónicos son la base de `09-qa/casos.yaml`.

## `l10n-cl` es distinto

No es un flujo paralelo: es transversal y **anterior**. Se instala y configura antes de cargar
partners y productos, porque `res.partner` gana `vat` (RUT con dígito verificador), tipo de
contribuyente, giro, actividad económica y comuna — y la comuna es una **entidad**, no texto libre.
Cada tipo de documento electrónico necesita su diario, y los folios CAF deben estar cargados o el QA
falla con un error que no parece de configuración. Toda la implementación corre en **certificación**
del SII, nunca en producción del SII hasta el cierre formal.

## Autoridad

Ningún listado de campos de estas referencias es autoridad. La autoridad es
`02-instancia/introspeccion.json`, generado con `fields_get` contra la instancia real. Todo lo
marcado `[VERIFICAR]` se confirma antes de usarse; una plantilla generada contra un Odoo imaginado se
cae en la carga.
