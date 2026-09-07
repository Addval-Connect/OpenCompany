---
name: scripts-verificados-de-carga-odoo
description: >-
  Los scripts ya probados que convierten un CSV completado en el payload de load() sin prueba y error:
  derivan la cabecera contra fields_get, aplican los remapeos y xmlids ya aprendidos, y apartan las
  filas que Odoo va a rechazar. Copialos tal cual; no los reescribas.
allowed-tools: sandboxed_python odoo_jsonrpc file_read
metadata:
  agente: TODOS
  tipo: DET
  prioridad: P0
  uso: referencia_compartida
  icon: "\U0001F9E9"
  author: addval
  version: "1.0"
  category: odoo_impl
---

# Scripts verificados de carga

Esta skill existe para que **no razones la mecanica**. Derivar la cabecera, decidir si una columna
relacional lleva `/id`, traducir una clave de `selection`, calcular un digito verificador: todo eso es
codigo, no criterio, y re-derivarlo en cada turno es de donde salio la mayor parte del costo de las
corridas anteriores.

**Regla: el script se copia, no se escribe.** El bloque de abajo esta verificado contra el interprete
real (`pydantic-monty`, el que corre detras de `sandboxed_python`) sobre archivos reales de este
proyecto. Si lo reescribes "mejor", vuelves a pagar el ciclo que esta skill evita. Lo unico que cambias
son las **tres primeras lineas**.

Tu criterio se gasta en lo que el script no puede decidir: si un match ambiguo es un pendiente, si un
`E400` es regla de negocio, a quien le toca corregir. Eso sigue siendo tuyo.

## La secuencia fija, por archivo

No la reordenes ni te saltes pasos; cada uno existe porque su ausencia produjo un fallo real.

```
1. una vez por modelo:  odoo_jsonrpc  fields_get  ->  guardalo en 05-plantillas/campos-<modelo>.json
2. por archivo:         sandboxed_python  S1  ->  {fields, data, avisos, filas_a_apartar...}
3. lee "avisos" y "descartes_columna" ANTES de llamar a Odoo
4. quita de "data" las filas de "filas_a_apartar_antes_de_enviar"  (son rechazos garantizados)
5. odoo_jsonrpc  load  con fields y data
6. si vuelve "messages":  sandboxed_python  S2  ->  reenvia el lote sin las filas rechazadas
7. read-back de 2-3 xmlids del lote, y segunda corrida para probar idempotencia
```

El paso 1 es la unica autoridad sobre que campos existen. El paso 3 es el que convierte un ciclo humano
en un informe: un `E210` de RUT o de codigo de cuenta lo detectas **antes** de escribir, no cuando Odoo
rechaza la fila.

## S1 — de CSV completado a payload de `load()`

`sandboxed_python` con `capabilities: ["workspace_read"]`.

Que hace, y por que cada parte esta ahi:

| Hace | Porque |
|---|---|
| `xmlid` / `id` -> `id` | sin esa columna la carga duplica en cada corrida |
| Decide `campo/id` vs `campo` **mirando el valor** | `/id` sobre `CPO/Stock` da `No matching record found for external id`, que parece referencia faltante y es cabecera equivocada |
| Aplica `remapeos_confirmados` de `capacidades-instancia.json` | `company_id`->`company_ids`, `category_ids`->`category_id`, `payment_term_id`->`property_payment_term_id`: ya se pagaron una vez |
| Aplica `xmlids_resueltos` | resuelve solo `l10n_cl.tax_vat_19_sale`->`account.1_ITAX_19`, `base.state_cl_at`->`base.state_cl_03`, `uom.product_uom_litr`->`uom.product_uom_litre` |
| Aplica `valores_confirmados` | `delivery_steps: one_step`->`ship_only`, y **deja** `reception_steps: one_step` porque ahi si es valido |
| `type=product` -> `consu` + columna `is_storable` | en 19 `product` no existe |
| Calcula el DV del RUT (modulo 11) y emite el correcto | un DV malo rechaza la fila entera con un mensaje que habla de formato |
| Marca el codigo de cuenta con guiones y propone el candidato | `1-1-2-05` se rechaza; `1.1.2.05` entra |
| Detecta el `l10n_*` que **no va a existir** | ver abajo: es el `E300` que no se ve venir |
| Chequea `required` **de la instancia** y el prefijo del xmlid | el `required` de la plantilla puede estar viejo |
| Descarta la columna que no existe en `fields_get` y **lo dice** | descartarla en silencio pierde datos que el consultor cree entregados |

Lo que **no** hace, a proposito: no adivina. Un valor fuera del `selection` que no este en
`valores_confirmados` sale como aviso `E220` **con la lista completa de claves** para que decidas; un
codigo de 2-3 caracteres no se resuelve por parecido.

### El `E300` que no se ve venir: `l10n_*` que si tiene forma de xmlid valido

`l10n_cl.tax_withholding_fees` pasa cualquier chequeo de forma y **no existe**, asi que sin este aviso
el rechazo aparece recien en el `load`, ya con el lote tumbado.

La regla no es "todo `l10n_*` es sospechoso" — eso da falsos positivos. Verificado contra la instancia,
`l10n_cl` **si** posee sus propios registros (58 `l10n_latam.document.type`, 32 `res.bank`, 3
`l10n_latam.identification.type`: `l10n_cl.it_RUT` existe y es correcto) y posee **cero** en
`account.tax`, `account.account`, `account.journal` y `account.fiscal.position`. Esos ultimos no los crea
el modulo: los crea la **plantilla contable** al aplicarse, con xmlid `account.<id_de_compañia>_<clave>`.

Por eso el script decide por el **modelo relacionado del campo** (`relation` de `fields_get`), no por el
prefijo del valor: si apunta a uno de los modelos de `GENERADOS_POR_PLANTILLA` y el valor es `l10n_*`,
sale en `xmlids_por_resolver_antes_de_enviar` con el modelo destino. **Resuelvelo por dominio antes de
llamar a `load`** (procedimiento en `odoo-rpc-en-opencompany` → `E300` sobre un xmlid de la
localizacion), y anota el resultado en `xmlids_resueltos` para que la proxima corrida lo sustituya sola.

```python
# =========== PARAMETROS: las 3 lineas que cambias por archivo ===========
ARCHIVO = "06-completadas/product.template.csv"
MODELO = "product.template"
PREFIJO = "ecominera"
# ========================================================================
import json
import re

def leer(ruta):
    f = open("/workspace/" + ruta)
    raw = f.read()
    f.close()
    return raw

def parse_csv(raw):
    rows = []
    row = []
    cell = ""
    inq = False
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if inq:
            if ch == '"':
                if i + 1 < n and raw[i + 1] == '"':
                    cell = cell + '"'
                    i = i + 2
                    continue
                inq = False
                i = i + 1
                continue
            cell = cell + ch
            i = i + 1
            continue
        if ch == '"':
            inq = True
            i = i + 1
            continue
        if ch == ',':
            row.append(cell)
            cell = ""
            i = i + 1
            continue
        if ch == '\n':
            row.append(cell)
            rows.append(row)
            row = []
            cell = ""
            i = i + 1
            continue
        if ch == '\r':
            i = i + 1
            continue
        cell = cell + ch
        i = i + 1
    if cell != "" or len(row) > 0:
        row.append(cell)
        rows.append(row)
    return rows

def dv_rut(cuerpo):
    s = 0
    mul = 2
    i = len(cuerpo) - 1
    while i >= 0:
        s = s + int(cuerpo[i]) * mul
        mul = mul + 1
        if mul > 7:
            mul = 2
        i = i - 1
    r = 11 - (s % 11)
    if r == 11:
        return "0"
    if r == 10:
        return "K"
    return str(r)

# modelos cuyos registros los crea la plantilla contable (xmlid account.<id_compania>_<clave>),
# no el modulo l10n_*: verificado contra la instancia, l10n_cl posee 0 xmlids en estos modelos
GENERADOS_POR_PLANTILLA = ["account.tax", "account.account", "account.journal", "account.fiscal.position", "account.group", "account.tax.group"]

ES_XMLID = re.compile(r"^[a-z0-9_]+\.[A-Za-z0-9_.\-]+$")

campos = json.loads(leer("05-plantillas/campos-" + MODELO + ".json"))["campos"]

remap = {}
xmlmap = {}
selmap = {}
try:
    cap = json.loads(leer("02-instancia/capacidades-instancia.json"))
except Exception:
    cap = {}
for e in cap.get("remapeos_confirmados", []):
    if e.get("modelo") == MODELO and e.get("campo") in campos:
        remap[e.get("cabecera")] = e.get("campo")
for e in cap.get("xmlids_resueltos", []):
    real = e.get("real") or ""
    if ES_XMLID.match(real) and " " not in real:
        xmlmap[e.get("buscado")] = real
for e in cap.get("valores_confirmados", []):
    if e.get("modelo") == MODELO and e.get("de"):
        selmap[e.get("campo") + "\t" + e.get("de")] = e.get("a")

rows = parse_csv(leer(ARCHIVO))
cabecera = rows[0]
filas = []
for r in rows[1:]:
    lleno = False
    for v in r:
        if v.strip() != "":
            lleno = True
    if lleno:
        filas.append(r)

avisos = []
descartes = []
remapeos = []
fields = []
usar = []

j = 0
while j < len(cabecera):
    col = cabecera[j].strip()
    if col == "xmlid" or col == "id":
        fields.append("id")
        usar.append(j)
        if col != "id":
            remapeos.append({"de": col, "a": "id", "motivo": "la columna del xmlid se llama id en el payload"})
        j = j + 1
        continue
    real = col
    if col not in campos and col in remap:
        real = remap[col]
        remapeos.append({"de": col, "a": real, "motivo": "remapeo confirmado en capacidades-instancia"})
    if real not in campos:
        descartes.append({"columna": col, "motivo": "no existe en fields_get de " + MODELO})
        j = j + 1
        continue
    tipo = campos[real].get("type")
    if tipo == "many2one" or tipo == "many2many":
        conxmlid = 0
        total = 0
        k = 0
        while k < len(filas):
            v = filas[k][j].strip() if j < len(filas[k]) else ""
            if v != "":
                total = total + 1
                primero = v.split(",")[0].strip()
                if xmlmap.get(primero):
                    primero = xmlmap[primero]
                if ES_XMLID.match(primero):
                    conxmlid = conxmlid + 1
            k = k + 1
        if total == 0:
            fields.append(real)
        elif conxmlid == total:
            fields.append(real + "/id")
        else:
            fields.append(real)
            if conxmlid > 0:
                avisos.append({"columna": col, "codigo": "E300?", "detalle": f"{conxmlid} de {total} valores parecen xmlid y el resto no: la columna va sin /id y Odoo buscara por nombre. Revisa las filas mixtas."})
    else:
        fields.append(real)
    usar.append(j)
    j = j + 1

obligatorios = []
for k in campos:
    if campos[k].get("required"):
        obligatorios.append(k)

data = []
apartar = []
por_resolver = []
extra_storable = []
necesita_storable = False

i = 0
while i < len(filas):
    r = filas[i]
    fila_csv = i + 2
    salida = []
    storable = ""
    p = 0
    while p < len(usar):
        j = usar[p]
        f = fields[p]
        base = f.split("/")[0]
        v = r[j].strip() if j < len(r) else ""
        if base != "id" and v != "":
            clave = selmap.get(base + "\t" + v)
            if clave:
                v = clave
            elif xmlmap.get(v):
                v = xmlmap[v]
            elif "," in v and (f.endswith("/id")):
                partes = []
                for x in v.split(","):
                    x = x.strip()
                    partes.append(xmlmap.get(x) or x)
                v = ",".join(partes)
            sel = campos.get(base, {}).get("selection")
            if sel:
                claves = []
                for par in sel:
                    claves.append(par[0])
                if v not in claves:
                    if base == "type" and MODELO == "product.template" and v == "product":
                        v = "consu"
                        storable = "1"
                        necesita_storable = True
                    else:
                        avisos.append({"fila": fila_csv, "columna": base, "valor": v, "codigo": "E220",
                                       "detalle": "no esta en el selection", "claves": claves})
            rel = campos.get(base, {}).get("relation") or ""
            if v.startswith("l10n_") and ES_XMLID.match(v) and rel in GENERADOS_POR_PLANTILLA:
                if v not in por_resolver:
                    por_resolver.append(v)
                    avisos.append({"columna": base, "valor": v, "modelo_destino": rel, "codigo": "E300",
                                   "detalle": "lo genera la plantilla contable, no el modulo: su xmlid es account.<id_compania>_<clave> y este l10n_* no existe. Resuelvelo por dominio en " + rel + " antes de enviar",
                                   "corrige": "agente"})
            if base == "vat" and re.match(r"^[0-9\.]+-[0-9kK]$", v):
                cuerpo = v.split("-")[0].replace(".", "")
                esperado = dv_rut(cuerpo)
                if esperado != v.split("-")[1].upper():
                    avisos.append({"fila": fila_csv, "columna": "vat", "valor": v, "codigo": "E210",
                                   "detalle": "DV invalido; el correcto es " + esperado, "corrige": "consultor"})
                    if fila_csv not in apartar:
                        apartar.append(fila_csv)
            if base == "code" and MODELO == "account.account" and not re.match(r"^[A-Za-z0-9\.]+$", v):
                avisos.append({"fila": fila_csv, "columna": "code", "valor": v, "codigo": "E210",
                               "detalle": "solo alfanumerico y puntos; candidato " + v.replace("-", "."),
                               "corrige": "consultor"})
                if fila_csv not in apartar:
                    apartar.append(fila_csv)
        if base == "id" and v != "" and not v.startswith(PREFIJO + "."):
            avisos.append({"fila": fila_csv, "columna": "id", "valor": v, "codigo": "E210",
                           "detalle": "el xmlid no lleva el prefijo " + PREFIJO})
        if base in obligatorios and v == "":
            avisos.append({"fila": fila_csv, "columna": base, "codigo": "E200",
                           "detalle": "obligatorio en la instancia y viene vacio", "corrige": "consultor"})
            if fila_csv not in apartar:
                apartar.append(fila_csv)
        salida.append(v)
        p = p + 1
    extra_storable.append(storable)
    data.append(salida)
    i = i + 1

if necesita_storable and "is_storable" in campos:
    fields.append("is_storable")
    i = 0
    while i < len(data):
        data[i].append(extra_storable[i])
        i = i + 1
    remapeos.append({"de": "type=product", "a": "type=consu + is_storable", "motivo": "en 19 'product' no existe"})

resultado = {
    "modelo": MODELO,
    "archivo": ARCHIVO,
    "fields": fields,
    "data": data,
    "filas": len(data),
    "remapeos": remapeos,
    "descartes_columna": descartes,
    "avisos": avisos,
    "filas_a_apartar_antes_de_enviar": apartar,
    "xmlids_por_resolver_antes_de_enviar": por_resolver,
    "obligatorios_del_modelo": obligatorios,
}
json.dumps(resultado)
```

Salida (todo lo que necesitas para el paso siguiente, sin volver a abrir el archivo):

```json
{"modelo": "product.template", "fields": ["id", "name", "categ_id/id", "type", "...", "is_storable"],
 "data": [["ecominera.product_tmpl_diesel", "Diesel", "ecominera.product_category_combustible",
           "consu", "uom.product_uom_litre", "1100.00", "950.00", "lot",
           "account.1_ITAX_19", "account.1_OTAX_19", "1"]],
 "filas": 5, "remapeos": [{"de": "type=product", "a": "type=consu + is_storable", "motivo": "..."}],
 "descartes_columna": [], "avisos": [{"columna": "supplier_taxes_id", "modelo_destino": "account.tax",
   "valor": "l10n_cl.tax_withholding_fees", "codigo": "E300", "detalle": "...", "corrige": "agente"}],
 "filas_a_apartar_antes_de_enviar": [], "xmlids_por_resolver_antes_de_enviar": ["l10n_cl.tax_withholding_fees"],
 "obligatorios_del_modelo": ["name", "type", "uom_id", "tracking"]}
```

`fields` y `data` van tal cual a `odoo_jsonrpc` con `method="load"`. **No los edites en el prompt**: si
algo esta mal, esta mal en `capacidades-instancia.json` o en el `campos-<modelo>.json`, y ahi se
corrige — asi la correccion sirve para la proxima corrida y no solo para esta.

## S2 — cuarentena despues de un `load` con `messages`

`load()` es transaccional: si el lote trajo errores, **no entro nada**, asi que hay que reenviarlo sin
las filas rechazadas. Pega los `messages` que devolvio Odoo en `MENSAJES` y el script te dice que
reenviar. Es aritmetica sobre datos que ya tienes en contexto, asi que va sin capabilities.

```python
# ===== pega aqui los messages de Odoo y las filas que enviaste =====
MENSAJES = [{"record": 3, "field": "categ_id", "message": "No matching record found for external id 'x'"}]
FILAS_ENVIADAS = 5
OBLIGATORIAS = ["id", "name"]
# ===================================================================
import json

por_columna = {}
filas_malas = []
for m in MENSAJES:
    r = m.get("record")
    if r is not None and r not in filas_malas:
        filas_malas.append(r)
    c = m.get("field") or ""
    if c != "":
        por_columna[c] = por_columna.get(c, 0) + 1

columna_a_descartar = ""
for c in por_columna:
    if por_columna[c] >= FILAS_ENVIADAS and c.split("/")[0] not in OBLIGATORIAS:
        columna_a_descartar = c

if columna_a_descartar != "":
    accion = "cuarentena de columna: quita '" + columna_a_descartar + "' de fields y de cada fila de data, y reenvia el lote COMPLETO"
else:
    accion = "cuarentena de filas: quita los indices " + json.dumps(sorted(filas_malas)) + " de data (0-based, tal como los reporta Odoo) y reenvia el resto"

json.dumps({"accion": accion, "filas_rechazadas_0based": sorted(filas_malas),
            "filas_csv": [r + 2 for r in sorted(filas_malas)],
            "columna_a_descartar": columna_a_descartar,
            "rechazos_por_columna": por_columna})
```

La distincion que hace este script es la que importa: **si todas las filas rechazan la misma columna no
obligatoria, el defecto es de la columna**, y cargar el archivo sin ella salva el archivo completo en vez
de perderlo. Si son filas sueltas, apartas filas. Confundir los dos casos cuesta un archivo entero o un
atributo, segun para que lado te equivoques.

`record` es un indice **0-based del lote**; la fila del CSV es `record + 2` (cabecera + base 1). Reporta
siempre la fila del CSV, que es la que el consultor puede abrir.

## Despues de cargar: alimenta el aprendizaje

Cada cosa que el script tuvo que aprender de ti va a `02-instancia/capacidades-instancia.json`
(`remapeos_confirmados`, `valores_confirmados`, `xmlids_resueltos`, `campos_inexistentes`,
`ajustes_aplicados`). No es documentacion: es **entrada del script**. Un remapeo anotado ahi se aplica
solo en la proxima corrida, y por eso el archivo vale mas que cualquier resumen en prosa.

Lo que NO va: criterio funcional (eso es un pendiente), y nada que no hayas verificado contra esta
instancia en esta corrida.

## Nunca

- No reescribas los scripts. Estan verificados contra el interprete real; una variante "equivalente"
  no lo esta.
- No edites `fields` / `data` a mano en el prompt. Corrige la fuente (`capacidades-instancia.json` o
  `campos-<modelo>.json`) para que la correccion persista.
- No llames a `load` sin haber leido `avisos`. Los `E210` y `E200` son rechazos garantizados: enviarlos
  gasta una llamada y un lote.
- No uses `javascript_code` ni `python_code` para abrir el CSV: ninguno de los dos ve el disco.
- No trates un aviso `E220` con lista de claves como si el script hubiera fallado. Es el script
  negandose a adivinar, que es lo correcto.
