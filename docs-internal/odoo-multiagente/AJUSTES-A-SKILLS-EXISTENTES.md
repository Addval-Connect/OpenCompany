# Ajustes a los skills que ya tenías

Los skills nuevos cambian rutas, nombres y responsabilidades. Estos son los cambios exactos en los que ya existían. No reescribí esos skills porque no tengo acceso a las versiones vigentes en tu plataforma; apliqué los cambios sobre el texto que me compartiste.

## Reemplazados por este paquete (retíralos)

| Skill anterior | Lo reemplaza |
|---|---|
| `contrato-implementacion-odoo` (versión con A1 a A5) | `contrato-implementacion-odoo` de este paquete |
| `puntos-de-control-consultor` (cinco expertos, G1 y G2 globales) | `puntos-de-control-consultor` de este paquete |
| `odoo-rpc-en-opencompany` | `odoo-rpc-transporte`, `taxonomia-errores-odoo`, `bucle-de-correccion`, `ajustes-de-aplicacion`, `entornos-y-seguridad`, `odoo19-diferencias` y `localizacion-chile` |
| Skills de etapa A1 a A4 (análisis, blueprint, plantillas, validación) | `flujo-entendimiento`, `flujo-configuracion`, `flujo-implementacion` |
| `orden-de-carga-odoo` | El orden sale del grafo `depende_de` (ver `carga-a-odoo-y-verifica`, paso 2) |
| `flujos-de-referencia` (en el runbook de carga) | La sección 6 de cada `flujos/<flujo>` (los casos de QA los escribe cada flujo) |

Dónde fue cada sección de `odoo-rpc-en-opencompany`: la herramienta, `load()`, las lecturas, el límite `E520` y la economía de llamadas a `odoo-rpc-transporte`; la tabla de códigos y su clasificación por texto a `taxonomia-errores-odoo`; el bucle, `E110`, `E220` y `E300` en carga a `bucle-de-correccion`; `res.config.settings` a `ajustes-de-aplicacion`; la seguridad y los entornos a `entornos-y-seguridad`; las tablas de campos y claves de Odoo 19 a `odoo19-diferencias`; el caso de `E300` sobre xmlids de la localización a `localizacion-chile`. "Ajustes verificados en esta instancia" no se migró como skill: es un hecho de **una** instancia y va en `08-carga/capacidades-instancia.json`.

## `carga-a-odoo-y-verifica` (runbook de CARGA)

1. **Nombres.** Reemplaza "A1/A3/A4/A5" por los nombres de los agentes (flujo `<flujo>`, CARGA). "A4 resultado" pasa a "veredicto del flujo".
2. **Precondición 1.** Lee `07-validacion/veredicto-<flujo>.json` (un veredicto por archivo: `cargable`, `con_errores`, `detenido`). Elimina el párrafo que tolera claves de nombre variable (`cargables`, `archivos_ok`…).
3. **Precondición 2.** El entorno sale de `03-blueprint/proyecto.yaml` (`entorno_objetivo`, `base_datos`, `rama`), no de `blueprint.yaml`.
4. **Ancla contable.** Agrega una precondición: no cargues ningún archivo de un flujo que no sea el ancla mientras los objetos con `ancla: true` de `blueprint-financiero.yaml` no estén `cargado` en `estado-carga.json` con read-back correcto.
5. **Paso 1 (configuración).** Los valores salen de `03-blueprint/configuracion-<flujo>.yaml` (registros y ajustes). Antes no había de dónde sacarlos.
6. **Prechecks de `account.account`** (xmlid de empresa, cuenta de resultado del ejercicio, `company_ids` en analíticos y diarios): muévelos a `localizacion-chile` y déjalos aquí como una línea que apunte allá. Quita las ramas para versiones anteriores de Odoo.
7. **Paso 2 (plan).** Quita "el `nn` del `blueprint.yaml`, que es la autoridad": ese campo no existe. El orden sale de `depende_de` y `requiere_de` de los blueprints de todos los flujos. Quita los nombres con prefijo `NN` (`20_res.partner.csv`): ahora son `<modelo>.csv`.
8. **Paso 2b.** El bucle y las reglas de corrección ahora viven en `bucle-de-correccion`: deja aquí solo el procedimiento por archivo y apunta allá.
9. **`capacidades-instancia.json`.** Cambia la ruta a `08-carga/capacidades-instancia.json`. Lo crea y lo escribe solo CARGA (ya no A1). Quita la excepción a la regla de "no escribir en carpeta ajena".
10. **Paso 2c, punto 2.** El script lee `campos-<modelo>.json`; ese archivo no puede vivir en `05-plantillas/` (carpeta del flujo). Cámbialo a `08-carga/campos-<modelo>.json`, o lee los campos desde `02-instancia/introspeccion-<flujo>.json`.
11. **Paso 5 (QA).** CARGA **no genera** los casos: ejecuta los de `09-qa/casos-<flujo>.yaml` (los escribe cada flujo). Quita la generación desde `flujos-de-referencia`. Adopta el formato único del contrato (`valores` con `*_xmlid`; aserciones como expresiones).
12. **Salida.** Agrega `ancla_cumplida: true|false` a `resultado_carga` y el campo `flujo` por modelo.

## `administrar-casos-de-borde-odoo`

1. **Paso 1 (tabla "El mensaje dice → es").** Elimínala: es la tabla de `taxonomia-errores-odoo`, que ahora es la fuente única. Deja una línea que apunte allá.
2. **Pasos 2 a 6.** Los reintentos, `E110`, `E220`, "ya existe", `E500` y las reglas de negocio son ahora `bucle-de-correccion`. Deja aquí solo lo que sea propio de un caso de borde sin repetir el bucle.
3. **`E300` sobre un xmlid `l10n_*`.** Muévelo a `localizacion-chile`.
4. **Paso 7, punto 5 (acumular en `capacidades-instancia.json`).** Cambia la ruta a `08-carga/` y apunta a `bucle-de-correccion` ("Reportar el estado real"), que ya lo describe.
5. **Nombres de agente.** Cambia "observación para A3" por "observación para el flujo dueño".

## `convencion-ids-externos`

1. **Normalización.** El conjunto permitido es `[a-z0-9_.]`, pero la regex de verificación es `^[a-z0-9_]+\.[a-z0-9_]+$`: el punto rompe la separación módulo.nombre. Quita `.` del conjunto permitido en la parte `objeto_clave`.
2. **Verificación 6** (`E320` por prefijo `NN`): cámbiala a "el grafo `depende_de` es acíclico y ninguna referencia apunta a un objeto que se cargue después".
3. **"Verificación antes de cargar".** Esa lista es el trabajo del validador (`flujo-implementacion`, misión `validacion`): deja solo las reglas del xmlid y apunta allá para el procedimiento.
4. **Prefijo `NN`.** Quita las menciones a `NN_<modelo>.csv`: ahora `<modelo>.csv`.

## `scripts-verificados-de-carga-odoo` y `sandbox-de-codigo-en-opencompany`

- Cambia las rutas de `05-plantillas/campos-<modelo>.json` (ver punto 10 del runbook).
- Quita referencias a nombres con prefijo `NN`.
- `sandbox-de-codigo-en-opencompany` no necesita otros cambios: lo cargan CARGA y los flujos (validación).

## Verificación final

Con los cambios aplicados, busca estos textos en todos los skills: `A1`, `A2`, `A3`, `A4`, `A5`, `NN_`, `cargables`, `blueprint.yaml` (sin `-<flujo>`), `matriz-brechas.csv` (sin `-<flujo>`), `introspeccion.json`. Si aparece alguno, es un resto de la arquitectura anterior.
