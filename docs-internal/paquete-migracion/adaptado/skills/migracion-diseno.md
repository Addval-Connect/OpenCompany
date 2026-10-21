# Analista · Diseño del mapeo

Misiones `diseno` y `cerrar P3`. Aquí se decide cómo se traduce el origen a Odoo. Cargas también `dominio-migracion`, `contrato-migracion` y `convencion-ids-externos`. Las decisiones de diseño son deterministas: salen del perfil de la fuente, de la introspección y de las respuestas del consultor; **nunca de JEV**.

## Misión `diseno`

### Precondición

- P2 cerrado: cero `respuesta:` vacías en `definiciones-requeridas.md`.
- `perfil-fuente.json`, `calidad-fuente.json`, `control-fuente.json` e `introspeccion.json` vigentes (no vencidos por una respuesta de P2).
- La instancia preparada, o cada faltante resuelto en una definición (`preparacion-instancia.json`).

### Procedimiento

1. **Relee** P2 respondido, el perfil, el control y la introspección.
2. **`03-diseno/estrategia.yaml`** (esquema en el contrato): prefijo de xmlid, entorno, fecha de corte, profundidad, tolerancia de cuadratura, alcance y diarios de migración, todo con su origen en una respuesta de P2.
3. **`03-diseno/mapeo.yaml`**: por cada archivo de origen, columna de origen → campo de Odoo, con la transformación (formato de fecha, separadores numéricos, regla de signo cuando el monto viene con signo, redondeo, valor por defecto). Todo campo de destino se confirma con `fields_get` o queda `[VERIFICAR]`.
4. **Estrategia de xmlid.** El de un asiento sale de su clave natural del origen: `<prefijo>.move_<sistema>_<tipo>_<numero>_<ejercicio>`; el de cada línea, del número de línea dentro del asiento: `<xmlid_del_asiento>_l<NN>`. **Nunca de la posición en el archivo** (`convencion-ids-externos`). Si el origen no trae número de línea estable, se deriva de forma determinista de campos que definen la línea (cuenta, tercero, monto, vencimiento) con un índice para líneas idénticas; una colisión irresoluble es una definición.
5. **Nombre y referencia del asiento.** Decide cómo el número de origen llega a Odoo sin consumir secuencias (`[VERIFICAR]` con una fila de prueba en staging), y conserva siempre el número y el tipo de comprobante de origen en un campo de referencia.
6. **Diarios de migración.** Define sus propiedades: sin formato de documento electrónico, sin exigir tipo de documento, secuencia propia, tipo adecuado `[VERIFICAR en la introspección]`. Si no existen, los crea CARGA en la fase `preparacion` con aprobación (P3).
7. **Estrategia de carga.** Fases: `preparacion` → `apertura` → `partidas_abiertas` → `historicos` (por período) → `conciliaciones`. Lotes por período; **un asiento nunca se parte entre dos lotes**. Cada lote se carga en **borrador**, se verifica y recién entonces se publica.
8. **Tablas de mapeo.** Genera las propuestas en `04-mapeos/` (`mapeo-cuentas`, `mapeo-terceros`, `mapeo-impuestos`, `mapeo-diarios`, `mapeo-tipos-documento`; columnas en `dominio-migracion` sección 5), cada una con `.meta.json` y una sección en `INSTRUCTIVO.md` que diga quién valida qué. Una coincidencia dudosa se marca `propuesto`; **nunca se decide con JEV**.
9. **Objetos propios de la migración** a crear en `preparacion`: cuentas faltantes del mapeo, terceros faltantes y diarios de migración. Cada uno como fila `confirmado` solo si el consultor lo aprobó.
10. **`03-diseno/casos-control.yaml`**: los controles de `dominio-migracion` sección 6 que son criterio de aceptación, cada uno con su `momento` (`previo` o `posterior`) y su tolerancia.
11. **`03-diseno/tareas.yaml`**: una tarea por fase y por lote, con dependencias.
12. **Cuestionario P3** (`D-NN` correlativos en `definiciones-requeridas.md`): esquema de xmlid y de nombre, propiedades de los diarios, orden y granularidad de lotes, estrategia de publicación, objetos propios a crear, controles de aceptación y lo que queda fuera por diseño. Cada ítem con propuesta.
13. **Verifica** antes de entregar: todo campo de destino confirmado o `[VERIFICAR]`, `basado_en` con las versiones vigentes, cada transformación con su origen en el perfil.

### Aceptación

`estrategia.yaml`, `mapeo.yaml`, `tareas.yaml`, `casos-control.yaml`, cinco tablas de mapeo con sidecar e `INSTRUCTIVO.md`, y los ítems de P3 con propuesta.

## Misión `cerrar P3`

1. Relee tus archivos antes de escribir.
2. Transcribe solo `respuesta`, `respondido_por` y `respondido_en` desde `context.respuestas`. Nunca escribas una respuesta que nadie dio.
3. Verifica que `05-validados/` trae las cinco tablas del consultor; si falta una o cambió su formato, es una definición abierta.
4. Actualiza el diseño solo en lo que la respuesta cambia, e incrementa `version`.
5. **Si una respuesta cambia el esquema de xmlid de los asientos, todo lo derivado queda vencido** (lotes, plan de conciliaciones, manifiesto): lo dices en `alertas` para que el Coordinador re-delegue `transformacion`. Nunca se parcha un lote.

Aceptación: cero `respuesta:` vacías en los ítems de P3; las cinco tablas validadas presentes; `basado_en` vigente.

## Nunca

- Diseñar una carga que consuma folios o genere documentos tributarios.
- Decidir con JEV una cuenta, un tercero o un impuesto del mapeo.
- Mapear a ojo un campo de Odoo que no viste en `fields_get`.
- Partir un asiento entre dos lotes.
- Cambiar el esquema de xmlid después de la primera carga sin una definición explícita.
- Escribir en Odoo ni en `05-validados/`.
