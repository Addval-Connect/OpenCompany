---
name: flujo-configuracion
description: Misiones diseño, cruce requiere_de y cierre G2 — procedimiento de configuración para los cuatro agentes de flujo.
allowed-tools: odoo_jsonrpc
metadata:
  author: opencompany
  version: "1.0"
  category: flujos

---

# Flujo · Configuración (diseño)

Misiones `diseno`, `cruzar requiere_de` y `cerrar G2`. Lo usan los cuatro agentes de flujo. El procedimiento está aquí; los modelos, las dependencias típicas y las decisiones de dominio están en tu skill `flujos/<flujo>`. Cargas también `contrato-implementacion-odoo` y `convencion-ids-externos`.

Las decisiones de diseño son **deterministas**: salen de tu introspección y de las respuestas del consultor. No uses JEV para decidir qué se llena a mano o qué se configura.

## Misión `diseno`

### Precondición

- Tu G1 está cerrado: cero `respuesta:` vacías en `definiciones-requeridas-<flujo>.md`.
- `basado_en` vigente: tu introspección y tu matriz no están vencidas respecto de las respuestas.
- Si tu diseño referencia objetos del ancla contable (cuentas, impuestos, diarios, posiciones fiscales) y tu flujo no es `financiero`, el **G2 del Flujo Financiero está cerrado**. Compruébalo en su archivo, no en tu memoria.

Si algo falla, escribe una definición `otro` en `preguntas-abiertas.md` y devuelve el control.

### Procedimiento

1. **Relee** G1 respondido, tu matriz y tu introspección. Parte de lo vigente.
2. **Construye `blueprint-<flujo>.yaml`**: un objeto por cada modelo que tu flujo necesita para sus historias en alcance (esquema en el contrato). Para cada objeto:
   - **Dueño.** Mira `proyecto.yaml` → `duenos_modelos`. Si el dueño es otro flujo, no es tu objeto: lo pides con `requiere_de`. Si el modelo no tiene dueño, escribe una definición `modelo_sin_dueno` y no lo plantilles.
   - **`fuente`.** `derivado` si Odoo lo crea solo (tu skill de dominio lo dice; verifica con la introspección). `configuracion` si el consultor no necesita aportar datos: los valores salen del diseño y de sus respuestas. `plantilla` si hay datos del cliente que solo él tiene. Una plantilla de pocas filas quema un ciclo humano: si los valores caben en una respuesta de G1, es `configuracion`.
   - **`ancla`.** Solo el Flujo Financiero marca `true`, y solo para el núcleo contable.
   - **`depende_de`.** Los modelos de sus campos relacionales obligatorios, según `fields_get`. El grafo debe ser **acíclico** y cada modelo referenciado debe ser un objeto propio, un objeto de otro flujo (por `requiere_de`) o existir en la instancia (xmlid nativo verificado).
   - `hu`, `cantidad_estimada`, y `requiere_de` si necesitas columnas o registros que pertenecen a otro flujo.
3. **Escribe `configuracion-<flujo>.yaml`** con los valores de los objetos `configuracion` y los ajustes `group_*` necesarios. **Cada valor debe tener origen**: una respuesta de G1, una decisión del skill de dominio confirmada, o un dato de `proyecto.yaml`. No inventes valores. Un ajuste `module_*` no va aquí: instala un módulo, y eso es una definición `modulo_faltante`.
4. **Escribe `tareas-<flujo>.yaml`** (backlog): una tarea por cada objeto cargable, con `depende_de` y `dod`.
5. **Verifica** antes de entregar: grafo acíclico, todo objeto con dueño, `fuente` y `ancla` explícitos, `basado_en` con las versiones vigentes, `version` incrementada.
6. **Escribe el cuestionario G2** como ítems `D-NN` nuevos y correlativos en el mismo `definiciones-requeridas-<flujo>.md` (formato de G2 en `puntos-de-control-consultor`): fuente y ancla de cada objeto, dueño y fecha de cada plantilla, objetos que siguen con `[VERIFICAR]`, entorno del ensayo (staging), alcance del QA del flujo, y qué queda fuera por diseño (`desarrollo`, `integracion`) como OT aparte. Cada ítem con propuesta.

### Aceptación

`blueprint-`, `configuracion-` y `tareas-<flujo>.yaml` con esquema válido; grafo acíclico; todo objeto con dueño, `fuente` y `ancla`; `basado_en` vigente.

## Misión `cruzar requiere_de`

### Precondición

Tu G1 cerrado y los blueprints de los flujos que te piden algo, o a los que tú pides algo, disponibles.

### Procedimiento

Un agente no escribe en el archivo de otro. Por eso el cruce es **simétrico**:

- **Tus pedidos** viven en tu blueprint, en `requiere_de: [{flujo, modelo, columna}]`.
- **Las respuestas a pedidos que te hacen** las escribes tú, en tu propio blueprint, bajo `acepta_pedidos: [{de_flujo, modelo, columna, decision, nota}]` con `decision` = `aceptado` o `rechazado`, y la razón si rechazas.
- Para ver la respuesta a tus pedidos, lees el `acepta_pedidos` del dueño.

Si el cruce produce un ciclo (A pide a B lo que B pide a A) o un pedido sin dueño que lo absorba, no lo resuelvas: escribe una definición `otro` con los dos extremos y devuelve el control. El Coordinador lo lleva a G2.

### Aceptación

Cada `requiere_de` que apunta a tu flujo tiene una entrada en tu `acepta_pedidos`.

## Misión `cerrar G2`

1. Relee tus archivos antes de escribir.
2. Transcribe solo `respuesta`, `respondido_por` y `respondido_en` desde `context.respuestas`. Nunca escribas una respuesta que nadie dio.
3. Actualiza el blueprint y la configuración solo en lo que la respuesta cambia; incrementa `version`.
4. Si una respuesta de G2 invalida algo aguas arriba (una clasificación, un G1), no lo parches: escribe una definición `otro` y devuelve el control. El Coordinador re-delega la etapa afectada.
5. Si una respuesta cambia una definición ya cerrada, agrega un ítem nuevo que dice qué reemplaza.

Aceptación: cero `respuesta:` vacías en los ítems de G2; `basado_en` vigente.

## Nunca

- Plantillar un modelo que tiene otro dueño, o un `derivado`.
- Plantillar un objeto con `[VERIFICAR]` abierto.
- Escribir valores de configuración sin origen.
- Cambiar el `prefijo_xmlid`: está aprobado en G0 y es inmutable tras la primera carga.
- Editar el blueprint de otro flujo para "resolver" un pedido.
