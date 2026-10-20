---
name: administrar-casos-de-borde-odoo
description: >-
  Qué hacer con un rechazo de Odoo que no es un error de dato — decidir si es un caso de borde
  propio, del bucle de corrección o del consultor, y recuperar el estado tras un lote fallido.
  Úsalo solo cuando la carga o el QA devuelven algo que el runbook de CARGA no cubre.
allowed-tools: odoo_jsonrpc file_read file_modify fs_search sandboxed_python javascript_code write_todos
metadata:
  agente: CARGA
  tipo: MIX
  prioridad: P1
  depende_de: carga-a-odoo-y-verifica
  siguiente_agente: Coordinador
  icon: "🩹"
  author: addval
  version: "2.0"
  category: odoo_impl
---

# Casos de borde de la carga

El flujo dueño ya validó estructura, formatos, catálogos y referencias antes de escribir. Un rechazo
que llega igual es una de tres cosas: una regla de negocio que solo Odoo conoce, un estado de la
instancia que cambió, o un defecto de diseño aguas arriba. Ninguna se arregla reintentando.

**Regla que gobierna esta skill:** un reintento ciego con el mismo payload gasta iteraciones y no
cambia el resultado. Antes de cualquier segundo intento, tiene que haber cambiado algo — el payload, el
estado de la instancia, o una decisión humana.

**La otra mitad de la regla: un caso de borde no termina la etapa.** Vienes desde el bucle de carga de
`carga-a-odoo-y-verifica` y **vuelves a él**. Un rechazo que necesita criterio humano se convierte en
un pendiente que se **acumula**, no en un `return` inmediato: apartas las filas o difieres el archivo,
anotas el pendiente, y sigues con el resto del plan. El control se devuelve **una vez**, al cerrar el
bucle, con todos los pendientes juntos.

Devolver el control en el primer `E400` deja 20 archivos sin cargar por dos filas, y obliga al
consultor a resolver los problemas de uno en uno: cada respuesta destapa el siguiente rechazo, y una
carga que era una corrida se convierte en diez. La única excepción son las tres cosas que hacen que
seguir sea peligroso, no solo inútil: `E500` (instancia), colisión de prefijo xmlid y falta de
confirmación para escribir en producción.

## Dónde vive cada cosa — no repitas el bucle

| Necesidad | Está en |
|---|---|
| Clasificar un mensaje por su **texto** (la tabla "el mensaje dice → es") | `taxonomia-errores-odoo` — la definición única de los códigos |
| Reintentos, `E110`, `E220`, "ya existe", `E400` regla de negocio, `E500`, el bucle de rondas | `bucle-de-correccion` |
| Un `E300` sobre un xmlid `l10n_*` de la localización (`l10n_cl.tax_vat_19_sale` no existe; lo real es `account.1_ITAX_19`) | `localizacion-chile` |
| Módulo ausente (`E510`) y método bloqueado (`E520`) | `bucle-de-correccion` — verifica el `state`, no instales por RPC |
| Reportar el estado real tras un lote fallido | `bucle-de-correccion` → "Reportar el estado real" |

Si no encaja en ninguna taxonomía, es `E400` con criterio funcional desconocido: pendiente
`regla_negocio` con el mensaje literal. **Nunca resumas ni parafrasees un mensaje de error de Odoo al
escalarlo**: el texto exacto es lo que un consultor funcional reconoce.

## Los `E400` que se repiten (conocimiento de dominio)

Odoo aplicó una validación que el modelo conoce y la plantilla no. Los casos vistos en proyectos
anteriores, para que reconozcas el patrón rápido:

- **UoM incompatible**: `uom_po_id` en otra `uom.category` que `uom_id`. Corrección de dato, va al
  consultor con el nombre de la categoría correcta.
- **Cuenta contable del tipo equivocado** para el uso (por cobrar en un campo de ingreso). Criterio
  funcional: consultor.
- **Impuesto de venta en un campo de compra** o incoherente con la posición fiscal. Consultor.
- **Moneda del documento distinta de la del diario**. Diseño: pendiente hacia el flujo dueño.
- **Localización chilena**: comuna como texto libre donde va una entidad; tipo de documento sin
  diario; folios CAF ausentes. El error de folios **no parece de configuración** — el mensaje habla de
  secuencia, no de CAF. Reconócelo y dilo con esas palabras.

Tu trabajo no es decidir el criterio funcional. Es traducir el mensaje de Odoo a algo accionable: qué
fila, qué columna, qué valor, qué esperaba Odoo, y las opciones viables. Después, pendiente
`regla_negocio` **acumulado** — y vuelves al bucle.

**El resto del archivo sigue, y el resto del plan también.** Un `E400` es una falla de fila: separa las
filas rechazadas del lote, **recarga el lote sin ellas** (`load()` es transaccional: si no lo reenvías,
las 299 filas buenas tampoco entraron), marca el archivo `parcial` en `08-carga/estado-carga.json`, y
continúa con el siguiente archivo del plan. No descartes el archivo entero por dos filas, y no termines
la etapa por un archivo parcial.

## Reportar el estado real

Después de cualquier caso de borde, el estado tiene que quedar escrito, no en tu memoria de la
conversación. El procedimiento completo (bitácora, `estado-carga.json` antes de pasar al siguiente
archivo, rangos exactos de lo parcial, y qué acumular en `08-carga/capacidades-instancia.json`) está
en `bucle-de-correccion` → "Reportar el estado real" — síguelo. Lo que agrega esta skill:

- `carga_completa: false` siempre que haya una fila fuera.
- El hallazgo que es **propio de un caso de borde** — la regla de negocio descubierta, la colisión de
  prefijo detectada — va al pendiente **con su evidencia**, no a `capacidades-instancia.json`: es
  criterio funcional, no un hecho de esta instancia.

## Nunca

- No reintentes un rechazo de negocio sin cambiar el payload.
- No devuelvas el control por un caso de borde de fila o de archivo. Apártalo, anótalo, sigue el plan, y
  entrega todos los pendientes juntos al cerrar el bucle. Solo `E500`, la colisión de prefijo xmlid y la
  falta de confirmación de producción interrumpen la carga.
- No escales un `Invalid field ...` sin el `fields_get` que lo respalde: la mitad de las veces el campo
  existe con otro nombre y la carga podía continuar.
- No intentes instalar un módulo por RPC. Verifica su `state`, escala el `modulo_faltante`, y sigue
  con los archivos que no dependen de él.
- No crees datos maestros para desatascar una referencia.
- No edites `05-plantillas/` ni `06-completadas/` — las corrige el flujo dueño.
- No parafrasees el mensaje de error de Odoo al escalarlo.
- No reintentes un timeout sin verificar primero si el lote entró.
- No reportes como completa una carga con filas fuera.
- No cambies el host ante un fallo de login.
