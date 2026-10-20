---
name: flujo-entendimiento
description: Misiones análisis y cierre G1 de los agentes de flujo — procedimiento de entendimiento; el dominio vive en flujos/<flujo>.
allowed-tools: odoo_jsonrpc
metadata:
  author: opencompany
  version: "1.0"
  category: flujos

---

# Flujo · Entendimiento

Misiones `analisis` y `cerrar G1`. Lo usan los cuatro agentes de flujo; tu `flujo` viene en el `context`. Este skill es el **procedimiento**: el conocimiento del dominio (modelos, preguntas, trampas) está en tu skill `flujos/<flujo>`. Cargas también `contrato-implementacion-odoo` e `introspeccion-odoo-solo-lectura`.

## Misión `analisis`

### Precondición (verifícala antes de empezar)

G0 cerrado: `00-entrada/historias.csv` existe con filas; `01-analisis/definiciones-proyecto.md` sin `respuesta:` vacías; `03-blueprint/proyecto.yaml` existe. Si algo falla, no ejecutes a medias: escribe una definición `otro` en `preguntas-abiertas.md` diciendo qué punto está abierto y devuelve el control.

### Procedimiento

1. **Filtra** `historias.csv` por `flujo` = el tuyo y por tu `sub_alcance` (en `proyecto.yaml`). Si tu flujo está en alcance y no tiene ninguna historia, escribe una definición `alcance_no_declarado` y termina.
2. **Introspecciona** la instancia con `introspeccion-odoo-solo-lectura`. Resultado: `02-instancia/introspeccion-<flujo>.json`.
3. **Clasifica cada historia** en `01-analisis/matriz-brechas-<flujo>.csv` (esquema en el contrato): `modelo_odoo`, `objeto_config`, `clasificacion`, `esfuerzo`, `riesgo`, `nota`. Un objeto estándar de Odoo no necesita desarrollo; reserva `desarrollo` e `integracion` para lo que el estándar y la parametrización no cubren. Puedes apoyarte en JEV para proponer (ver `jev-decisiones-agentes`, uso `analisis`); lo que JEV deje bajo el umbral va a G1 como `clasificacion_dudosa`.
4. **Escribe el cuestionario G1** en `01-analisis/definiciones-requeridas-<flujo>.md`, con el formato `D-NN` del contrato. Mínimo:
   - cada módulo faltante (`BLOQUEANTE`),
   - cada clasificación dudosa,
   - cada campo `[VERIFICAR]` de la introspección,
   - las decisiones no obvias de tu dominio, que listan las preguntas mínimas de tu skill `flujos/<flujo>`.

   Cada ítem trae pregunta cerrada, opciones **sin sugerir una**, referencia a archivo y fila o modelo, y una **propuesta concreta** del agente. `respuesta:` queda vacía. Lo que no aplica se declara `no aplica`, no se omite.
5. Marca `version: 1` en cada archivo que escribes y registra en la introspección su fecha.

### Salidas y aceptación

`matriz-brechas-<flujo>.csv`, `introspeccion-<flujo>.json` y `definiciones-requeridas-<flujo>.md`. El Coordinador acepta si existen, el cuestionario trae el mínimo y cada ítem trae propuesta.

## Misión `cerrar G1`

Misión acotada: el Coordinador te pasa en el `context.respuestas` lo que respondió el consultor.

1. Relee tu `definiciones-requeridas-<flujo>.md` antes de escribir (partes del contenido vigente, no de una copia).
2. Transcribe **solo** `respuesta`, `respondido_por` y `respondido_en` desde lo que llegó. **Nunca escribas una respuesta que nadie dio**, ni rellenes una "obvia".
3. Actualiza solo lo que la respuesta cambia:
   - una reclasificación cambia una fila de la matriz;
   - un módulo instalado o un campo agregado obliga a **re-introspeccionar esos modelos** (incrementa `version` de la introspección);
   - una respuesta que abre un ítem nuevo se agrega con el siguiente `D-NN`, abierto; nunca renumeres.
4. Un ítem cuya respuesta lo deja sin sentido se responde `no aplica`, citando quién lo dijo; no se borra.
5. Si el consultor cambió una respuesta ya cerrada, no la edites: agrega un ítem nuevo que diga qué reemplaza.
6. Incrementa `version` de lo que cambió. Devuelve el control con la lista de ítems aún abiertos, si los hay.

Aceptación: cero `respuesta:` vacías o `no aplica` con firma; introspección vigente.

## Nunca

- Suponer una decisión de negocio ("elegir la opción más razonable") en algo que decide una persona.
- Escribir en carpetas que no son tuyas, o en Odoo.
- Entregar un cuestionario sin propuesta en cada ítem, o con la propuesta como única opción.
- Cerrar G1 con un `[VERIFICAR]` sin definición.
