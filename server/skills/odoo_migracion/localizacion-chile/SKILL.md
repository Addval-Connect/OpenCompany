---
name: localizacion-chile
description: Lo que cambia al migrar contabilidad en Chile (l10n_cl) — RUT, folios, IVA, códigos de cuenta y paquete fiscal.
allowed-tools: odoo_jsonrpc
metadata:
  author: addval
  version: "1.0"
  category: odoo_migracion

---

# Localización Chile

Lo que cambia al implementar Odoo en Chile (`l10n_cl`). Lo cargan el Analista, el Transformador, el Auditor y CARGA. Reúne lo que estaba disperso en los runbooks genéricos: RUT, folios, IVA, códigos de cuenta y el paquete fiscal.

**Regla de procedencia.** Cada hecho de Odoo lleva su estado: `[observado en proyecto]` (visto en una instancia o proyecto anterior, sin fecha) o `[conocimiento general]` (del régimen tributario, no de Odoo). Un hecho de Odoo nunca se usa sin confirmarlo con `fields_get` o `ir.model.data` en la instancia real. Los nombres de módulo (`l10n_cl`, `l10n_cl_edi`) también son `[VERIFICAR]` hasta ver su `state`.

## RUT

`[conocimiento general]`

- **En el xmlid:** sin puntos ni guion, **con** dígito verificador: `76.123.456-7` → `761234567`. El DV es parte de la clave; omitirlo colisiona con otro RUT válido.
- **En el campo `vat`:** el consultor lo escribe como lo muestra Odoo. Respeta lo que la instancia acepta.
- **Cálculo del DV** (módulo 11), para *sugerir* el correcto en un mensaje de error: multiplica los dígitos del cuerpo, de derecha a izquierda, por 2, 3, 4, 5, 6, 7 y vuelve a 2; suma; calcula `11 - (suma mod 11)`; 11 es `0`, 10 es `K`. Ejemplo: cuerpo `76123456` → DV `7`.

`[observado en proyecto]` Con `l10n_cl` instalado, Odoo valida el DV **al escribir**: un DV incorrecto rechaza la fila entera aunque el resto esté perfecto, y el mensaje habla de formato aunque el formato esté bien. Por eso el validador solo rechaza un DV si la instancia lo aplica (`taxonomia-errores-odoo`: `E210`); y siempre sugiere el candidato.

## Tipo de contribuyente

`[observado en proyecto]` El campo es `l10n_cl_sii_taxpayer_type` (no `l10n_cl_taxpayer_type`) y sus claves son strings `1` a `4`. No confundirlo con `res.partner.type` (`contact`, `invoice`, `delivery`, `other`): una columna `type` llena con `1` es una columna intoxicada (`bucle-de-correccion`).

## El paquete fiscal y sus xmlids

`[observado en proyecto]`

- Los registros que crea un paquete de localización al aplicarse (cuentas, impuestos, diarios, posiciones fiscales) **no llevan el xmlid del módulo**: llevan `account.<id_de_compañía>_<clave_de_la_plantilla>`. En una instancia observada, el IVA 19% de venta es `account.1_ITAX_19` y el de compra `account.1_OTAX_19`; **`l10n_cl.tax_vat_19_sale` no existe ni va a existir**. Los nombres exactos dependen de la compañía y de la versión: confírmalos.
- **Un `E300` sobre un `l10n_*.<algo>` no es automáticamente un módulo ausente.** Buscarlo en `ir.module.module` confirma que `l10n_cl` está instalado y deja el problema donde estaba.
- **Contraejemplo, para no sobreaplicar la regla:** `l10n_cl.it_RUT` sí existe. Que un xmlid empiece con `l10n_*` no lo hace sospechoso; lo que importa es si el modelo destino lo crea la plantilla contable.

### Resolver un xmlid de la localización

Búsqueda semántica en el modelo destino, no una variante del nombre:

```
# 1. el registro, por lo que lo define funcionalmente
model="account.tax", method="search_read",
domain=[["amount","=",19],["type_tax_use","=","sale"]], fields=["name","amount","type_tax_use"]

# 2. su xmlid, por res_id
model="ir.model.data", method="search_read",
domain=[["model","=","account.tax"],["res_id","=",<id>]], fields=["module","name"]
```

**El match tiene que ser único.** Un candidato: úsalo y regístralo en `xmlids_resueltos` con la vía. Varios: **definición `referencia_no_resuelta` con la lista de candidatos (nombre y xmlid de cada uno)**, no el primero. `[observado en proyecto]` El IVA 19% de compra convive con varios IVAs de regímenes especiales (activo fijo, uso común, no recuperable, supermercado): elegir el equivocado produce una contabilidad que cuadra y está mal.

## Impuestos y país fiscal

`[observado en proyecto]` Odoo rechaza usar o editar un impuesto cuyo `country_id` no coincide con el `account_fiscal_country_id` de la compañía. Un impuesto "19%" preexistente de antes de la localización queda inutilizable: el que sirve es el del paquete.

## Aplicar el paquete fiscal (decisión humana)

`[observado en proyecto]`

- El paquete **solo se aplica con la contabilidad virgen** (cero `account.move`). Aplicarlo no es reversible sin restaurar la base: **nunca lo apliques sin confirmación explícita, y jamás en producción.**
- La llamada, para cuando esa confirmación existe, es `account.chart.template` / `try_loading` con `args=[[], "<codigo>", <company_id>]` y `kwargs={"install_demo": false}`. El primer posicional se consume como `ids`, así que `args=["cl", 1]` falla con `missing 1 required positional argument: 'company'`.
- Esta llamada no es parte del bucle de carga: es un paso con definición explícita (`D-NN`) aprobada por el consultor.

## Plan de cuentas

`[observado en proyecto]`

- **Código de cuenta:** `account.account.code` solo acepta alfanumérico y puntos. `1-1-2-05` se rechaza; el candidato obvio es `1.1.2.05`, pero **cambiar el plan de cuentas del cliente es decisión del consultor**: repórtalo con el candidato, no lo apliques.
- **Una sola cuenta de resultado del ejercicio por compañía.** Odoo solo permite **una** cuenta de tipo "resultado del ejercicio en curso" (`equity_unaffected` según la versión observada). `l10n_cl` la instala automáticamente; si el CSV trae otra, `load()` rechaza el batch completo con `There can only be one account of type…`. Antes de cargar `account.account`, un `search_read` por ese tipo: si ya hay una, esa fila del CSV es un conflicto y se resuelve con el consultor (excluirla del archivo, o reclasificarla), nunca reintentando.
- **Compañía de la cuenta:** el CSV casi siempre la referencia con un xmlid del proyecto (`adv_<proyecto>.company_<slug>`). Si ese xmlid no existe, `load()` es transaccional y **todo el batch de 200 a 500 cuentas se cae**. Verifícalo en `ir.model.data` antes de cargar. Si falta, es una definición `xmlid_empresa_faltante` con la propuesta ya lista: enlazar el xmlid a la empresa principal con un `ir.model.data.create` (`{module, name, model: "res.company", res_id}`) **previa confirmación del consultor de que ese `res_id` es la empresa correcta**. No inventes un xmlid ni uses `base.main_company` en su lugar. El mismo problema afecta a analíticos y diarios (`company_ids/id`, `company_id/id`): un solo pendiente agrupa todos los modelos afectados.

## Documentos tributarios y folios

`[observado en proyecto]` Los casos de borde de la localización incluyen: comuna como texto libre donde va una entidad; tipo de documento sin diario; folios (CAF) ausentes. **El error de folios no parece de configuración**: el mensaje habla de secuencia, no de CAF. Reconócelo y dilo con esas palabras al escalarlo.

## Qué validar y qué no

El validador solo rechaza lo que la instancia rechaza. Las validaciones locales (DV de RUT, formato de código de cuenta) se aplican **solo si** esta instancia las aplica; si no, una fila con ese dato entra, y rechazarla sería bloquear una carga correcta. En duda, haz la prueba contra staging con una fila, no supongas.

## Nunca

- Aplicar el paquete fiscal sin confirmación explícita, ni en producción.
- Elegir un impuesto entre varios candidatos "por ser el primero".
- Cambiar el código de una cuenta por tu cuenta para que pase.
- Crear un xmlid de empresa o enlazarlo a un `res_id` sin confirmación del consultor.
- Concluir "módulo ausente" por un `E300` sobre un xmlid `l10n_*` sin haber buscado por dominio.
