---
name: bucle-de-correccion
description: Cómo CARGA reintenta, qué corrige por su cuenta y cuándo se detiene — códigos E1xx a E5xx y reglas de corrección.
allowed-tools: odoo_jsonrpc
metadata:
  author: addval
  version: "1.0"
  category: odoo_migracion

---

# Bucle de corrección

Cómo CARGA reintenta, qué corrige por su cuenta y cuándo se detiene. Los códigos (`E1xx` a `E5xx`) están definidos en `taxonomia-errores-odoo`; la mecánica de `load()` en `odoo-rpc-transporte`; el procedimiento de carga archivo por archivo en `migracion-carga`.

**La carga no es una pasada: es un bucle que converge.** Intentas, clasificas, corriges lo que te toca y vuelves a intentar. Devolver el control ante el primer rechazo deja la base a medias y convierte una carga de una corrida en varias.

## Qué reintentas tú

| Código | ¿Lo corriges tú? | Cómo | Intentos |
|---|---|---|---|
| `E110` | sí | `fields_get` del modelo → cabecera corregida | 1 por campo |
| `E220` | sí, si el valor es una etiqueta y el catálogo trae la clave | `fields_get` con `selection` → clave real | 1 por columna |
| `E300` | sí, si el xmlid lo produce otro archivo del plan | difiere el archivo y recárgalo tras su dependencia | hasta 2 rondas |
| `E320` | sí | reordena el plan y vuelve a intentar | 1 reordenamiento |
| `E510` | no | verifica el `state` del módulo; los archivos de ese módulo quedan `detenido` con definición `modulo_faltante`. **El resto del plan sigue** | 0 |
| `E520` | no | método bloqueado; no hay reintento por RPC | 0 |
| `E100` | no | el archivo queda `detenido` | 0 |
| `E200` `E210` `E400` | no | quita **esas filas** del lote, recarga el resto y repórtalas | ver abajo |
| `E500` | no | detén la carga completa y devuelve el control | 0 |

**Un lote con filas rechazadas se recarga sin ellas.** `load()` es transaccional: una fila mala tira el lote entero, así que las 299 filas correctas tampoco entraron. Quitar las filas rechazadas y reenviar **no** es "reintentar igual": es la única forma de que el rechazo de una fila no se convierta en la pérdida del archivo. Anota las filas apartadas con su número de fila del CSV y el archivo queda `parcial`.

## El bucle

```
verifica los módulos del plan (un search_read) -> los archivos de un módulo ausente: detenido
ronda = 1
mientras queden archivos en pendiente|diferido|parcial y ronda <= 5:
    progreso = 0
    por cada archivo del plan, en orden:
        si estado es cargado o detenido -> siguiente
        intenta cargarlo
        todo entró            -> cargado,  progreso += 1
        E110 / E220           -> corrígelo y reintenta YA, en esta misma ronda
        E300 / E320           -> diferido
        E200 / E210 / E400    -> aparta esas filas, recarga el lote sin ellas -> parcial
        E100                  -> detenido
        E510                  -> detenido + definición modulo_faltante
        E500                  -> detén el bucle completo y devuelve el control
    si progreso == 0 -> corta el bucle
    ronda += 1
```

- **Regla de progreso.** Cada ronda cuenta los archivos que pasaron a `cargado` y las filas nuevas que entraron. Una ronda completa con progreso cero termina el bucle: lo que queda no depende de otro archivo, depende de una decisión del consultor. Sin esta regla el bucle reintenta para siempre los mismos rechazos.
- **Tope duro: 5 rondas.** Cinco alcanzan para cualquier grafo de dependencias real; más rondas significan que giras sobre un error que no es de orden.
- **No reintentes sin cambio verificable.** Antes de cada reintento tiene que haber cambiado algo: un campo confirmado con `fields_get`, una dependencia cargada, unas filas apartadas, un orden distinto. Dos rechazos idénticos seguidos son un bucle, no un reintento.
- **Un módulo ausente no cambia dentro del bucle.** Instalarlo es trabajo humano; sus archivos salen del bucle en la primera ronda.
- **Escribe el estado al final de cada archivo**, no al final del bucle (`08-carga/estado-carga.json`: `estado`, `intentos`, `ultimo_codigo`, `filas_apartadas`). Si el turno se corta, la siguiente corrida reanuda desde ahí.

Solo interrumpen la carga: `E500`, una colisión de prefijo xmlid (ver abajo) y la falta de confirmación de producción. Un caso de borde de fila o de archivo **nunca** devuelve el control: se aparta, se anota y se sigue, y los pendientes se entregan juntos al cerrar el bucle.

Al cerrar, registra cuántas rondas hiciste y qué quedó sin cargar. `cierre_bucle` ∈ `todo_cargado` | `sin_progreso` | `tope_rondas` | `detenido_E500`. `sin_progreso` necesita una decisión del consultor; volver a ejecutar sin cambiar nada cuesta lo mismo y da lo mismo. `tope_rondas` sí se reanuda tal cual.

## `E110`: el campo no existe, no adivines otro nombre

`Invalid field 'X' in 'Y'` significa que el campo que escribiste no existe en ese modelo: no es un problema de dato, de permisos ni de instancia. Es el único error que corriges sin devolver el control, con un procedimiento fijo:

1. `fields_get` **sobre ese modelo**:

   ```
   model="res.company", method="fields_get", args=[[]],
   kwargs={"attributes": ["type","required","relation","string"]}
   ```

2. Elige el campo que existe. Si el dato pertenece a **otro modelo** (la compañía delega su contacto en `partner_id`), escribe en ese otro modelo.
3. Reintenta **una sola vez** con el campo verificado, y guarda el hallazgo en `08-carga/capacidades-instancia.json` para no volver a pagar la llamada.
4. Si ningún campo sostiene el dato: definición `campo_inexistente` **con la lista de campos que sí existen** como evidencia, y sigues con el resto del plan.

Condiciones para corregir el nombre en el payload (las tres): el match es **inequívoco** (dos candidatos plausibles es una definición, no un match); lo registras en la bitácora como corrección de cabecera, con el nombre que venía y el que usaste; y lo reportas como observación para el Transformador o el Analista, para que el lote o el mapeo se corrija en el origen. Tú no editas `04-mapeos/` ni `06-lotes/`.

**Un segundo nombre adivinado es el error.** Dos rechazos seguidos por campo inexistente significan que el `fields_get` no se hizo, y cada rechazo encarece el resto del turno. Nunca escribas el dato en un campo "parecido" para que la llamada pase.

## `E220`: clave contra etiqueta

Un `selection` tiene **clave** (invariable, en inglés) y **etiqueta** (traducida al idioma de la instancia). El CSV suele traer la etiqueta, o una clave de una versión anterior. `fields_get` con `attributes: ["selection"]` da los pares:

1. Compara contra las **claves** primero, normalizando (minúsculas, `_` y espacios equivalentes).
2. Después contra las **etiquetas**. Si la instancia está en español y el valor viene en inglés, pide las etiquetas en inglés: `kwargs={"attributes": ["selection"], "context": {"lang": "en_US"}}`.
3. Las claves de entrada y salida **no son simétricas** (ver `odoo19-diferencias`): no extrapoles una de la otra.

**Un match tiene que ser único, y un código corto no se resuelve por parecido.** Un valor de 2 o 3 caracteres (`AT`, `US`, `01`) que no calza exacto con ninguna clave ni etiqueta es una definición, no un candidato: el parecido produce una clave plausible y equivocada que Odoo acepta sin protestar, y eso es peor que el rechazo.

**Columna intoxicada.** Si todas las filas rechazan la misma columna con el mismo motivo, el problema es la columna, no las filas. Si la columna **no es obligatoria** (`fields_get` lo dice), quítala del lote, carga el archivo sin ella y repórtala como `E220` de columna con el valor literal y la lista de claves válidas. Nunca con una columna obligatoria, y nunca inventes un valor "razonable" para rellenarla.

## "Ya existe"

**Antes de clasificar, mira el nombre de la constraint.** Si dice `ir_model_data_module_name_uniq_index`, el error es tuyo: cargaste con `create` y registraste el xmlid a mano. Rehaz el archivo con `load` y no vuelvas a escribir en `ir.model.data`. Revisa si quedaron registros creados sin xmlid (un `search_read` del modelo cruzado contra `ir.model.data`): son huérfanos que `load()` no reconoce y hay que borrar antes de recargar, o quedan duplicados invisibles.

Con cualquier otra constraint hay dos causas con tratamiento opuesto:

- **Es una recarga.** El xmlid ya existía. `load()` debería haber actualizado; si falló, es un unique sobre **otro** campo (un `default_code` duplicado, un RUT repetido) y el conflicto es con un registro **distinto**. Es `E400`: decidir cuál de los dos es el correcto es una decisión de negocio.
- **Colisión de prefijo.** El xmlid existe pero apunta a un registro que este proyecto no creó: el `prefijo_xmlid` colisiona con otro proyecto o módulo. **Detén la carga completa** y escala; seguir sobrescribe registros ajenos.

Para distinguirlas: `read` del registro existente y compáralo con la fila del CSV. Mismo negocio → recarga. Otro → colisión.

## Regla de negocio (`E400`)

Con un mensaje de constraint (`There can only be one…`, `duplicate key`, `violates not-null`, `check constraint`): **no reintentes**. La definición incluye el mensaje literal de Odoo, las filas afectadas (código y nombre) y una **propuesta de corrección concreta** (excluir, reclasificar, actualizar en vez de crear). El consultor aprueba o ajusta; tú ejecutas su decisión. Tu trabajo no es decidir el criterio funcional: es traducir el mensaje a algo accionable (qué fila, qué columna, qué valor, qué esperaba Odoo, qué opciones hay).

## `E300` en carga

Ya pasó por validación, así que si aparece acá el mundo cambió, o se resolvió contra la instancia y el registro se borró. Verifica el xmlid concreto en `ir.model.data`:

- **No existe y lo produce un archivo anterior que se cargó OK** → ese archivo cargó menos filas de las que crees; revisa su bitácora (algún lote traía errores leídos como éxito).
- **No existe y es un xmlid nativo** (`base.*`, `uom.*`) → módulo no instalado o nombre distinto en esta versión. Verifica el `state` del módulo: instalado → `referencia_no_resuelta`; no instalado → `modulo_faltante`.
- **No existe y es de la localización** → no concluyas "módulo ausente": ver `localizacion-chile`.
- **Existe pero apunta a otro modelo** → el diseño referencia el objeto equivocado: definición, no lo fuerces.

**No crees el registro faltante para que la referencia resuelva.** Un `res.partner` o una `product.category` inventada deja basura que aparece en un informe contable seis meses después.

## Error de instancia (`E500`)

- **Timeout o 502/503 en un lote:** el estado es **desconocido**, no fallido. Un timeout del cliente puede ocurrir con la transacción ya confirmada. **Verifica antes de reintentar**: consulta `ir.model.data` por los xmlids de ese lote. Están → el lote entró, sigue. No están → reintenta ese lote.
- **Un reintento, no tres.** Si el segundo también falla por instancia, detén la carga completa.
- **Lotes más chicos** si el timeout es consistente (500 → 200 → 100). Si a 100 también hay timeout, el problema no es el tamaño. Registra el tamaño que aguantó en `lote_optimo`.
- **Login o permisos:** no es recuperable desde acá y **no es el host**. Definición y control al Coordinador.

## Reportar el estado real

1. Anota en `08-carga/bitacora-<modelo>.jsonl` el lote fallido con el mensaje literal de Odoo y las filas que quedaron fuera (números de fila del CSV).
2. Actualiza `08-carga/estado-carga.json` antes de pasar al siguiente archivo.
3. Si un archivo quedó a medias, di los rangos exactos: "filas 2-301 cargadas, 302-412 no".
4. `carga_completa: false` siempre que haya una fila fuera.
5. Acumula en `08-carga/capacidades-instancia.json` lo que el caso enseñó **sobre la instancia**, no sobre los datos: remapeos que terminaron `cargado`, campos que `fields_get` no reporta, claves de `selection` resueltas (con la lista completa), xmlids resueltos y su vía, referencias inexistentes con su causa y dueño, llamadas que devolvieron `cannot be called remotely`, ajustes encendidos con su valor anterior, reglas de xmlid verificadas **con su contraejemplo**, tamaño de lote. Un remapeo que probaste y volvió a fallar no va ahí: solo lo confirmado.

## Nunca

- Reintentar un rechazo de negocio sin cambiar el payload.
- Devolver el control por un caso de borde de fila o de archivo.
- Escalar un `Invalid field …` sin el `fields_get` que lo respalde.
- Reintentar un timeout sin verificar si el lote entró.
- Reportar como completa una carga con filas fuera.
- Cambiar el host ante un fallo de login.
