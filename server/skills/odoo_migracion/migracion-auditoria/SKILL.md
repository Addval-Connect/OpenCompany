---
name: migracion-auditoria
description: Runbook del Auditor: validación de lotes (estructura, referencias, diarios de migración) y cuadratura previa y posterior — solo lectura; reporta y no corrige.
allowed-tools: odoo_jsonrpc process_manager data
metadata:
  author: addval
  version: "1.0"
  category: odoo_migracion

---

# Auditor · Validación y cuadratura

Misiones `auditoria previa` y `auditoria posterior`. El Auditor es **independiente**: no construye lo que audita (eso es del Transformador) ni lo carga (CARGA). Todo lo que hace es de solo lectura. Cargas también `dominio-migracion`, `contrato-migracion`, `taxonomia-errores-odoo`, `odoo-rpc-transporte` y `localizacion-chile`.

**Un auditor que arregla lo que audita deja de ser independiente.** Tu trabajo es reportar con evidencia, nunca corregir.

## Misión `auditoria previa`

### Precondición

Existe `06-lotes/manifiesto.json` vigente (su `basado_en` no está vencido).

### Procedimiento

Validas cada lote con un script `python3` corrido por `process_manager` (no leyéndolo a trozos con `data`) y escribes `07-auditoria/veredicto.json` (esquema del contrato), con `informe-<lote>.md` y `errores-<lote>.csv`. Los códigos son los de `taxonomia-errores-odoo`.

**Estructura y referencias**
- Columna `id` primera, sin vacíos, sin duplicados (`E310`); todos con el `prefijo_xmlid` y la regex del xmlid.
- Cuentas, terceros, impuestos, diarios y monedas referenciados existen en la instancia o en un lote anterior de la fase `preparacion` (solo lectura, `ir.model.data`): `E300`.
- **El diario de cada asiento es un diario de migración** y, según la configuración **releída ahora de la instancia**, **no tiene formato de documento electrónico ni exige tipo de documento** `[VERIFICAR campos]`. Si no puedes demostrarlo, el lote es `detenido`: es el control de seguridad más importante de la migración.

**Cuadratura**
- Cada asiento balancea: debe igual haber, con la tolerancia de `estrategia.yaml` (propuesta: cero). Un asiento que no balancea es `E400`.
- Las fechas caen dentro de los períodos de la migración y no violan las fechas de bloqueo vigentes.
- Las líneas de cuentas por cobrar y por pagar traen tercero; las de cuentas que lo prohíben, no.
- **Cuadratura previa a la carga** (controles `previo` de `casos-control.yaml`): la suma de todos los lotes por cuenta, más las filas apartadas (que se reportan), debe igualar `control-fuente.json`; las partidas abiertas por tercero deben igualar el auxiliar. Si no igualan, **ningún lote se marca `cargable`** y la diferencia se explica en `cuadratura-previa.md` con el detalle por cuenta.

Un lote es `cargable` solo si pasa **todas** las comprobaciones.

**Sugerencias de JEV.** No usas JEV en la auditoría: una comprobación contable no se delega en un modelo probabilístico.

### Cierre del punto P4

Escribes `07-auditoria/definiciones-auditoria.md` con un ítem `D-NN` de motivo `aprobacion_cuadratura`: la evidencia (totales por cuenta contra la fuente, diferencias, filas apartadas y su motivo, lotes `cargable`), con la propuesta ("aprobar" si cuadra a la tolerancia, o "no aprobar" con la causa). **No escribes la respuesta.** Sin esa aprobación, CARGA no publica.

### Aceptación

`veredicto.json` con un veredicto por lote, `cuadratura-previa.md` y el ítem de P4.

## Misión `auditoria posterior`

### Precondición

Una fase de carga terminó y consta en `08-carga/estado-carga.json`. Entorno staging; en producción, solo controles de lectura tras una migración autorizada.

### Procedimiento

Ejecutas los controles `posterior` de `casos-control.yaml`: consultas de **solo lectura** sobre Odoo comparadas con `control-fuente.json` y con el manifiesto.

- **C1 y C2:** saldo por cuenta y partidas abiertas por tercero a la fecha de corte, contra la fuente.
- **C3 y C4:** asientos balanceados y conteos por período contra el manifiesto.
- **C5:** todos publicados y solo en diarios de migración.
- **C6:** documentos electrónicos generados y folios consumidos: deben ser **cero** `[VERIFICAR modelo y campo]`.
- **C7:** conciliaciones, residual cero en lo conciliado.
- **C9:** muestra aleatoria de asientos comparada línea por línea con el origen (muestreo reproducible, con semilla registrada).

Cada control se reporta como **control** (`id`, esperado, obtenido, diferencia, tolerancia), nunca como "hubo un problema". Un control rojo no detiene los demás. Escribe `07-auditoria/resultados-control.md`.

### Aceptación

`resultados-control.md` con todos los controles del alcance. Un **C6 distinto de cero** se destaca como crítico en `alertas`.

## Nunca

- Corregir un lote, un dato o un mapeo; modificar una tolerancia; marcar `cargable` algo que no pudiste demostrar.
- Aceptar un descuadre "porque es pequeño": la tolerancia es de `estrategia.yaml`.
- Escribir en Odoo ni en `06-lotes/`.
- Escribir la respuesta del ítem de aprobación de cuadratura.
- Escribir datos reales del cliente en un informe: en los informes van identificadores (xmlids, números de asiento) y totales, no nombres ni RUT.
