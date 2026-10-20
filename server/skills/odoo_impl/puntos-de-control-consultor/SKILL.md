---
name: puntos-de-control-consultor
description: Los cuatro tipos de punto de control con el consultor — qué detiene el pipeline, qué se pregunta y cuándo.
allowed-tools: task_manager write_todos
metadata:
  author: opencompany
  version: "1.0"
  category: coordinador

---

# Puntos de control del consultor

Una implementación de Odoo no falla por falta de agentes: falla por definiciones que nadie tomó y que el pipeline supuso. Cada una se descubre en la carga, cuando ya hay plantillas llenadas a mano. Por eso el proceso se detiene en cuatro tipos de punto. **Un punto de control no es un error: es el diseño.** El error es cruzarlo.

| Punto | Alcance | Lo cierra |
|---|---|---|
| **G0** | Proyecto | Validación del descubrimiento y definiciones del proyecto |
| **G1** | Por flujo | Cierre del análisis |
| **G2** | Por flujo | Aprobación del diseño |
| **G3** | Por flujo | Llenado de plantillas |

Los cuatro flujos avanzan a su propio ritmo: el G1 de un flujo puede cerrarse mientras otro está en G3. Una definición corregida en G1 cuesta una respuesta; la misma corregida después de G3 cuesta regenerar plantillas y volver a pedir al consultor que las llene.

## Qué cierra cada punto

### G0 · Descubrimiento y proyecto

D0 produce una propuesta; la autoridad es `00-entrada/`. Se cierra cuando:

1. `00-entrada/historias.csv` validado existe y tiene filas (los flujos filtran por su columna `flujo`; sin él entregan un análisis vacío).
2. Alcance por flujo y sub-alcance confirmados (tesorería, facturación, servicios, aprobaciones, fabricación pueden quedar fuera sin que el flujo entero lo esté), incluidas las historias marcadas fuera del alcance modular.
3. Cada pregunta `D-00-NN` de `preguntas-descubrimiento.md` respondida o declarada no aplica.
4. Los flujos en alcance sin ninguna historia: el consultor confirma que es así, o agrega historias.
5. **Definiciones de proyecto** en `01-analisis/definiciones-proyecto.md`, preguntadas una sola vez: base de datos y rama del entorno objetivo, `prefijo_xmlid` aprobado literalmente, compañía y localización, moneda, y el dueño de cada modelo compartido.

### G1 · Cierre del análisis (por flujo)

Cada agente escribe su cuestionario en `01-analisis/definiciones-requeridas-<flujo>.md` durante su misión de análisis. Las definiciones que no aplican se declaran no aplicables, no se omiten. Mínimo:

| # | Definición | Qué se rompe si se supone |
|---|---|---|
| 1 | **Cada módulo faltante** que sus historias requieren: se instala, o las HU salen de alcance (`BLOQUEANTE`) | Un blueprint sobre un módulo ausente se cae completo en la carga |
| 2 | **Cada clasificación dudosa** (estándar, parametrizable, desarrollo, integración, fuera de alcance) | Se descubre cuando ya hay plantillas |
| 3 | **Cada campo marcado `[VERIFICAR]`**: omitir columna, instalar módulo o usar campo alternativo | Una columna que el consultor llena para nada |
| 4 | **Cada decisión no obvia del dominio**, una por línea, cerrada | Es lo que alguien "arregla" tres semanas después sin saber por qué estaba así |

Decisiones de dominio mínimas por flujo (los skills de dominio las detallan):

- `financiero`: plan de cuentas (¿el de la localización o uno propio?), impuestos y tasa vigente, diarios, bancos y conciliación, folios y documentos tributarios.
- `ventas_servicios`: política de facturación, precios con IVA incluido o neto, cómo se factura un servicio.
- `compras_aprobaciones`: control de facturas de proveedor, reglas y umbrales de aprobación, arranque del reabastecimiento.
- `inventario_fabricacion`: método de valorización y costeo, detalle de ubicaciones, tipo de lista de materiales, órdenes de trabajo.

### G2 · Aprobación del diseño (por flujo)

Aprobar el diseño es aprobar el trabajo humano que viene. Por cada `blueprint-<flujo>.yaml`, transcrito como definiciones `D-NN` en el mismo archivo de G1 del flujo:

| # | Definición | Qué se rompe si se supone |
|---|---|---|
| 1 | La `fuente` de cada objeto (`plantilla`, `configuracion`, `derivado`) y qué objetos son `ancla` | Una plantilla de 3 filas quema un ciclo humano; plantillar un `derivado` hace llenar datos que Odoo sobrescribe |
| 2 | Dueño y fecha por cada plantilla (quién llena qué columnas) | G3 espera indefinidamente a nadie en particular |
| 3 | Los objetos que siguen con `[VERIFICAR]` | Plantillar un objeto dudoso detiene el pipeline más tarde y más caro |
| 4 | Cada pedido `requiere_de` cruzado: aceptado o rechazado por escrito por el dueño | Una columna que nadie absorbe aparece vacía en G3 |
| 5 | Entorno del ensayo de carga: siempre `staging` | QA y ensayos jamás contra producción |
| 6 | Alcance del QA del flujo: qué casos son criterio de aceptación del cliente | Se cierra con un QA que no era el que importaba |
| 7 | Lo que queda fuera del blueprint por diseño (`desarrollo`, `integracion`), confirmado como OT aparte | Una OT abierta por diseño se lee como omisión |

### G3 · Llenado de plantillas (por flujo)

El consultor llena las plantillas siguiendo `INSTRUCTIVO-<flujo>.md`. El Coordinador transcribe sus respuestas a `06-completadas/`. CARGA no valida una carpeta vacía. No lleva cuestionario propio: el INSTRUCTIVO es el documento del punto.

## Reglas del archivo de definiciones

1. **Un ítem se numera `D-NN` y no se renumera nunca.** El consultor responde citando el número.
2. **Ningún agente escribe `respuesta`, `respondido_por` ni `respondido_en` por su cuenta.** Se transcriben desde lo que respondió la persona, y solo el agente dueño del archivo (en su misión `Cerrar G1` / `Cerrar G2`) o el Coordinador (G0). Rellenar una respuesta "obvia" convierte el punto en trámite.
3. **Un ítem no se borra porque quedó sin responder.** Es la evidencia de qué falta. Si dejó de aplicar, se responde `no aplica` con quién lo dijo.
4. **`BLOQUEANTE` marca lo que detiene la etapa siguiente completa** (módulo faltante, autorización de producción, toda definición sin la cual el diseño no existe). El resto bloquea solo un objeto, y permite avanzar con lo ya definido.

El archivo es la autoridad sobre si el punto está cerrado. Si el puntero y el archivo se contradicen, manda el archivo.

## Cómo lo ejecuta el Coordinador

No escribes cuestionarios: **transportas**.

1. **Lee el archivo** del punto con `fileRead`; el cuestionario del agente ya trae todo.
2. **Publica** (skill `correo-consultor`): los `BLOQUEANTE` primero, agrupados por flujo, con las opciones tal como vienen y sin sugerir una, porque la propuesta ya está en cada bloque. Los pendientes que los agentes escribieron en los archivos no se preguntan dos veces.
3. **Di explícitamente que ese trabajo está detenido** y qué desbloquea cada respuesta. Refleja el punto como ítem propio en `write_todos`. Los flujos que no dependen de esa respuesta siguen.
4. **Espera por el mismo canal.** No reintentes por otra vía ni avances "mientras tanto" con lo que depende de la respuesta.
5. **Al llegar respuestas**, re-delega la misión de cierre (`Cerrar G1` / `Cerrar G2`) al agente dueño de cada archivo, con las respuestas en el `context`. Es una delegación acotada: transcribe y actualiza solo lo que la respuesta cambia. G0 y las plantillas llenadas las transcribes tú.
6. **Verifica el cierre releyendo los archivos**, no el resultado de la delegación: cero `respuesta:` vacías. Recién ahí delegas la etapa siguiente de ese flujo.

Lo que no haces: dar un punto por cerrado con ítems sin responder, responder tú un ítem, ni saltarte un punto porque "no había pendientes". El cuestionario mínimo existe aunque ningún agente haya levantado una duda.

## Precondiciones de cada misión

Antes de ejecutar una misión, el agente comprueba su precondición. Si no se cumple, no la ejecuta a medias: devuelve una definición `otro` diciendo qué punto está abierto y con qué ítems. El Coordinador comprueba las mismas precondiciones **antes de asignar**, para no gastar un turno de agente (tabla en `orquestacion-del-proyecto`).

## Casos de borde

- **Respuesta parcial:** transcribe lo definido; re-pregunta solo por los ítems abiertos, citando su `D-NN`, nunca reenviando el cuestionario completo.
- **La respuesta obliga a re-introspeccionar** (instalaron un módulo, agregaron un campo): el cierre de G1 incluye la re-introspección de esos modelos. Una plantilla generada contra una introspección vencida se cae en la carga con un error que parece de diseño.
- **La respuesta invalida un artefacto ya producido:** re-delega la etapa que lo produjo. Nadie parcha artefactos ajenos.
- **El consultor cambia una definición ya cerrada:** no se edita la respuesta anterior. Se agrega un ítem nuevo que dice qué reemplaza y se re-delega la etapa afectada.
- **El consultor pide más contexto** (ver el CSV, ver qué reportó `fields_get`): lo provees; no cuenta como segunda interrupción.
- **G1 reabierto con G2 aprobado:** G2 vuelve a abrirse en los ítems que dependían de la respuesta cambiada. Se detecta por `basado_en` vencido.
- **Producción:** la autorización exige base de datos y rama explícitas en el texto de la respuesta. "Sí, dale" no vale. El ensayo de carga y el QA van contra staging de todas maneras.
