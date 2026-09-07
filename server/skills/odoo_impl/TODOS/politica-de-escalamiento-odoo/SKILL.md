---
name: politica-de-escalamiento-odoo
description: >-
  Cuándo un agente se detiene y escala en vez de decidir: qué es un pendiente, cómo se escribe, qué
  detiene un archivo y qué detiene la carga completa. Lee esto cuando encuentres algo que no está en
  tu runbook.
metadata:
  agente: TODOS
  tipo: DET
  prioridad: P0
  uso: referencia_compartida
  icon: "🚦"
  author: addval
  version: "1.0"
  category: odoo_impl
---

# Política de escalamiento

Una implementación de Odoo falla de forma silenciosa: un dato mal clasificado se convierte en una
configuración que se convierte en un registro cargado que se convierte en un movimiento contable. El
costo de escalar una duda es minutos; el de adivinar, una restauración de base de datos.

## Regla base

**Si la respuesta no está en tu runbook, en el `blueprint.yaml`, en la introspección o en la
referencia del flujo, no la inventes: escríbela como pendiente y devuelve el control al
Coordinador.** No preguntes por chat tú mismo, no delegues a otro worker, no elijas "la opción más
razonable" en un campo que afecta contabilidad, impuestos, folios o saldos.

Un pendiente no es un fracaso. Un pendiente es el entregable correcto cuando la información no
existe.

## Qué escalar siempre

| Situación | Motivo |
|---|---|
| Un módulo que el blueprint asume no está instalado (verificado por `search_read` sobre `ir.module.module`) | `modulo_faltante` — instalarlo es trabajo manual de una persona, no del agente |
| **Ningún** campo del modelo sostiene el dato del blueprint, confirmado con `fields_get` | `campo_inexistente` |
| Una HU no cae limpio en `estandar` / `parametrizable` / `desarrollo` / `integracion` | `clasificacion_dudosa` |
| Un `<campo>/id` apunta a un xmlid que no existe en ningún archivo ni en la instancia | `referencia_no_resuelta` |
| Odoo rechaza por constraint y la corrección requiere criterio funcional | `regla_negocio` |
| Vas a escribir en producción sin confirmación explícita de base + rama | `entorno_produccion` |
| Cualquier otra cosa que te obligue a suponer | `otro` |

## Antes de escalar: lo que se corrige solo

Escalar de más tiene un costo simétrico al de adivinar: cada pendiente cuesta un ciclo humano, y una
etapa que devuelve el control ante algo que el agente podía verificar en una llamada convierte una
corrida en tres. `campo_inexistente` es la fila que más se escala mal, porque el síntoma de "no se
puede" y el de "no lo verifiqué" son idénticos.

**Un campo que no existe se verifica antes de escalarlo.** `Invalid field 'X' in 'Y'` no significa que
el dato no tenga dónde ir: casi siempre significa que el nombre que usaste no es el real, o que el
dueño del dato es otro modelo. Es `E110`: `fields_get` sobre ese modelo, corriges, reintentas **una**
vez. Solo si tras el `fields_get` no hay ningún campo que sostenga el dato es un pendiente
`campo_inexistente` — y entonces el pendiente vale, porque trae la lista real de campos como
evidencia. El procedimiento y las trampas conocidas están en `odoo-rpc-en-opencompany`.

**Un módulo faltante se verifica y se escala — no se instala.** Odoo no permite invocar
remotamente los métodos administrativos de `ir.module.module` (`button_immediate_install`,
`get_module_info`, …): devuelve `The method '<X>' cannot be called remotely`, y eso no cambia con
otra credencial ni con otro host. Lo que el agente sí hace es **leer** el estado
(`search_read` con `fields=["name","state"]`) y, si falta, escribir un `modulo_faltante` con el
nombre exacto del módulo para que una persona lo instale desde la UI. Instalado el módulo, hay que
**reintrospeccionar**: la introspección anterior no conoce sus campos, y usarla produce un `E110` que
parece un error de diseño.

Esto es la excepción a la regla de arriba, y es de sentido opuesto: acá el pendiente **no** es
"algo que no verifiqué", es el único camino posible. Intentar la instalación por RPC "por si acaso"
gasta iteraciones con resultado garantizado.

**Una dependencia que aún no cargaste no es una referencia no resuelta.** Un `<campo>/id` que apunta a
un xmlid que **otro archivo del plan produce** es orden, no falta de dato: difiere el archivo y
recárgalo después. `referencia_no_resuelta` es cuando el xmlid no lo produce ningún archivo ni existe
en la instancia — verifícalo con `ir.model.data` antes de escalar.

La regla operativa: **escala cuando falta una decisión o un dato que nadie tiene; corrige cuando falta
una verificación que tú puedes hacer.** Y todo pendiente que se pudo haber evitado con una llamada a
`fields_get` es un pendiente mal escrito.

## Qué NO es un pendiente

- **Un error de formato con corrección obvia y verificable.** Un RUT con DV mal calculado es `E210`
  con el DV correcto sugerido, no una pregunta. Lo mismo una fecha `10/08/2026` que claramente es
  `2026-08-10`. Reporta el error con la sugerencia; que decida el consultor al corregir el archivo.
- **Un dato que está en un artefacto que aún no leíste.** Lee primero: la introspección, el sidecar
  `.meta.json`, el `blueprint.yaml`, la referencia del flujo. Un pendiente cuya respuesta estaba en un
  archivo del proyecto quema un ciclo humano completo.
- **Una decisión que tu rol sí puede tomar.** A2 decide `fuente: plantilla` vs `configuracion`: es su
  trabajo. A3 decide el orden de las columnas. A5 decide el tamaño del lote de `load`.

## Cómo se escribe un pendiente

En el resultado que devuelves al Coordinador, dentro de `pendientes[]`, con la forma exacta del
contrato (`contrato-implementacion-odoo`):

```json
{
  "id": "P-003",
  "origen": "A3",
  "motivo": "campo_inexistente",
  "pregunta": "El blueprint pide 'l10n_cl_activity_description' en res.partner, pero fields_get no lo reporta. ¿Se usa 'l10n_cl_activity_description' de otro módulo, se omite la columna, o falta instalar l10n_cl_edi?",
  "opciones": ["Omitir la columna", "Instalar l10n_cl_edi y reintroducir", "Usar el campo alternativo <nombre>"],
  "referencia": { "archivo": "05-plantillas/20_res.partner.csv", "fila": 1, "columna": "l10n_cl_activity_description" },
  "respuesta": null,
  "respondido_por": null,
  "respondido_en": null
}
```

Un pendiente útil tiene tres cosas: la **pregunta cerrada** (respondible en una línea), las
**opciones** viables (quien responde no debería tener que investigar), y la **referencia** exacta
(archivo, fila, columna). Sin las tres, el ciclo de respuesta se duplica.

Los tres campos `respuesta` / `respondido_por` / `respondido_en` los llena el Coordinador tras
consultar al usuario. Un worker nunca los escribe.

## Qué detiene qué

Tres niveles, y confundirlos es el error caro:

0. **Corregible por el agente** (`E110`, `E220`, y `E300` cuando la dependencia está en el plan): no
   detiene nada. Se corrige y se reintenta dentro del bucle de carga. Detenerse acá es el error más
   caro de todos, porque parece prudencia.
1. **Fila rechazada** (`E200`, `E210`, `E400`, `E310`, y `E300` cuando el xmlid no existe en ninguna
   parte): el archivo continúa. Como `load()` es transaccional, "continúa" significa **reenviar el
   lote sin las filas rechazadas** — si no, una fila mala se lleva el archivo entero. Se reportan
   **todas** las filas malas en una pasada, para que el consultor corrija una vez.
2. **Archivo detenido** (`E100`; `E510` para los archivos que dependen del módulo ausente; `E320` solo
   si reordenar no lo resuelve): el archivo no se procesa. No es una falla de dato: el archivo, su
   lugar en el orden o el módulo que lo sostiene no están en condiciones, y seguir produce un estado a
   medias que nadie puede auditar. Los demás archivos del plan continúan.
3. **Carga detenida** (`E500`): se aborta todo. Instancia caída, timeout, permisos, login. No
   reintentes en bucle; escribe el pendiente y devuelve el control. **`E510` no está acá**: un módulo
   ausente detiene sus archivos (nivel 2) pero no la corrida, y **`E520` no detiene nada** — es la
   respuesta esperada de la instancia a una acción que no le corresponde al agente.

Corolario que se olvida: **detenerse no es lo mismo que no reportar.** Un archivo detenido por `E320`
igual produce su `informe-<modelo>.md` diciendo qué dependencia falta y en qué archivo debería estar.

## Precondiciones que el Coordinador verifica antes de delegar

Estas no se saltan; están acá para que un worker pueda rechazar una misión mal formada:

- **A2 no diseña** sin `02-instancia/introspeccion.json` fechada contra la instancia actual.
- **A3 no genera plantillas** con pendientes abiertos que afecten a los modelos de esas plantillas.
- **A4 no valida** archivos que el consultor no ha devuelto a `06-completadas/`.
- **A5 no carga** un archivo con errores abiertos en `07-validacion/`, ni escribe en producción sin
  confirmación explícita.

Si recibes una misión que viola tu precondición: no la ejecutes a medias. Devuelve un pendiente
`otro` explicando qué falta.

## Nunca

- No reintentes un rechazo de negocio sin entender el mensaje. Un reintento ciego con el mismo payload
  gasta iteraciones y no cambia el resultado.
- No escales lo que te tocaba verificar. Un pendiente `campo_inexistente` sin el `fields_get` que lo
  respalde, o un `modulo_faltante` sin haber mirado `ir.module.module`, devuelve el control con una
  pregunta cuya respuesta era una llamada — y el ciclo humano que gasta no se recupera.
- No intentes instalar, actualizar ni crear módulos, modelos o campos por RPC. La instancia rechaza
  esos métodos (`cannot be called remotely`) y el intento no es gratis: gasta la iteración y deja un
  error en el historial que parece un fallo de la carga.
- No inventes datos maestros para que una referencia resuelva. Crear un `res.partner` o una
  `product.category` que no estaba en el blueprint, para que un `<campo>/id` no falle, deja basura que
  nadie sabe que existe.
- No reportes carga parcial como completa. Si hay filas en error, el resultado es parcial, con la
  lista de qué faltó.
- No escribas en la carpeta de otro agente para "arreglar" algo aguas arriba. Observación en
  `01-analisis/preguntas-abiertas.md` y control al Coordinador.
