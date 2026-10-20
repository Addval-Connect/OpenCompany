---
name: contrato-implementacion-odoo
description: Fuente única de verdad del layout de archivos del proyecto — qué dato vive dónde, su forma y quién lo escribe.
allowed-tools: odoo_jsonrpc
metadata:
  author: opencompany
  version: "1.0"
  category: compartidos

---

# Contrato de implementación Odoo

Fuente única de verdad sobre dónde vive cada dato, qué forma tiene y quién lo escribe. Solo datos: los procedimientos viven en los skills de etapa y de coordinación. Si falta un campo, no lo agregues por tu cuenta: el contrato evoluciona aquí, explícitamente.

## Agentes

Coordinador · D0 · cuatro agentes de flujo (`financiero`, `ventas_servicios`, `compras_aprobaciones`, `inventario_fabricacion`) · CARGA. Un worker no decide el avance: devuelve su resultado y el Coordinador abre la tarea siguiente. Si no sabe resolver algo, escribe una definición abierta y devuelve el control; nunca salta ni delega.

## Dónde vive la sesión

1. **`task_manager`**: delegación y estados de tarea (`queued → running → submitted → accepted`). Es el único registro del avance de las tareas.
2. **Archivos bajo `proyecto/`**: artefactos y definiciones. Son la autoridad sobre si un punto de control está cerrado.
3. **`proyecto/coordinador/estado.json`**: solo hilos de correo y autorización de producción (ver más abajo).

El `context` de una tarea lleva solo rutas y datos livianos, nunca contenido de archivos.

## Carpetas

**Raíz del proyecto.** Este flujo es multiproyecto: cada implementación vive en su propia carpeta
`proyectos/<proyecto>/`, donde `<proyecto>` es el slug que el Coordinador fija al abrir el proyecto y
registra en `proyectos/index.json`. **Toda ruta de este contrato es relativa a esa raíz.** El
`<proyecto>` activo viaja en el `context` de cada misión; un agente que no lo reciba devuelve
`detenida_por_precondicion` y no escribe nada. Al llamar a la herramienta `data`, antepone siempre
`proyectos/<proyecto>/` a la ruta: `data` con path `01-analisis/x.md` es un error — la ruta correcta
es `proyectos/<proyecto>/01-analisis/x.md`. Los scripts lanzados con `process_manager` reciben la raíz
del proyecto como argumento o la derivan de su cwd; nunca adivinan rutas absolutas del host.

```
proyectos/
└── <proyecto>/
    ├── 00-entrada/        epicas.md, historias.csv, alcance.md
    ├── 01-analisis/       propuesta-epicas.md, propuesta-historias.csv, preguntas-descubrimiento.md,
    │                      definiciones-proyecto.md, definiciones-requeridas-<flujo>.md,
    │                      matriz-brechas-<flujo>.csv, preguntas-abiertas.md
    ├── 02-instancia/      introspeccion-<flujo>.json
    ├── 03-blueprint/      proyecto.yaml, blueprint-<flujo>.yaml, configuracion-<flujo>.yaml
    ├── 04-backlog/        tareas-<flujo>.yaml
    ├── 05-plantillas/     <modelo>.csv, <modelo>.meta.json, INSTRUCTIVO-<flujo>.md
    ├── 06-completadas/    <modelo>.csv (llenadas por el consultor)
    ├── 07-validacion/     informe-<modelo>.md, errores-<modelo>.csv, veredicto-<flujo>.json
    ├── 08-carga/          plan-carga.json, estado-carga.json, bitacora-<modelo>.jsonl,
    │                      resumen-carga.md, capacidades-instancia.json
    ├── 09-qa/             casos-<flujo>.yaml, resultados-<flujo>.md, evidencia/
    └── coordinador/       estado.json, jev-log.jsonl
```

Los números de carpeta son el orden del proceso, no una jerarquía. **Los nombres de archivo de plantilla no llevan prefijo `NN`**: el orden de carga sale del grafo `depende_de`. Si llega un archivo con prefijo, se ignora.

## Propiedad

| Ruta | Escribe | Lee |
|---|---|---|
| `00-entrada/*` | Coordinador (transcribe lo validado por el consultor) | todos |
| `01-analisis/propuesta-*`, `preguntas-descubrimiento.md` | D0 | Coordinador, flujos |
| `01-analisis/definiciones-proyecto.md` | D0 (las preguntas); Coordinador (transcribe las respuestas) | todos |
| `01-analisis/*-<flujo>.*` | agente del flujo | Coordinador, otros flujos |
| `01-analisis/preguntas-abiertas.md` | cualquiera, **solo en append** | Coordinador |
| `02-instancia/introspeccion-<flujo>.json` | agente del flujo | todos |
| `03-blueprint/proyecto.yaml` | Coordinador (transcribe respuestas de G0) | todos |
| `03-blueprint/*-<flujo>.yaml`, `04-backlog/tareas-<flujo>.yaml` | agente del flujo | Coordinador, CARGA |
| `05-plantillas/*`, `09-qa/casos-<flujo>.yaml` | agente del flujo | consultor, CARGA |
| `06-completadas/*` | Coordinador (transcribe las respuestas del consultor) | flujos, CARGA |
| `07-validacion/*` | agente del flujo dueño del modelo | CARGA, Coordinador |
| `08-carga/*`, `09-qa/resultados-*`, `09-qa/evidencia/*` | CARGA | todos |
| `coordinador/*` | Coordinador | — |

**Regla dura: un agente nunca escribe en un archivo que no es suyo.** Si necesita corregir algo aguas arriba, escribe una entrada en `preguntas-abiertas.md` y devuelve el control. Quien enriquece un archivo propio relee antes de escribir (`data`), para partir del contenido vigente. No hay excepciones: `capacidades-instancia.json` lo escribe solo CARGA.

**Modelos compartidos.** Cada modelo tiene un único dueño declarado en `proyecto.yaml` → `duenos_modelos`. Un flujo que necesita columnas de un modelo ajeno las pide con `requiere_de`; no plantilla el modelo.

## Obsolescencia

Todo artefacto de agente trae `version: N` (el dueño la incrementa en cada cambio). Todo artefacto derivado trae `basado_en: {<ruta>: <version>}`. Si la versión vigente de una fuente es mayor que la registrada, el derivado está **vencido**: se re-delega la etapa que lo produjo. Los CSV lo llevan en su `.meta.json`.

## Esquemas

### Definición (pregunta al consultor)

Un solo formato para G0, G1 y G2, en el archivo de definiciones del punto. Se numera `D-NN` por archivo y no se renumera nunca. La cita lleva el flujo: `D-03 (financiero)`.

```markdown
## D-01 · <motivo> · BLOQUEANTE
pregunta: ¿Se usa el plan de cuentas que instaló l10n_cl, o se carga uno propio?
opciones: (a) El de l10n_cl  (b) Uno propio (adjuntar)  (c) El de l10n_cl con cuentas adicionales
referencia: 02-instancia/introspeccion-financiero.json, account.account
propuesta: quedarse con el plan de l10n_cl y crear solo las cuentas adicionales que el cliente exija
respuesta:
respondido_por:
respondido_en:
```

`motivo` ∈ `modulo_faltante` | `campo_inexistente` | `clasificacion_dudosa` | `referencia_no_resuelta` | `regla_negocio` | `entorno_produccion` | `alcance_no_declarado` | `xmlid_empresa_faltante` | `constraint_cuenta_resultado` | `modelo_sin_dueno` | `definicion_requerida` | `otro`. El enum crece aquí.

### `03-blueprint/proyecto.yaml`

```yaml
proyecto: acme
version: 1
prefijo_xmlid: adv_acme            # aprobado literalmente en G0; inmutable tras la primera carga
entorno_objetivo: staging          # staging | production | development
base_datos: <nombre>
rama: staging
odoo_version: "19.0"
compania: {nombre: ACME SpA, pais: CL, moneda: CLP, localizacion: [l10n_cl]}   # [VERIFICAR] nombres reales
flujos_en_alcance: [financiero, ventas_servicios]
sub_alcance: {financiero: [contabilidad, tesoreria, facturacion]}
duenos_modelos: {account.account: financiero, res.partner: ventas_servicios, product.template: inventario_fabricacion}
```

### `03-blueprint/blueprint-<flujo>.yaml`

```yaml
flujo: financiero
version: 3
basado_en: {"01-analisis/definiciones-requeridas-financiero.md": 2}
objetos:
  - modelo: account.journal
    fuente: configuracion          # plantilla | configuracion | derivado
    ancla: true                    # pertenece al núcleo contable
    depende_de: [account.account]  # modelos que deben estar cargados antes
    requiere_de: []                # pedidos a otros flujos: [{flujo, modelo, columna}]
    hu: [HU-052]
    cantidad_estimada: 6
acepta_pedidos:                    # respuestas a pedidos de otros flujos (se escriben en el blueprint del dueño)
  - {de_flujo: ventas_servicios, modelo: res.partner, columna: property_account_receivable_id/id, decision: aceptado, nota: ""}
```

`plantilla` genera archivo para el consultor; `configuracion` la ejecuta CARGA por RPC con los valores de `configuracion-<flujo>.yaml`; `derivado` lo crea Odoo solo y no se carga. El grafo de `depende_de` debe ser acíclico.

### `03-blueprint/configuracion-<flujo>.yaml`

```yaml
flujo: financiero
version: 1
basado_en: {"03-blueprint/blueprint-financiero.yaml": 3}
registros:
  - modelo: res.company
    id: adv_acme.company_acme
    accion: enlazar_y_actualizar     # crear | actualizar | enlazar_y_actualizar
    valores: {name: ACME SpA}
ajustes:                              # res.config.settings; solo group_*, nunca module_*
  - {campo: group_analytic_accounting, valor: true}
```

### `04-backlog/tareas-<flujo>.yaml`

```yaml
- id: T-012
  titulo: Cargar categorías de producto
  tipo: carga            # analisis | configuracion | carga | desarrollo | qa
  modelo: product.category
  depende_de: [T-004]
  agente: carga          # o "humano:<nombre>" para completar plantillas
  entradas: [06-completadas/product.category.csv]
  salidas: [08-carga/bitacora-product.category.jsonl]
  dod: "Todas las filas con xmlid resuelto y 0 errores en 07-validacion"
```

### `00-entrada/historias.csv` y `01-analisis/matriz-brechas-<flujo>.csv`

```csv
id_hu,epica,flujo,titulo,como,quiero,para,criterios_aceptacion,prioridad
```

`flujo` ∈ `financiero` | `ventas_servicios` | `compras_aprobaciones` | `inventario_fabricacion`. Los criterios se separan con `|` y son la materia prima del QA.

```csv
id_hu,flujo,modelo_odoo,objeto_config,clasificacion,esfuerzo,riesgo,nota
```

`clasificacion` ∈ `estandar` | `parametrizable` | `desarrollo` | `integracion` | `fuera_de_alcance`. Decide si la HU genera plantilla, configuración o una OT aparte.

### Plantillas

`05-plantillas/<modelo>.csv` con cabeceras nativas del importador, más `<modelo>.meta.json`:

```json
{
  "modelo": "res.partner", "prefijo_xmlid": "adv_acme", "version_plantilla": "1.0",
  "obligatorios": ["id", "name", "vat"],
  "catalogos": {"l10n_cl_sii_taxpayer_type": ["1", "2", "3", "4"]},
  "referencias": {"property_account_position_id/id": "account.fiscal.position.csv"},
  "fila_ejemplo": 2, "introspeccion_fecha": "2026-08-10", "odoo_version": "19.0",
  "basado_en": {"03-blueprint/blueprint-ventas_servicios.yaml": 2}
}
```

`INSTRUCTIVO-<flujo>.md` declara quién llena qué columnas de cada archivo.

### `07-validacion/veredicto-<flujo>.json`

```json
{"flujo": "financiero", "version": 2, "basado_en": {"05-plantillas/account.account.meta.json": 1},
 "archivos": [{"archivo": "account.account.csv", "modelo": "account.account",
               "veredicto": "cargable", "errores": 0,
               "informe": "07-validacion/informe-account.account.md"}]}
```

`veredicto` ∈ `cargable` | `con_errores` | `detenido`. CARGA solo carga lo `cargable`, y lee este archivo, no el resultado de un turno.

### `09-qa/casos-<flujo>.yaml`

```yaml
- id: QA-007
  hu: [HU-014]
  flujo: ventas_servicios
  descripcion: Cotización a cliente mayorista aplica lista de precios
  pasos:
    - {modelo: sale.order, metodo: create, valores: {partner_id_xmlid: adv_acme.partner_761234567, order_line: []}}
    - {modelo: sale.order, metodo: action_confirm}
  aserciones:
    - "pricelist_id == adv_acme.pricelist_mayorista"
    - "amount_total == 119000"
```

Lo escribe el agente del flujo (conoce el dominio); CARGA solo lo ejecuta, en staging.

### Carpeta `08-carga/`

Escribe solo CARGA. `estado-carga.json` tiene un objeto por archivo con `estado` ∈ `pendiente` | `cargado` | `diferido` | `parcial` | `detenido`. `capacidades-instancia.json` acumula lo aprendido de esta instancia (claves: `metodos_bloqueados`, `remapeos_confirmados`, `campos_inexistentes`, `valores_confirmados`, `xmlids_resueltos`, `xmlids_inexistentes`, `modulos`, `ajustes_aplicados`, `reglas_de_xmlid`, `scripts`, `lote_optimo`, `resultado_ultimo_ensayo`); solo se agregan entradas y solo `resultado_ultimo_ensayo` se sobrescribe. El esquema detallado vive en el skill de carga.

**Ancla contable cumplida** = todos los objetos con `ancla: true` están `cargado` en `estado-carga.json`, con read-back correcto en `resumen-carga.md`, en el entorno de ensayo (staging).

### `coordinador/estado.json`

```json
{"sesion_id": "uuid", "empresa": "acme",
 "consultores_autorizados": ["consultor@cliente.cl"],
 "mensajes_procesados": ["<message_id>"],
 "hilos": [{"id": "H-001", "message_id": "...", "asunto": "...", "punto": "G1",
            "flujos": ["financiero"], "items": ["D-01 (financiero)"],
            "enviado_en": "iso8601", "respondido": false}],
 "autorizacion_produccion": null}
```

`consultores_autorizados` se fija al arrancar el proyecto, con las direcciones que entrega quien lo lanza; si está vacía, el Coordinador no actúa sobre ninguna respuesta y lo reporta. `mensajes_procesados` evita procesar dos veces un mismo correo. No guarda el estado de los puntos de control ni del ancla: eso se lee de los archivos.

### `context` de una tarea

```json
{"sesion_id": "uuid", "empresa": "acme", "ruta_proyecto": "proyecto", "flujo": "financiero",
 "mision": "Cerrar G1", "ronda": 1,
 "rutas": {"definiciones": "01-analisis/definiciones-requeridas-financiero.md"},
 "respuestas": [{"id": "D-03", "respuesta": "...", "respondido_por": "...", "respondido_en": "iso8601"}]}
```

`rutas` lleva solo lo que esa misión necesita. `respuestas` aparece solo en misiones de cierre.

## Casos de borde

- **Falta un campo del esquema:** no lo agregues; escribe una definición abierta de motivo `otro`.
- **Dos agentes tocan el mismo artefacto:** la tabla de propiedad lo resuelve. Si un modelo no tiene dueño en `proyecto.yaml`, es una definición `modelo_sin_dueno`.
- **`context` pesado:** nunca incrustes introspección ni CSV; pasa la ruta.
- **El consultor no ha devuelto las plantillas:** no es un error del pipeline; el Coordinador informa y espera.
- **Un xmlid mal asignado:** no se edita una plantilla; es una tarea explícita del backlog con confirmación humana.
