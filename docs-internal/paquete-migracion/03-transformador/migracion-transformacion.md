# Transformador · Transformación a lotes

Misión `transformacion`. Convierte los archivos de origen en lotes listos para cargar. **No escribe en Odoo y no se audita a sí mismo**: lo que produce lo valida el Auditor, que es independiente. Cargas también `dominio-migracion`, `contrato-migracion`, `convencion-ids-externos`, `localizacion-chile` y `sandbox-de-codigo-en-opencompany`.

**Capacidad requerida del sandbox.** La transformación genera archivos grandes en `06-lotes/`. Necesitas un sandbox que pueda **leer y escribir** el workspace (`workspace_read` y una capacidad de escritura; el nombre exacto es `[VERIFICAR]` en tu plataforma). Si no puede escribir, no devuelvas lotes enormes por el contexto: detén la misión con una definición `otro` explicando la limitación.

## Precondición

- P3 cerrado: cero `respuesta:` vacías en los ítems de P3.
- Las **cinco tablas de mapeo validadas** por el consultor en `05-validados/`. Sin ellas, el mapeo de cuentas, terceros e impuestos es una propuesta, no un dato.
- `basado_en` vigente: perfil, control de la fuente, estrategia y mapeo no están vencidos.

Si algo falla, no ejecutes a medias: definición `otro` en `preguntas-abiertas.md` y `detenida_por_precondicion`.

## Procedimiento

1. **Un solo script versionado** (`06-lotes/scripts/transformar.py`) que hace todo el trabajo y es reejecutable: misma entrada, mismos lotes. No hay transformaciones manuales ni arreglos hechos a mano sobre un lote.
2. **Lee** los archivos de `00-entrada/fuente/` y las tablas de `05-validados/`; aplica `mapeo.yaml` (fechas, números, signos, redondeo) y las reglas de `estrategia.yaml`.
3. **Genera los lotes** en `06-lotes/lotes/<conjunto>_<periodo>.csv`, con las cabeceras del importador de Odoo: `id` primera columna, un asiento con sus líneas anidadas (la primera fila trae el `id` del asiento y las siguientes lo dejan vacío), referencias por xmlid. **Un asiento nunca se parte entre lotes.** Un lote por fase y por período, en el orden de las fases de `estrategia.yaml`.
4. **Genera los datos de la fase `preparacion`**: los diarios de migración, las cuentas faltantes y los terceros faltantes que el consultor aprobó, como lotes de configuración con xmlid.
5. **Genera `plan-conciliaciones.csv`**: grupos de líneas (por xmlid de línea) que se concilian entre sí, con su `origen` (`origen`, `regla` o `confirmada`). Una conciliación ambigua no se incluye: va a una definición.
6. **Genera `manifiesto.json`** (esquema en el contrato): por lote, número de asientos y líneas, total debe, total haber, período, rango de xmlids, hash y `basado_en`.
7. **Nunca modifiques una cifra de la fuente.** Si un dato no se puede transformar (fecha ilegible, monto no numérico), la fila se aparta con su motivo en `rechazos-transformacion.csv`, y **todo el asiento** al que pertenece se aparta: un asiento incompleto no balancea.
8. **Verificación propia mínima**, antes de entregar: la suma de las filas de los lotes más las apartadas iguala el total de filas de la fuente. Esto no reemplaza la auditoría independiente.

## Aceptación

`transformar.py`, los lotes, `plan-conciliaciones.csv`, `manifiesto.json` y `rechazos-transformacion.csv`; la suma de lotes y apartadas iguala la fuente.

## Resultado

Resumen con conteos (asientos, líneas, lotes, apartados y su motivo) y rutas. **Sin datos reales del cliente** en el resultado.

## Nunca

- Escribir en Odoo, en `05-validados/`, ni en `00-entrada/`.
- Modificar, redondear o "completar" una cifra de la fuente para que cuadre.
- Partir un asiento entre dos lotes, o dejar un asiento incompleto en un lote.
- Editar un lote a mano: se corrige el script y se regenera.
- Marcar un lote como `cargable`: eso lo decide el Auditor.
- Escribir datos reales del cliente en un resultado o mensaje.
