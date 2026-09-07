---
name: contrato-implementacion-odoo
description: >-
  Contrato único de la sesión de implementación Odoo 19: qué viaja en la mission/context del
  task_manager entre el Coordinador y los agentes A1-A5, y qué artefactos viven como archivos en el
  workspace. Referencia obligatoria antes de leer/escribir estado o agregar un campo.
metadata:
  agente: TODOS
  tipo: DET
  prioridad: P0
  uso: referencia_compartida
  icon: "📋"
  author: addval
  version: "1.0"
  category: odoo_impl
---

# Contrato de sesión de implementación Odoo

Fuente única de verdad sobre qué significa cada campo, dónde vive y quién lo escribe. Cinco agentes
actúan en turnos separados sin verse entre sí; sin contrato, los errores de integración serían
silenciosos.

## Dónde vive la sesión (tres soportes)

1. **Delegación durable (`task_manager`).** El Coordinador (team-lead `ai_employee`) delega a cada
   worker A1-A5 con `task_manager` (`operation="assign_task"`, `assignee_node_id`, `title`,
   `mission`, `context={...}`, `acceptance_criteria={...}`). NO usa `delegate_to_*`. Cada
   `assign_task` crea un TeamTask durable cuyo ciclo `queued → running → submitted → accepted`
   reemplaza cualquier máquina de estados propia; su finalización dispara el `taskTrigger` que el
   Coordinador observa.
2. **Estado de sesión (mission + context).** Los datos livianos de coordinación viajan en el
   `context` y regresan en el resultado. El "estado" NO es un campo que un worker sobrescriba: es el
   TeamTask que el Coordinador abre para el paso siguiente. El `context` lleva rutas
   workspace-relativas, nunca datos pesados.
3. **Artefactos pesados (archivos en el workspace).** Matriz de brechas, introspección, blueprint,
   backlog, plantillas, informes de validación y bitácoras viven como archivos bajo
   `~/.opencompany/workspaces/<slug>/proyecto/…`. Se leen/escriben con `fileRead` / `fileModify` /
   `fsSearch` / `shell`; el `context` solo lleva las rutas.

## Estructura de carpetas del proyecto (única, compartida)

Todas las etapas leen y escriben acá, bajo `proyecto/` en el workspace. Los números del prefijo son
el orden del proceso, no una jerarquía.

```
proyecto/
├── 00-entrada/          epicas.md, historias.csv, alcance.md
├── 01-analisis/         matriz-brechas.csv, supuestos.md, preguntas-abiertas.md
├── 02-instancia/        introspeccion.json, modulos-instalados.json, capacidades-instancia.json
├── 03-blueprint/        blueprint.yaml, decisiones.md
├── 04-backlog/          tareas.yaml
├── 05-plantillas/       NN_<modelo>.csv, NN_<modelo>.meta.json, INSTRUCTIVO.md
├── 06-completadas/      (idem 05, devueltas por el consultor)
├── 07-validacion/       informe-<modelo>.md, errores-<modelo>.csv
├── 08-carga/            plan-carga.json, estado-carga.json, bitacora-<modelo>.jsonl, resumen-carga.md
└── 09-qa/               casos.yaml, resultados-<flujo>.md, evidencia/
```

**Regla dura: un agente nunca escribe en la carpeta de otro.** Si necesita corregir algo aguas
arriba, escribe una observación en `01-analisis/preguntas-abiertas.md` y devuelve el control al
Coordinador. Esto evita que dos agentes se pisen editando el mismo artefacto.

**Única excepción: `02-instancia/capacidades-instancia.json`.** A1 lo crea, y A5 le **agrega** durante
la carga los hechos que solo se descubren escribiendo: métodos que la instancia no expone
(`metodos_bloqueados`), remapeos de cabecera confirmados (`remapeos_confirmados`), campos inexistentes
(`campos_inexistentes`), claves de `selection` verificadas (`valores_confirmados`), xmlids que sí
existen detrás de uno que no y la vía por la que se resolvieron (`xmlids_resueltos`), referencias
ausentes con su causa y su dueño humano (`xmlids_inexistentes`), el estado de los módulos del plan
(`modulos`), los ajustes de `res.config.settings` que encendió y su valor anterior
(`ajustes_aplicados`), las reglas de xmlid que verificó con su evidencia y su contraejemplo
(`reglas_de_xmlid`), qué script usó para cada etapa y contra qué se verificó (`scripts`), el tamaño de
lote que aguantó (`lote_optimo`) y el cierre de la corrida (`resultado_ultimo_ensayo`). Es memoria de *esta* instancia para que la próxima corrida no la
redescubra. La excepción se sostiene porque solo se agregan entradas —`resultado_ultimo_ensayo` es la
única clave que se sobrescribe, porque describe la corrida en curso—: A5 no reescribe ni corrige lo que
A1 introspeccionó, y nunca toca `introspeccion.json`.

## Formatos exactos

### `00-entrada/historias.csv`

```csv
id_hu,epica,flujo,titulo,como,quiero,para,criterios_aceptacion,prioridad
HU-014,E-03,ventas,Cotizar con lista de precios mayorista,...,...,...,"...|...",alta
```

`flujo` ∈ `ventas` | `compras` | `inventario` | `fabricacion` | `contabilidad`. Los criterios de
aceptación se separan con `|` y son la materia prima del QA.

### `01-analisis/matriz-brechas.csv`

```csv
id_hu,flujo,modelo_odoo,objeto_config,clasificacion,esfuerzo,riesgo,nota
HU-014,ventas,product.pricelist,Lista mayorista,estandar,S,bajo,...
HU-021,ventas,sale.order,Aprobación por margen,desarrollo,M,medio,...
```

`clasificacion` ∈ `estandar` | `parametrizable` | `desarrollo` | `integracion` |
`fuera_de_alcance`. Es la clasificación la que decide si la HU genera plantilla de carga, tarea de
configuración o una OT de desarrollo aparte.

### `03-blueprint/blueprint.yaml`

```yaml
proyecto: acme
prefijo_xmlid: adv_acme
compania:
  nombre: ACME SpA
  pais: CL
  moneda: CLP
  localizacion: [l10n_cl, l10n_cl_edi]   # [VERIFICAR] nombres reales en la instancia
objetos:
  - modelo: product.category
    fuente: plantilla          # plantilla | configuracion | derivado
    cantidad_estimada: 25
    depende_de: []
    hu: [HU-014, HU-031]
  - modelo: account.journal
    fuente: configuracion
    depende_de: [account.account, l10n_latam.document.type]
    hu: [HU-052]
```

`fuente: plantilla` genera archivo para el consultor. `configuracion` la ejecuta un agente directo
por RPC. `derivado` lo crea Odoo solo (ej. variantes desde atributos) y **no debe cargarse a mano**.

### `04-backlog/tareas.yaml`

```yaml
- id: T-012
  titulo: Cargar categorías de producto
  tipo: carga            # analisis | configuracion | carga | desarrollo | qa
  flujo: ventas
  modelo: product.category
  depende_de: [T-004]
  agente: A5             # o "humano:<nombre>" para completar plantillas
  entradas: [06-completadas/27_product.category.csv]
  salidas: [08-carga/bitacora-product.category.jsonl]
  dod: "Todas las filas con xmlid resuelto y 0 errores en 07-validacion"
```

### `09-qa/casos.yaml`

```yaml
- id: QA-007
  hu: [HU-014]
  flujo: ventas
  descripcion: Cotización a cliente mayorista aplica lista de precios
  pasos:
    - modelo: sale.order
      metodo: create
      args_ref: fixtures/so_mayorista.yaml
    - modelo: sale.order
      metodo: action_confirm
  aserciones:
    - "order.pricelist_id.xmlid == adv_acme.pricelist_mayorista"
    - "order.amount_total == 119000"
    - "len(order.picking_ids) == 1"
```

## Plantillas: CSV + sidecar `.meta.json`

**Decisión de este despliegue.** El contrato original usaba `.xlsx` con hoja oculta `_meta`,
desplegables y comentarios en cabecera. `openpyxl` no está en el entorno del server, así que las
plantillas son **CSV con las cabeceras nativas del importador de Odoo** más un sidecar JSON que
transporta lo que la hoja `_meta` llevaba. Odoo importa CSV nativamente y `load()` acepta las mismas
cabeceras, así que el contrato de fondo (idempotencia por xmlid) no cambia.

`05-plantillas/NN_<modelo>.csv`:

```csv
id,name,vat,l10n_cl_sii_taxpayer_type,property_account_position_id/id
adv_acme.partner_761234567,ACME SpA,76.123.456-7,1,
```

`05-plantillas/NN_<modelo>.meta.json`:

```json
{
  "modelo": "res.partner",
  "prefijo_xmlid": "adv_acme",
  "version_plantilla": "1.0",
  "generado": "2026-08-10",
  "orden_carga": 20,
  "obligatorios": ["id", "name", "vat"],
  "catalogos": { "l10n_cl_sii_taxpayer_type": ["1", "2", "3", "4"] },
  "referencias": { "property_account_position_id/id": "13_account.fiscal.position.csv" },
  "fila_ejemplo": 2,
  "introspeccion_fecha": "2026-08-10",
  "odoo_version": "19.0"
}
```

`fila_ejemplo` es el número de línea (1-indexado sobre el CSV incluyendo cabecera) que contiene el
ejemplo; el validador la ignora. Las desplegables se sustituyen por `catalogos` en el sidecar +
la sección correspondiente del `INSTRUCTIVO.md`: el validador rechaza el valor fuera de catálogo con
`E220`, así que la restricción sigue existiendo, solo se aplica más tarde.

`NN` es la posición en el orden de carga (ver `orden-de-carga-odoo`). El número es parte del
contrato: el cargador procesa por orden alfabético de archivo y así el orden queda garantizado sin
lógica extra. Ejemplos: `20_res.partner.csv`, `31_product.template.csv`, `64_mrp.bom.csv`.

## Esquema del `context` de la sesión

**No hay campo de estado.** El avance NO se representa con un enum ni con `agente_actual`: lo lleva
el Task Manager. El `context` transporta solo datos de dominio; los campos con ruta apuntan a
archivos, no incrustan contenido.

```json
{
  "sesion_id": "uuid",
  "proyecto": {
    "nombre": "acme",
    "prefijo_xmlid": "adv_acme",
    "ruta_proyecto": "proyecto",
    "flujos": ["ventas", "contabilidad"]
  },
  "instancia": {
    "entorno": "staging|production|development",
    "odoo_version": "19.0|null",
    "introspeccion_fecha": "iso8601|null",
    "modulos_faltantes": ["string"],
    "confianza": "alta|media|baja"
  },
  "rutas": {
    "matriz_brechas": "01-analisis/matriz-brechas.csv",
    "introspeccion": "02-instancia/introspeccion.json",
    "blueprint": "03-blueprint/blueprint.yaml",
    "backlog": "04-backlog/tareas.yaml",
    "plantillas": "05-plantillas/",
    "completadas": "06-completadas/",
    "validacion": "07-validacion/",
    "carga": "08-carga/",
    "qa": "09-qa/"
  },
  "pendientes": [
    {
      "id": "P-001",
      "origen": "A1|A2|A3|A4|A5",
      "motivo": "modulo_faltante|campo_inexistente|clasificacion_dudosa|referencia_no_resuelta|regla_negocio|entorno_produccion|otro",
      "pregunta": "string",
      "opciones": ["string"],
      "referencia": { "archivo": "string", "fila": 0, "columna": "string" },
      "respuesta": "string|null",
      "respondido_por": "string|null",
      "respondido_en": "iso8601|null"
    }
  ],
  "alertas": ["string"],
  "resultado_carga": {
    "archivos_ok": 0,
    "archivos_error": 0,
    "registros_creados": 0,
    "registros_actualizados": 0,
    "bitacoras": ["08-carga/bitacora-res.partner.jsonl"]
  },
  "resultado_qa": {
    "casos_total": 0,
    "casos_ok": 0,
    "casos_fallidos": [{ "id": "QA-007", "motivo": "string" }]
  }
}
```

## Propiedad de campos

| Campo / artefacto | Quién escribe | Quién solo lee |
|---|---|---|
| Paso siguiente (NO es campo: es el `assign_task`) | Solo el Coordinador | — |
| `01-analisis/*`, `02-instancia/*`, `instancia.*` | A1 (Analiza e Introspecciona) | A2, A3, A4, A5 |
| `02-instancia/capacidades-instancia.json` | A1 lo crea; **A5 le agrega** (única excepción a la regla dura) | A2, A3, A4 |
| `03-blueprint/*`, `04-backlog/*`, `proyecto.prefijo_xmlid` | A2 (Blueprint y Backlog) | A3, A4, A5 |
| `05-plantillas/*` | A3 (Genera Plantillas) | consultor humano, A4 |
| `06-completadas/*` | **El consultor humano** (único punto no-agente) | A4, A5 |
| `07-validacion/*` | A4 (Valida Archivos) | A5, Coordinador |
| `08-carga/*`, `09-qa/*`, `resultado_carga`, `resultado_qa` | A5 (Carga y QA) | Coordinador |
| `pendientes[]` (en el resultado) | Cualquier worker con duda; Coordinador consolida | — |
| Trazabilidad (registro durable + console) | Todos, solo agregando eventos | — |

## Regla de oro

Un worker no decide el avance: devuelve su resultado y el Coordinador abre el `assign_task`
siguiente. Un worker produce solo el resultado natural de su rol (A2 entrega blueprint y backlog; no
decide "ya se pueden generar plantillas"). Si detecta algo que no sabe resolver, escribe un pendiente
estructurado y devuelve el control — nunca salta ni delega a otro worker.

## Casos de borde

- **Falta un campo del esquema**: no lo agregues por tu cuenta; el contrato debe evolucionar acá,
  explícitamente.
- **Dos agentes tocan el mismo artefacto en turnos distintos**: la tabla de propiedad resuelve la
  ambigüedad. Quien enriquece un archivo ajeno siempre lo relee con `fileRead` antes de escribir,
  para partir del contenido vigente y no de una copia obsoleta en `context`.
- **`context` pesado**: nunca incrustes la introspección ni el CSV completo; pasa la ruta y abre con
  `fileRead`.
- **El consultor no ha devuelto `06-completadas/`**: NO es un error del pipeline. El Coordinador
  informa y espera; es el único punto donde el proceso se detiene por una persona.
