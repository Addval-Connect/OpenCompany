---
name: analiza-brechas-e-introspecciona
description: >-
  Runbook completo del Agente A1: lee épicas e historias de 00-entrada/, clasifica cada HU en la
  matriz de brechas, e introspecciona la instancia real de Odoo (versión, módulos, campos) para
  producir la única autoridad sobre qué existe. Ejecuta los pasos en orden y no vuelvas al
  Coordinador entre ellos.
allowed-tools: odoo_jsonrpc file_read file_modify fs_search javascript_code
metadata:
  agente: A1
  tipo: MIX
  prioridad: P0
  siguiente_agente: COORD
  icon: "🔍"
  author: addval
  version: "1.0"
  category: odoo_impl
---

# Analizar brechas e introspeccionar (runbook A1)

Dos trabajos que van juntos porque uno sin el otro no sirve: qué pide el cliente
(`01-analisis/`) y qué tiene realmente la instancia (`02-instancia/`). El segundo es la **única
autoridad** sobre campos y módulos para todo el resto del proyecto — ninguna lista escrita en una
referencia lo es, incluida cualquiera de estas skills.

Lee `contrato-implementacion-odoo`, `convencion-ids-externos` y `odoo-rpc-en-opencompany` antes de
empezar. Del flujo del proyecto, abre solo la referencia que corresponde
(`flujos-de-referencia` → `read_resource`), más `l10n-cl.md` si el país es CL.

Escribes en `01-analisis/` y `02-instancia/`. **En ninguna otra carpeta.**

## Paso 1 — Leer la entrada

`fs_search` en `00-entrada/` y `file_read` de `historias.csv`, `epicas.md` y `alcance.md`. Si
`historias.csv` no tiene la cabecera del contrato
(`id_hu,epica,flujo,titulo,como,quiero,para,criterios_aceptacion,prioridad`), no lo interpretes a la
fuerza: devuelve un pendiente `otro` con la cabecera que sí encontraste.

Verifica que cada HU tenga `flujo` ∈ `ventas` | `compras` | `inventario` | `fabricacion` |
`contabilidad`. Una HU sin flujo válido no se puede clasificar contra ninguna referencia: pendiente
`clasificacion_dudosa`.

## Paso 2 — Introspeccionar la instancia (antes de clasificar)

El orden importa: clasificar una HU como `estandar` requiere saber que el módulo que la cubre está
instalado. Cuatro consultas, en bloque, con `fields` mínimos:

```
1. Versión:  model="ir.module.module", method="search_read",
             domain=[["name","=","base"]], fields=["latest_version"]

2. Módulos:  model="ir.module.module", method="search_read",
             domain=[["state","=","installed"]], fields=["name","shortdesc"]

3. Campos:   model="<cada modelo del alcance>", method="fields_get", args=[[]],
             kwargs={"attributes":["type","required","selection","relation","string"]}

4. Modelos:  model="ir.model", method="search_read",
             domain=[["model","in",[<modelos del alcance>]]], fields=["model","name"]
```

La consulta 3 es la cara: un `fields_get` devuelve cientos de campos. **No la hagas para todos los
modelos del universo** — solo para los que las referencias del flujo listan como objetos de
configuración o de carga. Y **cachea inmediatamente**: escribe el resultado a
`02-instancia/introspeccion.json` con `file_modify` y en los pasos siguientes lee del archivo, no
repitas la consulta. Cada resultado de tool se queda en el historial y se re-lee en cada iteración.

Si `common.login` falla: **no pruebes otro host.** El nodo tiene el host correcto por diseño; el
problema es base de datos, usuario o API key. Pendiente `otro`, y termina — sin introspección no hay
nada que clasificar con confianza.

`02-instancia/introspeccion.json`:

```json
{
  "fecha": "2026-08-10",
  "odoo_version": "19.0",
  "base_datos": "acme-staging-19",
  "entorno": "staging",
  "modelos": {
    "res.partner": {
      "existe": true,
      "campos": {
        "vat": {"type": "char", "required": false, "string": "Tax ID"},
        "l10n_cl_sii_taxpayer_type": {"type": "selection", "selection": [["1","VAT Affected"],["2","Fees"]]}
      }
    },
    "l10n_cl_edi.caf": {"existe": false}
  }
}
```

`02-instancia/modulos-instalados.json`: la lista plana de `name` instalados. Los dos archivos por
separado porque el segundo se consulta mucho más seguido y es mucho más chico.

### `02-instancia/capacidades-instancia.json` — lo que esta instancia permite

Tercer archivo, y el más chico de los tres. Tú lo **creas**; A5 lo **acumula** durante la carga. Es la
memoria de lo que ya se probó contra *esta* instancia, para que ninguna corrida vuelva a descubrirlo:

```json
{
  "instancia": {"host_alias": "ecominera-staging", "odoo_version": "19.0", "actualizado": "2026-08-10"},
  "metodos_bloqueados": [
    {"llamada": "ir.module.module.get_module_info", "mensaje": "cannot be called remotely", "visto": "2026-08-10"}
  ],
  "remapeos_confirmados": [],
  "campos_inexistentes": [],
  "lote_optimo": null
}
```

Al introspeccionar, llénalo con lo que ya sabes de esta instancia: la versión, y cualquier método que
te haya devuelto `cannot be called remotely` (`E520`). `remapeos_confirmados`, `campos_inexistentes` y
`lote_optimo` los escribe A5; tú los dejas vacíos, no los omitas — un archivo con las cuatro claves
presentes se puede leer sin defensas.

**Es un registro de hechos de esta instancia, no una regla general.** No escribas en él nada que no
hayas verificado contra la instancia en esta corrida, y no lo uses para guardar criterio (eso va a
`01-analisis/preguntas-abiertas.md`). Si algo de acá resulta cierto en varios proyectos, quien lo
promueve a una skill compartida es una persona, no el pipeline.

## Paso 3 — Clasificar las brechas

Una fila de `01-analisis/matriz-brechas.csv` por HU. La clasificación es la decisión de A1 y determina
todo lo que viene después:

| `clasificacion` | Significa | Consecuencia aguas abajo |
|---|---|---|
| `estandar` | Odoo lo hace sin configurar nada más allá de los datos | Plantilla de carga |
| `parametrizable` | Se logra configurando (reglas, campos, vistas de Studio) | Tarea de configuración |
| `desarrollo` | Requiere código | OT aparte, **no** entra en el blueprint de carga |
| `integracion` | Requiere hablar con otro sistema | OT aparte |
| `fuera_de_alcance` | No se hace en este proyecto | Se documenta y se cierra |

```csv
id_hu,flujo,modelo_odoo,objeto_config,clasificacion,esfuerzo,riesgo,nota
HU-014,ventas,product.pricelist,Lista mayorista,estandar,S,bajo,Requiere l10n_cl para impuestos
HU-021,ventas,sale.order,Aprobación por margen,desarrollo,M,medio,No hay regla estándar sobre margen calculado
```

Reglas al clasificar:

- **`estandar` exige que el módulo esté instalado**, verificado contra `modulos-instalados.json`. Si
  no lo está, sigue siendo `estandar` pero levantas un pendiente `modulo_faltante`: la decisión de
  instalarlo es del consultor, no tuya.
- **`estandar` exige que el campo exista**, verificado contra `introspeccion.json`. Un campo que la
  referencia del flujo menciona pero `fields_get` no reporta es un pendiente `campo_inexistente`.
  Marca la fila con `[VERIFICAR]` en la nota.
- Una HU puede generar **varias filas** si toca varios modelos. Una fila por (HU, modelo).
- `esfuerzo` ∈ `S` | `M` | `L`. `riesgo` ∈ `bajo` | `medio` | `alto`. Riesgo alto es lo que puede
  obligar a rehacer trabajo: saldos iniciales, impuestos, folios.
- **No inventes la clasificación de una HU ambigua.** Pendiente `clasificacion_dudosa` con las
  opciones viables. Una HU mal clasificada como `estandar` se descubre en la carga, cuando ya hay
  plantillas hechas.

Escribe también:

- `01-analisis/supuestos.md` — lo que asumiste para poder clasificar, explícito. Es lo primero que
  A2 debe cuestionar.
- `01-analisis/preguntas-abiertas.md` — el bitácora de observaciones. **Esta es la carpeta donde
  cualquier agente aguas abajo deja una observación sobre el análisis**, así que su formato importa:
  una entrada por línea, con fecha, origen y texto.

## Paso 4 — Evaluar la confianza

Antes de devolver, califica `instancia.confianza`. El Coordinador la usa para decidir si A2 puede
diseñar:

- **`alta`** — todos los modelos del alcance introspeccionados, todos los módulos requeridos
  instalados, cero `campo_inexistente`.
- **`media`** — algún campo `[VERIFICAR]` sin resolver, o un módulo faltante que el consultor puede
  instalar. A2 puede diseñar marcando esos objetos.
- **`baja`** — no se pudo introspeccionar, o faltan módulos centrales del alcance. **A2 no debe
  diseñar**: un blueprint sobre una instancia mal leída se cae completo en la carga y hay que rehacer
  las plantillas.

Sé conservador. Declarar `alta` con dudas abiertas ahorra un ciclo de consulta y cuesta una
regeneración completa de plantillas.

## Salida (un resultado al COORD)

```json
{
  "instancia": {
    "entorno": "staging",
    "odoo_version": "19.0",
    "introspeccion_fecha": "2026-08-10",
    "modulos_faltantes": ["l10n_cl_edi"],
    "confianza": "media"
  },
  "brechas": {
    "total_hu": 62,
    "por_clasificacion": {"estandar": 41, "parametrizable": 9, "desarrollo": 7, "integracion": 3, "fuera_de_alcance": 2},
    "modelos_involucrados": ["res.partner", "product.template", "account.tax"],
    "riesgo_alto": ["HU-052", "HU-058"]
  },
  "rutas": {
    "matriz_brechas": "01-analisis/matriz-brechas.csv",
    "introspeccion": "02-instancia/introspeccion.json",
    "modulos": "02-instancia/modulos-instalados.json",
    "capacidades": "02-instancia/capacidades-instancia.json"
  },
  "pendientes": [
    {"id": "P-001", "origen": "A1", "motivo": "modulo_faltante",
     "pregunta": "l10n_cl_edi no está instalado y HU-052..HU-058 lo requieren. ¿Se instala en staging o queda fuera de alcance?",
     "opciones": ["Instalar en staging", "Fuera de alcance"],
     "referencia": {"archivo": "01-analisis/matriz-brechas.csv", "fila": 52, "columna": "clasificacion"},
     "respuesta": null, "respondido_por": null, "respondido_en": null}
  ]
}
```

## Nunca

- No diseñes el blueprint. Clasificas y reportas qué hay; el diseño es de A2.
- No escribas en Odoo. A1 es solo lectura; el único punto de escritura es A5.
- No declares un campo como existente porque la referencia del flujo lo menciona. La autoridad es
  `fields_get`.
- No incrustes la introspección completa en el resultado — pasa la ruta.
- No repitas un `fields_get` que ya cacheaste en `introspeccion.json`.
