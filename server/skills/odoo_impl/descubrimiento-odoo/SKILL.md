---
name: descubrimiento-odoo
description: Misión descubrimiento de D0 — convertir el material del cliente en propuesta de épicas e historias y preguntas de alcance (ola 0, una vez por proyecto).
allowed-tools: odoo_jsonrpc
metadata:
  author: opencompany
  version: "1.0"
  category: d0

---

# Descubrimiento (D0)

Misión `descubrimiento`. La ejecuta solo D0, una vez por proyecto (ola 0). Convierte el material que dejó el cliente en una **propuesta** de épicas e historias y en las preguntas de alcance. Cargas también `contrato-implementacion-odoo`, `catalogo-de-flujos` y `jev-decisiones-agentes` (uso `descubrimiento`).

**D0 propone; no decide.** La autoridad es `00-entrada/`: un consultor revisa tu propuesta, corrige y arma el `historias.csv` validado. Lo que tú escribes nunca entra solo al alcance.

## Precondición

`00-entrada/` tiene material (documentos, correos, notas de reuniones, un listado de requerimientos). Si está vacía, no inventes: escribe una definición `alcance_no_declarado` en `preguntas-descubrimiento.md` y termina.

## Qué escribes (y solo esto)

| Archivo | Contenido |
|---|---|
| `01-analisis/propuesta-epicas.md` | Épicas con id `E-NN`, objetivo en una línea y flujo(s) |
| `01-analisis/propuesta-historias.csv` | Historias con las columnas de `historias.csv` (contrato) |
| `01-analisis/preguntas-descubrimiento.md` | Preguntas `D-00-NN` de alcance, en el formato de definición del contrato |
| `01-analisis/definiciones-proyecto.md` | Las preguntas de definiciones de proyecto (ver abajo), también como `D-00-NN` |
| `01-analisis/jev-d0.jsonl` | Log de las llamadas a JEV |

No escribes en `00-entrada/` ni en `03-blueprint/proyecto.yaml`: son del Coordinador, que transcribe lo que el consultor valide.

## Procedimiento

1. **Lee todo el material** de `00-entrada/`. Si un formato no es legible con tus herramientas, es un pendiente, no un material que ignoras.
2. **Extrae historias.** Una historia = un resultado verificable, en el formato `como / quiero / para`, con `criterios_aceptacion` separados por `|` y `prioridad`. Ids estables `HU-NNN`, agrupadas en épicas `E-NN`.
   - **No inventes requerimientos.** Lo que el material no dice no es una historia: es una pregunta `D-00-NN`.
   - Una historia sin criterios verificables se registra igual, pero con una pregunta que pide los criterios.
3. **Clasifica el flujo** de cada historia con JEV (`jev-decisiones-agentes`, uso `descubrimiento`), usando `catalogo-de-flujos` para las fronteras. Con confianza ≥ 0,8 escribes el `flujo`; bajo ese umbral dejas la columna vacía y abres una pregunta. Registra cada llamada en `jev-d0.jsonl`.
4. **Detecta lo que falta o choca:**
   - los flujos que el material sugiere en alcance y no tienen **ninguna** historia;
   - historias que parecen duplicadas o contradictorias;
   - historias candidatas a `fuera_de_alcance_modular` (desarrollo a medida o integración con un sistema externo); las listas como candidatas, JEV no las saca del alcance;
   - sub-alcances que el material no aclara (por ejemplo, si tesorería o fabricación entran).
5. **Escribe las preguntas de alcance** (`preguntas-descubrimiento.md`), numeradas `D-00-NN`, con pregunta cerrada, opciones **sin sugerir una**, referencia, propuesta concreta y `respuesta:` vacía.
6. **Escribe las definiciones de proyecto** en `definiciones-proyecto.md`, también `D-00-NN` con propuesta, **una sola vez** para todo el proyecto:
   - base de datos y rama del entorno objetivo (y si es `production`, que las pruebas y el ensayo van a staging);
   - `prefijo_xmlid` propuesto, a aprobar literalmente (se propone uno derivado del nombre del cliente, y se pide confirmación: es inmutable tras la primera carga);
   - compañía(s), localización, moneda;
   - el dueño propuesto de cada modelo compartido (`res.partner`, `product.*`, `uom.*`), según `catalogo-de-flujos`.

## Aceptación (lo que comprueba el Coordinador)

Existen `propuesta-epicas.md`, `propuesta-historias.csv` y `preguntas-descubrimiento.md` con al menos una fila, y el documento lista los flujos en alcance sin historias. Todo ítem trae propuesta.

## Nunca

- Escribir una respuesta (`respuesta:`, `respondido_por:`, `respondido_en:`): las transcribe el Coordinador desde lo que respondió el consultor.
- Asignar un flujo con confianza baja "porque se parece": queda vacío y se pregunta.
- Decidir que una historia sale del alcance.
- Inventar un requerimiento, un criterio de aceptación o un nombre de cliente que el material no trae.
- Escribir fuera de los archivos de la tabla.
