---
name: "leer-tabla-desde-imagen"
description: "No hay servicio de OCR: la lectura la hace el propio LLM por visión. Abre el"
metadata:
  author: opencompany
  version: "1.0"
  category: "assistant"

---

# Leer tabla desde imagen

No hay servicio de OCR: la lectura la hace **el propio LLM por visión**. Abre el
`.jpeg` de la página con **file_read** (la herramienta entrega la imagen al modelo)
y transcribe lo que ves. La ruta (`ruta_img`) viene del índice de páginas del
workspace, referenciado en el `context` de la TeamTask.

## Cuándo se activa (solo dos escenarios)

1. El índice de páginas marcó `tiene_texto: false` para la página.
2. `interpreta-cartola` detecta que el `.txt` tiene columnas
   desalineadas/interleaved (texto presente pero inservible como tabla).

Si ninguna aplica, prioriza la lectura de texto plano (menos contexto, más precisa
para cifras).

## Procedimiento

1. Toma `ruta_img` del índice de páginas (workspace) y ábrela con **file_read**.
2. Identifica visualmente los encabezados de columna, apoyándote en el diccionario
   del custodio ya recuperado (describe qué columnas esperar y en qué orden).
3. Transcribe fila por fila, columna por columna, el mismo conjunto de campos que
   una extracción de texto: fecha, descripción/movimiento, cantidad, precio, monto
   — según el diccionario.
4. Atención a: separadores de miles/decimales (formato chileno: punto miles, coma
   decimales, salvo que el diccionario indique otra convención para custodios
   extranjeros), signos de cargo/abono, prefijos de moneda (ej. "USD" antepuesto al
   monto en Banchile).
5. Celda ilegible (resolución, mancha, corte): no completes por inferencia. Marca la
   línea con `confianza_instrumento: baja` y agrega el detalle a `alertas`.

## Salida

Los mismos campos que produciría `interpreta-cartola` desde texto
plano, para las filas de esa página. Se integran a `sesion/cartola_base.json` (la
integración la hace `interpreta-cartola` con **file_modify**), no se
devuelven como estructura aparte.

## Casos de borde

- **Tabla parcialmente cortada al borde de la imagen**: no la completes; alerta
  `"tabla cortada en imagen de pagina <n>: posible fila incompleta"` y deja la línea
  en `requiere_confirmacion`.
- **Resolución insuficiente para distinguir 3 de 8 o 0 de 6 en un monto**: nunca
  redondees ni elijas la lectura más probable de una cifra financiera. Mejor una
  línea sin cargar que una con un dígito equivocado.
