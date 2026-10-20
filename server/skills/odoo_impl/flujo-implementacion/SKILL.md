---
name: flujo-implementacion
description: Misiones plantillas y validación — producir y validar los archivos que el consultor llena; no cargan nada en Odoo.
allowed-tools: odoo_jsonrpc
metadata:
  author: opencompany
  version: "1.0"
  category: flujos

---

# Flujo · Implementación (plantillas y validación)

Misiones `plantillas` y `validacion`. Lo usan los cuatro agentes de flujo. Producen y validan los archivos que el consultor llena; **no cargan nada**: eso es de CARGA. Cargas también `contrato-implementacion-odoo`, `convencion-ids-externos` y `sandbox-de-codigo-en-opencompany` (para leer CSV).

## Misión `plantillas`

### Precondición

Tu G2 cerrado: cero `respuesta:` vacías en los ítems de G2 de `definiciones-requeridas-<flujo>.md`. Si no, escribe una definición `otro` y devuelve el control.

### Procedimiento

Para cada objeto de tu blueprint con `fuente: plantilla`:

1. **CSV `05-plantillas/<modelo>.csv`**, sin prefijo `NN`. Cabeceras nativas del importador, `id` siempre primera. Una referencia a otro objeto es siempre `<campo>/id` con xmlid, nunca nombre ni id numérico. La forma de una columna relacional la decide el valor: si lleva xmlid, la cabecera termina en `/id`.
2. **Sidecar `<modelo>.meta.json`** (esquema en el contrato): `obligatorios` según `fields_get`, `catalogos` con las claves técnicas de cada `selection` (de tu introspección, no de memoria), `referencias` hacia los CSV que producen cada xmlid, `fila_ejemplo`, `introspeccion_fecha` y `basado_en`.
3. **Incluye las columnas que otros flujos te pidieron** y tú aceptaste en `acepta_pedidos`. Una columna que nadie absorbe no existe.
4. **xmlids** según `convencion-ids-externos`: `<prefijo>.<objeto_corto>_<clave_natural>`, clave inmutable, nunca un contador. La fila de ejemplo muestra el patrón con una clave real.
5. **`INSTRUCTIVO-<flujo>.md`**, una sección por archivo: qué es el archivo, **quién llena qué columnas y para cuándo** (de los ítems de G2), formatos (fechas `YYYY-MM-DD` en UTC, booleanos `1`/`0`, valores técnicos de `selection` y no etiquetas), la regla del xmlid y, si el CSV tiene filas anidadas, la advertencia de que ordenar o filtrar rompe la relación.
6. **Casos de QA `09-qa/casos-<flujo>.yaml`** (formato del contrato): uno por criterio de aceptación verificable de tus historias y por caso canónico de tu skill de dominio, dentro del alcance de QA aprobado en G2.
7. **Verifica** antes de entregar: todo `<campo>/id` apunta a un objeto de algún blueprint o a un xmlid nativo verificado; el grafo `depende_de` sigue siendo acíclico.

### Aceptación

Un CSV y un sidecar por objeto `plantilla`; `INSTRUCTIVO-<flujo>.md` con quién llena qué; `casos-<flujo>.yaml` según el alcance aprobado.

## Misión `validacion`

### Precondición

Hay archivos en `06-completadas/` de **tus** modelos. Valida solo tus modelos, nunca los de otro flujo.

### Procedimiento

1. **Lee los CSV con `sandboxed_python` y `workspace_read`**, no con `fileRead`: el archivo completo no debe entrar a tu historial. Devuelve solo errores y conteos.
2. **Valida** por cada archivo, en este orden:
   - **Estructura (`E100`)**: columna `id` primera, sin vacíos; cabeceras que existen en el modelo; sidecar presente. Un `E100` **detiene el archivo completo**.
   - **Identidad**: `id` únicos (`E310`), todos con el `prefijo_xmlid`, todos cumpliendo `^[a-z0-9_]+\.[a-z0-9_]+$`.
   - **Obligatorios (`E200`)**, **formatos (`E210`)** y **catálogos (`E220`)** contra el sidecar.
   - **Referencias (`E300`)**: cada `<campo>/id` existe en un archivo del mismo lote, o en la instancia (`ir.model.data`, solo lectura).
   - **Dependencias (`E320`)**: ninguna referencia a un objeto que, por el grafo `depende_de`, deba cargarse después.
   - Validaciones locales (RUT con dígito verificador, formato de código de cuenta) **solo si** tu skill de localización las declara y la instancia las aplica. **Clasifica por lo que Odoo rechaza, no por lo que a ti te parece mal**: nunca rechaces una fila por una comprobación tuya que Odoo no aplica.
3. **Reporta con ubicación exacta.** `07-validacion/errores-<modelo>.csv` con `codigo,archivo,fila,columna,valor,mensaje,corrige`; un error sin archivo, fila y columna es inútil. Cuando el valor erróneo se parece a uno válido, sugiere el candidato en `mensaje`. Un `E220` con lista de claves reporta la lista completa.
4. **`07-validacion/informe-<modelo>.md`** por modelo y **`veredicto-<flujo>.json`** (esquema en el contrato): un veredicto por archivo, `cargable`, `con_errores` o `detenido`. CARGA lee ese archivo, no tu resultado.
5. Si el defecto es de la plantilla (una cabecera mal generada, un catálogo vencido), no lo corrijas en el archivo del consultor: escribe una observación en `preguntas-abiertas.md`. El Coordinador re-delega `plantillas`.

Apoyo opcional de JEV: proponer el candidato de un `E220` o `E300` (ver `jev-decisiones-agentes`, uso `validacion`). Solo es una sugerencia en el informe: **nunca corrige** una celda.

### Aceptación

`veredicto-<flujo>.json` con un veredicto por archivo, y `informe-` y `errores-` por modelo.

## Nunca

- Editar `05-plantillas/` desde `validacion` ni `06-completadas/` en ninguna misión: lo segundo es del Coordinador.
- Descartar una columna "para que pase". Si la columna estaba, alguien llenó datos ahí.
- Corregir celdas. El consultor corrige; tú reportas.
- Rechazar con una validación que Odoo no hace.
- Validar modelos de otro flujo.
