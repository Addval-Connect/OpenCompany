---
name: "procesa-archivo-cartola"
description: "Pipeline determinista de 4 pasos, siempre en este orden. Todo vive bajo el workspace del"
metadata:
  author: opencompany
  version: "1.0"
  category: "statement_import"

---

# Procesar archivo de cartola (runbook A1)

Pipeline determinista de 4 pasos, siempre en este orden. Todo vive bajo el **workspace** del
workflow (rutas workspace-relativas, nunca `/tmp` ni memoria). El `context` de la `task_manager`
trae la ruta al archivo original (ej. `sesiones/<sesion_id>/original/<nombre>`) y el nombre
original (sugiere custodio, no lo confirma).

> **Nodo shell = Nushell (NO bash).** No uses `&&`/`||`; encadena con `;` o `try {…} catch {…}`.
> Redirección `| save archivo` (no `>`). Sustitución `(cmd)` (no `$(cmd)`). Para filtrar por
> contenido usa `fs_search`, no `grep`. Si un comando falla, corrige la sintaxis y reintenta; no
> insistas con la misma.

Persiste los artefactos de cada paso en `sesiones/<sesion_id>/` con `file_modify`, y devuelve al
Coordinador el bloque `archivo` consolidado. Un solo resultado de tarea al final; no vuelvas al
COORD entre pasos.

## Paso 1 — Detectar formato real (nunca por extensión)

`pdfinfo`/`pdftotext` fallan **en silencio** sobre ZIP disfrazados de PDF (Banchile, BCI AM, UBS,
Moneda/Pershing, Ameris entregan ZIP con un `.jpeg`+`.txt` por página bajo extensión `.pdf`).

1. `shell_execute`: `file <ruta_workspace>` (ignora la extensión).
2. Interpreta:
   - `Zip archive data` / firma `PK` → **ZIP disfrazado**. `unzip -o -q <archivo> -d
     sesiones/<sesion_id>/paginas` → espera pares `<n>.jpeg` + `<n>.txt`.
   - `PDF document` → **PDF real**, ruta estándar de lectura.
   - `Microsoft Excel` / Zip con estructura `xl/` → **XLSX**, deriva a ruta tabular (fuera de
     alcance).
   - otra cosa → `desconocido`.
3. Si es ZIP: `ls -1v sesiones/<sesion_id>/paginas` para verificar pares consecutivos y contar
   páginas.
4. **Nunca** `pdftotext`/`pdfinfo` sobre lo que `file` marcó como ZIP.

→ `archivo.formato_real` (`pdf_texto|pdf_escaneado|zip_paginas|xlsx|desconocido`),
`archivo.paginas`, `archivo.ruta_paquete`. Cortes: formato `desconocido`, ZIP corrupto/parcial, o
archivo de 0 bytes → alerta + sesión `RECHAZADA`, sin reintento automático.

## Paso 2 — Extraer contenido por página (índice de texto vs imagen)

El interpretador (A2) necesita saber, antes de leer, si cada página tiene texto confiable o debe
leerse por imagen.

1. Por página `n`: si hay `n.txt` (ZIP), cuenta caracteres no-whitespace (`file_read`, o shell
   `tr -d '[:space:]' | wc -c`). Si es PDF real, extrae por página (`pdftotext -f n -l n`); el
   COORD puede haber cableado un **documentParser** aguas arriba que ya dejó el texto por página.
2. Umbral: promedio muy bajo para una página que debería tener tabla (referencia: <~200 chars
   no-whitespace) → `tiene_texto: false` en esas páginas.
3. **Página PDF real con `tiene_texto: false` → rasterízala, no la dejes sin imagen.** El caso ZIP
   ya trae su `n.jpeg` por construcción; un PDF real (texto no extraíble por fuentes subseteadas,
   anotaciones/comentarios que ensucian el stream, o escaneo puro) no trae ninguna imagen de
   respaldo salvo que la generes tú: `pdftoppm -jpeg -r 150 -f n -l n "<ruta_workspace>"
   "sesiones/<sesion_id>/paginas/pagina"` → produce `pagina-n.jpeg`. Hazlo por cada página bajo el
   umbral (no la cartola completa, para no gastar contexto de más) y referencia esa ruta como
   `ruta_img` en el índice. Sin este paso, A2 llega a una página sin `ruta_txt` útil y sin
   `ruta_img` — no tiene con qué leerla y la sesión queda colgada en
   `PENDIENTE_PREPROCESAMIENTO` en vez de resolverse aquí.
4. Con imagen (de ZIP o recién rasterizada): conserva `n.jpeg`/`pagina-n.jpeg` para lectura visual
   en A2 (no fuerces OCR ciego, la visión del LLM supera al OCR en tablas densas — esto vale igual
   para el caso de comentarios/anotaciones que para el escaneo puro; no son dos problemas distintos,
   son el mismo "sin texto confiable, léela como imagen").
5. **No cargues el contenido completo de las páginas al contexto** — esto construye el índice, no
   interpreta.

→ Escribe `sesiones/<sesion_id>/indice_paginas.json`:
```json
{"paginas": [{"n": 1, "tiene_texto": true, "chars": 1840, "ruta_txt": "1.txt", "ruta_img": "1.jpeg"}],
 "texto_disponible_global": true}
```
`texto_disponible_global` es `false` solo si **ninguna** página relevante tiene texto útil (señal
para que A2 derive a `REQUIERE_USUARIO`). Portada/carátula con `chars` bajo es legítimo — no la
uses para decidir el global.

## Paso 3 — Armar paquete (aislar página 1)

El clasificador de custodio (A2) solo necesita la página 1; aislarla evita multiplicar el costo de
contexto en el paso más frecuente.

1. Escribe `sesiones/<sesion_id>/pagina_1.json` (`ruta_txt` + `ruta_img` de la página 1) — es lo
   único que el COORD pasa al clasificador en su `context`.
2. Conserva el índice completo en el workspace para el interpretador, pero **no lo empujes** al
   clasificador.
3. Si la página 1 está vacía/corrupta pero otras tienen encabezado de cliente (`fs_search`), no
   sustituyas: deja la alerta y que el clasificador decida.

## Paso 4 — Hash y detección de duplicado

El reenvío accidental de una cartola ya cargada es frecuente en un flujo mensual manual; detectarlo
aquí es mucho más barato que después de que A4 escribió movimientos.

0. **Override**: si el `context` trae `forzar_reproceso: true` (el usuario pidió reprocesar),
   SALTA los pasos 2-3 de duplicado: registra la alerta `"reproceso forzado por el usuario: se
   ignora el duplicado de <sesion_previa>"`, calcula igual el `sha256` para la traza, y continúa
   sin `RECHAZADA`.
1. `sha256sum <archivo_original>` sobre el archivo **tal como llegó** (antes de descomprimir), no
   sobre los derivados.
2. Busca ese hash en sesiones previas `IMPORTADA`/`IMPORTADA_PARCIAL` (`fs_search` sobre
   `sesiones/*/archivo.json` + rastro de TeamTasks cerradas; no hay base externa).
3. Coincidencia exacta de hash y sin `forzar_reproceso` → NO reproceses; devuelve `RECHAZADA` con
   `"cartola duplicada: ya procesada en sesión <previa> el <fecha>"` e indica al COORD que el
   usuario puede pedir procesarla igual (lo que reactiva con `forzar_reproceso: true`).
4. Hash distinto pero nombre muy similar a una sesión reciente del mismo custodio+período → no
   bloquees; alerta `"nombre similar a sesión previa <id>: mismo custodio y período, hash distinto"`
   (puede ser corrección legítima del custodio).

## Salida (un solo resultado de tarea al COORD)

```json
{
  "archivo": {
    "nombre_original": "BANCHILE_Diciembre_2025.pdf",
    "hash_sha256": "…",
    "formato_real": "zip_paginas",
    "paginas": 7,
    "ruta_paquete": "sesiones/sesion_123/paginas"
  },
  "duplicado": false,
  "sesion_previa_relacionada": null
}
```
Más los artefactos en el workspace: `archivo.json`, `indice_paginas.json`, `pagina_1.json`. El
COORD avanza la TeamTask a `NORMALIZADA` y asigna a A2.

## Casos de borde

- **Misma cartola, distinto nombre**: manda el hash del contenido, no el nombre.
- **Cartola corregida por el custodio** (mismo período, contenido distinto): hash distinto → no es
  duplicado; procésala, la alerta del paso 4 avisa a Tax.
- **Sin registro histórico** (primera ejecución): no bloquees; alerta `"verificación de duplicado
  omitida: registro histórico no disponible"`.
- **Cartola de una sola página**: igual pasa por los 4 pasos para mantener uniforme el contrato.
- **Layout multicolumna** (página 5 Banchile): el `.txt` puede tener chars pero desordenados; no lo
  detecta el conteo — queda como riesgo documentado para que A2 use imagen en esa página.
- **PDF real con fuentes subseteadas o con anotaciones/comentarios** (ej. exportado desde
  Chromium/Skia): `pdftotext` puede devolver vacío o basura sin fallar — no lo trates como corte
  duro de formato (sigue siendo `pdf_texto`, el problema es por página). Rasterízala con
  `pdftoppm` (Paso 2.3) y sigue.
- **`pdftoppm` también falla** (PDF corrupto/cifrado a nivel de página): ahí sí es corte duro para
  esa página — `tiene_texto: false`, sin `ruta_img`, y anótalo en `indice_paginas.json` para que A2
  la derive a `REQUIERE_USUARIO` en vez de reintentar en loop.
