---
name: contrato-migracion
description: Fuente única de verdad del layout de archivos del flujo de migración — qué dato vive dónde, su forma y quién lo escribe.
allowed-tools: odoo_jsonrpc
metadata:
  author: addval
  version: "1.0"
  category: odoo_migracion

---

# Contrato del flujo de migración

Fuente única de verdad sobre dónde vive cada dato, qué forma tiene y quién lo escribe en el **flujo de migración contable a Odoo 19**. Este flujo es independiente de cualquier otro sistema de implementación: parte de una instancia de Odoo que ya tiene su configuración contable base. Solo datos; los procedimientos viven en los skills de cada agente. Si falta un campo, no lo agregues por tu cuenta: el contrato evoluciona aquí, explícitamente.

## Agentes

| Agente | Función | Escribe en Odoo |
|---|---|---|
| Coordinador de Migración | Programa tareas, habla con el consultor, verifica | no |
| Analista de Migración | Entiende el formato de origen, mide su calidad, diseña el mapeo | no |
| Transformador de Migración | Convierte el origen en lotes listos para cargar | no |
| Auditor de Migración | Valida lotes antes de cargar y prueba la cuadratura antes y después. **Independiente**: nunca construye ni carga lo que audita | no (solo lectura) |
| CARGA Migración | Único que escribe en Odoo | **sí** |

Un worker no decide el avance: devuelve su resultado y el Coordinador abre la tarea siguiente. Si detecta algo que no sabe resolver, escribe una definición abierta y devuelve el control; nunca salta ni delega.

## Dónde vive la sesión

1. **`task_manager`**: delegación y estados de tarea (`queued → running → submitted → accepted`).
2. **Archivos bajo `migracion/`**: artefactos y definiciones. Son la autoridad sobre si un punto de control está cerrado.
3. **`migracion/coordinador/estado.json`**: solo hilos de correo, remitentes autorizados, mensajes procesados y autorización de producción.

El `context` de una tarea lleva solo rutas y datos livianos, nunca contenido de archivos.

## Carpetas

```
migracion/
├── 00-entrada/       fuente/ (archivos del sistema de origen), alcance.md
├── 01-analisis/      perfil-fuente.json, calidad-fuente.json, control-fuente.json,
│                     definiciones-requeridas.md, preguntas-abiertas.md
├── 02-instancia/     introspeccion.json, preparacion-instancia.json
├── 03-diseno/        estrategia.yaml, mapeo.yaml, tareas.yaml, casos-control.yaml
├── 04-mapeos/        mapeo-*.csv, mapeo-*.meta.json, INSTRUCTIVO.md   (propuestas del Analista)
├── 05-validados/     mapeo-*.csv                                       (corregidos por el consultor)
├── 06-lotes/         scripts/transformar.py, lotes/, plan-conciliaciones.csv,
│                     manifiesto.json, rechazos-transformacion.csv
├── 07-auditoria/     veredicto.json, informe-<lote>.md, errores-<lote>.csv,
│                     cuadratura-previa.md, definiciones-auditoria.md, resultados-control.md
├── 08-carga/         plan-carga.json, estado-carga.json, bitacora-<fase>.jsonl,
│                     resumen-carga.md, capacidades-instancia.json
└── coordinador/      estado.json, jev-log.jsonl
```

Los números de carpeta son el orden del proceso, no una jerarquía.

## Propiedad

| Ruta | Escribe | Lee |
|---|---|---|
| `00-entrada/*` | Coordinador (guarda lo que entrega el consultor; **nunca abre** los archivos del origen) | Analista, Transformador |
| `01-analisis/*` (salvo `preguntas-abiertas.md`) | Analista | todos |
| `01-analisis/preguntas-abiertas.md` | cualquiera, **solo en append** | Coordinador |
| `02-instancia/*` | Analista | todos |
| `03-diseno/*`, `04-mapeos/*` | Analista | todos |
| `05-validados/*` | Coordinador (transcribe lo que devuelve el consultor) | Transformador, Auditor, CARGA |
| `06-lotes/*` | Transformador | Auditor, CARGA |
| `07-auditoria/*` | Auditor | CARGA, Coordinador |
| `08-carga/*` | CARGA | todos |
| `coordinador/*` | Coordinador | — |

**Regla dura: un agente nunca escribe en un archivo que no es suyo.** Si necesita corregir algo aguas arriba, escribe una entrada en `preguntas-abiertas.md` y devuelve el control. Quien enriquece un archivo propio lo relee antes de escribir.

## Obsolescencia

Todo artefacto de un agente trae `version: N` (el dueño la incrementa en cada cambio). Todo artefacto derivado trae `basado_en: {<ruta>: <version>}`. Si la versión vigente de una fuente es mayor que la registrada, el derivado está **vencido**: se re-delega la etapa que lo produjo. Los lotes lo llevan en `manifiesto.json`.

## Esquemas

### Definición (pregunta al consultor)

Un solo formato para todos los puntos de control. Se numera `D-NN` por archivo y no se renumera nunca.

```markdown
## D-01 · <motivo> · BLOQUEANTE
pregunta: ¿Cómo se configuran los diarios de migración para que no generen documentos tributarios?
opciones: (a) uno general  (b) uno de ventas, uno de compras y uno general
referencia: 02-instancia/introspeccion.json, account.journal
propuesta: (b), sin formato de documento electrónico ni exigencia de tipo de documento
respuesta:
respondido_por:
respondido_en:
```

`motivo` ∈ `modulo_faltante` | `campo_inexistente` | `referencia_no_resuelta` | `regla_negocio` | `entorno_produccion` | `alcance_no_declarado` | `instancia_no_preparada` | `defecto_fuente` | `columna_dudosa` | `diario_no_verificable` | `descuadre` | `aprobacion_cuadratura` | `definicion_requerida` | `otro`. El enum crece aquí.

### `03-diseno/estrategia.yaml`

```yaml
version: 1
proyecto: acme
prefijo_xmlid: adv_acme          # aprobado literalmente en P2; inmutable tras la primera carga
entorno_objetivo: staging        # staging | production | development
base_datos: <nombre>
rama: staging
odoo_version: "19.0"
sistema_origen: <nombre>
fecha_corte: <YYYY-MM-DD>
profundidad: apertura_y_ejercicio_en_curso     # apertura | apertura_y_ejercicio_en_curso | historico_n
tolerancia_cuadratura: 0
alcance: [apertura, partidas_abiertas, asientos, conciliaciones]
diarios_migracion: [{xmlid: adv_acme.journal_mig_ventas, tipo: sale}, {xmlid: adv_acme.journal_mig_general, tipo: general}]
```

### `03-diseno/mapeo.yaml`

```yaml
version: 1
basado_en: {"01-analisis/perfil-fuente.json": 2}
archivos:
  - fuente: libro_diario.csv
    tipo: libro_diario
    destino: account.move
    columnas:
      - {origen: "Nro Comprobante", destino: ref,  transformacion: texto}
      - {origen: "Fecha",           destino: date, transformacion: "fecha DD/MM/AAAA"}
      - {origen: "Debe",            destino: line_ids/debit, transformacion: "numero punto_miles coma_decimal"}
```

Todo `destino` es `[VERIFICAR]` hasta confirmarlo con `fields_get`.

### `03-diseno/tareas.yaml` y `casos-control.yaml`

`tareas.yaml`: una tarea por fase y lote, con `depende_de` y `dod`. `casos-control.yaml`: controles de cuadratura de solo lectura:

```yaml
- id: CTL-001
  descripcion: El saldo por cuenta a la fecha de corte iguala al origen
  consulta: {modelo: account.move.line, agrupar: account_id, medida: balance,
             dominio: [["date", "<=", "<corte>"], ["parent_state", "=", "posted"]]}   # [hipótesis]
  esperado_ref: 01-analisis/control-fuente.json#saldos_por_cuenta
  tolerancia: 0
  momento: posterior        # previo (contra lotes) | posterior (contra Odoo)
```

### Tablas de mapeo (`04-mapeos/`, `05-validados/`)

`mapeo-cuentas`, `mapeo-terceros`, `mapeo-impuestos`, `mapeo-diarios` y `mapeo-tipos-documento` (columnas en `dominio-migracion`). Cada una con `.meta.json`: `obligatorios`, `catalogos`, `basado_en`, `version`.

### `06-lotes/manifiesto.json`

```json
{"version": 3, "basado_en": {"05-validados/mapeo-cuentas.csv": 1, "03-diseno/mapeo.yaml": 2},
 "lotes": [{"archivo": "lotes/asientos_2025-01.csv", "conjunto": "asientos", "periodo": "2025-01",
            "asientos": 412, "lineas": 1987, "total_debe": 0, "total_haber": 0,
            "xmlid_desde": "...", "xmlid_hasta": "...", "hash": "..."}]}
```

### `07-auditoria/veredicto.json`

```json
{"version": 2, "basado_en": {"06-lotes/manifiesto.json": 3},
 "cuadratura_previa": {"estado": "cuadra | no_cuadra", "informe": "07-auditoria/cuadratura-previa.md"},
 "lotes": [{"archivo": "lotes/asientos_2025-01.csv", "veredicto": "cargable | con_errores | detenido",
            "errores": 0, "informe": "07-auditoria/informe-asientos_2025-01.md"}]}
```

CARGA solo carga lo `cargable`, y lee este archivo, no el resultado de un turno.

### `08-carga/`

Escribe solo CARGA. `estado-carga.json` tiene un objeto por fase y lote con `estado` ∈ `pendiente` | `borrador` | `verificado` | `publicado` | `conciliado` | `detenido`. `capacidades-instancia.json` acumula lo aprendido de esta instancia; solo se agregan entradas y solo `resultado_ultimo_ensayo` se sobrescribe.

### `coordinador/estado.json`

```json
{"sesion_id": "uuid", "empresa": "acme",
 "consultores_autorizados": ["consultor@cliente.cl"],
 "mensajes_procesados": ["<message_id>"],
 "hilos": [{"id": "H-001", "message_id": "...", "asunto": "...", "punto": "P2",
            "items": ["D-01"], "enviado_en": "iso8601", "respondido": false}],
 "autorizacion_produccion": null}
```

`consultores_autorizados` se fija al arrancar el proyecto; si está vacía, el Coordinador no actúa sobre ninguna respuesta. No guarda el estado de los puntos de control: eso se lee de los archivos.

### `context` de una tarea

```json
{"sesion_id": "uuid", "empresa": "acme", "ruta_proyecto": "migracion",
 "mision": "analisis", "ronda": 1,
 "rutas": {"definiciones": "01-analisis/definiciones-requeridas.md"},
 "respuestas": [{"id": "D-03", "respuesta": "...", "respondido_por": "...", "respondido_en": "iso8601"}],
 "autorizacion_produccion": null}
```

`respuestas` aparece solo en misiones de cierre. `autorizacion_produccion` (`{base_datos, rama}`) lo agrega el Coordinador **solo** en misiones de carga cuando `entorno_objetivo` es `production`, tras verificar la respuesta del consultor.

## Casos de borde

- **Falta un campo del esquema:** no lo agregues; escribe una definición `otro`.
- **El consultor no ha devuelto los archivos o mapeos:** no es un error del pipeline; el Coordinador informa y espera.
- **Un archivo de origen cambia:** `perfil-fuente`, `control-fuente`, el mapeo y todo lo derivado quedan vencidos; se re-delega desde `analisis`.
- **Un xmlid mal asignado:** no se edita un lote; es una tarea explícita con confirmación humana.
