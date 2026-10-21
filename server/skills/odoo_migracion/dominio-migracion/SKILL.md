---
name: dominio-migracion
description: Conocimiento de dominio de la migración contable a Odoo 19: alcance, fases de carga, preguntas P2, tablas de mapeo y controles de cuadratura.
allowed-tools: odoo_jsonrpc
metadata:
  author: addval
  version: "1.0"
  category: odoo_migracion

---

# Dominio: migración contable a Odoo

Conocimiento de dominio del flujo de migración: traspasar la contabilidad histórica de un sistema de origen a Odoo hasta dejar la instancia migrada. Lo cargan el Analista, el Transformador, el Auditor y CARGA. Los procedimientos están en los skills de cada agente.

**Regla de procedencia.** Todo hecho de Odoo lleva su estado: `[hipótesis]` (no verificado en una instancia; se confirma con `fields_get` o con una fila de prueba en staging antes de usarlo) o `[conocimiento general]` (de contabilidad, no de Odoo). Los nombres de campo y de método de este skill son hipótesis: `fields_get` es la única autoridad.

## 1. Alcance

Cubre: saldos de apertura, partidas abiertas, asientos y movimientos de diario, documentos de compra y venta, conciliaciones, y los controles de cuadratura que prueban que la instancia quedó migrada. Sub-alcances declarables: `apertura`, `partidas_abiertas`, `asientos`, `conciliaciones`.

**Parte de una instancia con su configuración contable base ya hecha** (compañía, localización, plan de cuentas, impuestos). Este flujo **no** la configura: la verifica (`preparacion-instancia.json`) y, si falta algo, lo reporta como `instancia_no_preparada`. Lo único que crea por sí mismo, con aprobación del consultor, son los objetos propios de la migración: los **diarios de migración**, las **cuentas faltantes** del mapeo y los **terceros** que no existan.

No cubre: inventario físico (cantidades y ubicaciones), activos fijos como módulo, ni integración continua con el origen. Solo migra sus **saldos contables**.

**Principio rector: lo migrado no es tributario.** Ningún documento migrado genera un documento tributario electrónico, consume folios ni se informa al SII. Se carga en diarios de migración configurados para eso, y se verifica antes y después de cargar.

## 2. Mapa de datos y fases de carga

| Fase | Qué se carga | Modelo `[hipótesis]` | Cómo |
|---|---|---|---|
| `preparacion` | Diarios de migración, cuentas faltantes, terceros faltantes | `account.journal`, `account.account`, `res.partner` | `load()` con xmlid, con aprobación previa |
| `apertura` | Asiento de apertura con los saldos por cuenta | `account.move` | `load()` en borrador |
| `partidas_abiertas` | Documentos de compra y venta con saldo, o sus partidas por tercero | `account.move` | `load()` en borrador |
| `historicos` | Asientos del período migrado, por período | `account.move` | `load()` en borrador |
| `conciliaciones` | Conciliación de líneas ya publicadas | `account.partial.reconcile` / `account.full.reconcile` | Las crea Odoo al ejecutar la conciliación; no se cargan |

Archivos de trabajo (no son modelos de Odoo): `mapeo-cuentas`, `mapeo-terceros`, `mapeo-impuestos`, `mapeo-diarios`, `mapeo-tipos-documento`.

## 3. Preguntas de indagación mínimas (P2)

Cada una se copia al cuestionario con el formato del contrato. `BLOQUEANTE` detiene el diseño.

| # | Pregunta | Opciones | Propuesta por defecto | Qué se rompe si se supone |
|---|---|---|---|---|
| 1 | **(BLOQUEANTE)** ¿Qué sistema es el origen y entregan todos los archivos de todos los períodos? | lista por archivo | pedir una muestra de cada archivo | Se diseña contra un formato supuesto |
| 2 | **(BLOQUEANTE)** ¿Cuál es la fecha de corte y cuándo se congela el origen? | fecha | último día de un período cerrado | Las cifras no cuadran porque el origen siguió moviéndose |
| 3 | **(BLOQUEANTE)** ¿Qué profundidad se migra? | (a) solo apertura y partidas abiertas (b) apertura más asientos del ejercicio en curso (c) N ejercicios | (b) | Se carga historia que nadie consulta, o se pierde la que sí |
| 4 | **(BLOQUEANTE)** La instancia, ¿tiene ya configurados compañía, localización, plan de cuentas e impuestos? | sí / falta algo | verificar en la introspección | Los asientos apuntan a cuentas o impuestos que no existen |
| 5 | **(BLOQUEANTE)** ¿Cómo se configuran los diarios de migración para que **no** generen documentos tributarios ni consuman folios? | (a) uno general (b) uno de ventas, uno de compras y uno general | (b) | Un documento migrado se informa al SII: no se deshace |
| 6 | ¿Cómo se cargan los documentos de compra y venta? | (a) como asientos del diario de migración, con tercero y vencimiento (b) como documentos en un diario sin facturación electrónica | (a) | Folios consumidos o conciliaciones imposibles |
| 7 | ¿Qué documentos se migran? | (a) solo con saldo abierto (b) todos los del período | (a) | Cuentas por cobrar y pagar que no cuadran con el auxiliar |
| 8 | Ejercicios cerrados en el origen | (a) sin cierre, solo resultados acumulados (b) con asiento de cierre | (a) | Resultado duplicado o ausente |
| 9 | Impuestos | (a) importar los montos como vienen, sin recalcular (b) recalcular en Odoo | (a) | Diferencias de centavos que rompen la cuadratura |
| 10 | Terceros: ¿los de la instancia se emparejan por RUT y los faltantes se crean? | (a) crear los faltantes (b) detener hasta que existan | (a) | Líneas contra un tercero equivocado, o terceros duplicados |
| 11 | Terceros sin RUT, duplicados o con RUT inválido | (a) crear con identificador provisorio y reportar (b) detener hasta corregir en el origen | (b) para inválidos, (a) para sin RUT | Líneas contra el tercero equivocado |
| 12 | Cuentas del origen sin equivalente en Odoo | (a) crearlas (b) mapearlas a una cuenta puente | (a) | Saldos en una cuenta que nadie revisa |
| 13 | **(BLOQUEANTE)** Inventario y activos fijos: ¿cómo entra su saldo contable para no duplicarse si el stock o los activos se cargan por otra vía? | (a) solo el saldo contable por apertura, y el stock sin valorización contable (b) el stock se valoriza en el diario de migración y esas cuentas se excluyen de la apertura | sin default sin ver el origen | El balance duplica el inventario |
| 14 | ¿Las conciliaciones vienen identificadas en el origen? | (a) usar las del origen (b) reconstruirlas por reglas y confirmarlas (c) solo partidas abiertas sin conciliar | (c) para lo histórico, (a) si el origen las trae | Conciliaciones inventadas |
| 15 | Moneda extranjera y UF | por archivo | monto en moneda local, más moneda y tipo de cambio del origen | Cuadratura en pesos pero no en moneda original |
| 16 | ¿Desde qué fecha se bloquean los períodos migrados? | fecha | el corte, tras aprobar la cuadratura | Alguien edita un asiento migrado |
| 17 | **(BLOQUEANTE)** Ensayo y reversa: ¿se ensaya en staging desde cero y se migra a producción solo con respaldo previo? | confirmar | sí | Una publicación errónea solo se deshace restaurando la base |
| 18 | Tolerancia de cuadratura | monto | 0 pesos | Diferencias aceptadas sin criterio |

## 4. Decisiones de diseño (P3)

Orden de las fases; granularidad de lotes (por período, un asiento nunca se parte); estrategia de publicación (borrador → verificación → publicación); esquema de xmlid y de referencia del asiento; propiedades de los diarios de migración; qué terceros y cuentas se crean; controles de cuadratura que son criterio de aceptación; qué queda fuera por diseño.

## 5. Tablas de mapeo y quién las valida

El Analista las propone; el consultor y el contador del cliente las **corrigen y validan**.

| Archivo | Columnas | Quién valida |
|---|---|---|
| `mapeo-cuentas` | `cuenta_origen`, `nombre_origen`, `cuenta_odoo_xmlid`, `estado` (`propuesto` / `confirmado` / `sin_equivalente`) | Contador |
| `mapeo-terceros` | `rut_origen`, `nombre_origen`, `partner_xmlid`, `coincidencia` (`exacta` / `sin_rut` / `duplicado` / `invalido`) | Contador |
| `mapeo-impuestos` | `codigo_origen`, `impuesto_odoo_xmlid` | Contador |
| `mapeo-diarios` | `tipo_comprobante_origen`, `diario_odoo_xmlid` | Consultor |
| `mapeo-tipos-documento` | `tipo_documento_origen`, `descripcion`, `tratamiento` | Contador |

## 6. Controles de cuadratura

La migración se acepta por cuadratura contra el origen. Cada control es un caso de `casos-control.yaml` con `momento`: `previo` (lotes contra la fuente) o `posterior` (Odoo contra la fuente).

| # | Control | Momento | Esperado |
|---|---|---|---|
| C1 | Saldo por cuenta a la fecha de corte | previo y posterior | Igual al balance de comprobación del origen (tolerancia de P2) |
| C2 | Partidas abiertas por tercero en cuentas por cobrar y por pagar | previo y posterior | Igual al auxiliar del origen |
| C3 | Cada asiento balanceado; debe y haber globales y por período | previo y posterior | Diferencia cero |
| C4 | Conteo de asientos y documentos por período | previo y posterior | Igual al manifiesto |
| C5 | Todos publicados y solo en diarios de migración | posterior | Cero fuera de ellos |
| C6 | Documentos electrónicos generados y folios consumidos | posterior | Cero |
| C7 | Conciliaciones: residual cero en lo conciliado; abiertas = esperadas | posterior | Igual al plan |
| C8 | Recargar un lote en borrador no cambia los conteos | posterior (solo ensayo) | Sin cambios |
| C9 | Muestra de asientos al azar comparada línea por línea con el origen | posterior | Sin diferencias |

## 7. Particularidades de Chile

- **Terceros.** Se emparejan por RUT normalizado (sin puntos ni guion, con dígito verificador), igual que el xmlid (`localizacion-chile`). Un RUT inválido es un dato a corregir en el origen, no a "arreglar" al migrar.
- **Números.** `[conocimiento general]` Los sistemas locales suelen exportar con punto de miles y coma decimal, y fechas `DD/MM/AAAA`. Se detecta por archivo en el perfilado; nunca se asume.
- **UF y moneda extranjera.** Se conserva el monto original, la moneda y el tipo de cambio del origen cuando existan.
- **SII.** `[conocimiento general]` Los libros de compras y ventas de períodos ya declarados siguen siendo los del origen: la migración no los regenera ni reemite nada. El folio del documento original, si el origen lo trae, se conserva solo como referencia de texto, nunca como folio de Odoo `[por confirmar con el consultor]`.
- **Retenciones y PPM.** Entran como líneas contables en sus cuentas, sin recalcularse.

## 8. Trampas conocidas

Todas `[hipótesis]`: confírmalas en staging con una fila de prueba antes de diseñar sobre ellas.

| Qué se espera | Qué podría pasar | Cómo se detecta |
|---|---|---|
| Que un diario no genere documentos electrónicos | Que tenga un formato electrónico activo y publicar dispare su generación | Leer la configuración del diario antes de cargar; control C6 después |
| Que `name` del asiento sea el número de origen | Que Odoo asigne su secuencia al publicar y la consuma | Fila de prueba en staging |
| Que los impuestos de una línea no se recalculen | Que Odoo recalcule y cambie los montos | Cuadratura por lote antes de publicar |
| Poder publicar con cualquier fecha | Que las fechas de bloqueo rechacen períodos antiguos | Leer las fechas de bloqueo de la compañía antes de cargar |
| Que un asiento publicado se pueda borrar | Que no: la reversa es un asiento inverso o restaurar la base | Regla de diseño: nunca publicar sin cuadratura verificada |
| Que cargar miles de líneas publicadas sea rápido | Timeouts | Lotes por período y `lote_optimo` |
| Conciliar cualquier par de líneas | Que Odoo exija misma cuenta, misma compañía y cuenta conciliable | Plan de conciliaciones validado por cuenta |
| Que una carga parcial se pueda reintentar | Que un asiento ya publicado no se pueda recargar | `estado-carga.json`: un lote `publicado` no se toca |
