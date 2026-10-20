---
name: ajustes-de-aplicacion
description: Configuración de Odoo vía res.config.settings — ajustes que habilitan menús y rutas; trabajo exclusivo de CARGA.
allowed-tools: odoo_jsonrpc
metadata:
  author: opencompany
  version: "1.0"
  category: carga

---

# Ajustes de la aplicación (`res.config.settings`)

Media configuración de Odoo no vive en un registro sino en un **ajuste**: la contabilidad analítica, las rutas multi-paso, las ubicaciones de almacenamiento, las unidades de medida, los lotes. Sin el ajuste encendido, el modelo existe y el menú no aparece, y el síntoma que reporta el usuario es "no está configurado", no un error. Esto **no** es `E520`: se hace por RPC y es trabajo de CARGA. Los agentes de flujo solo **leen** el estado de los ajustes (`default_get`) y declaran los que necesitan en `configuracion-<flujo>.yaml`.

## Patrón

Dos llamadas, y las dos son necesarias:

```
# 1. leer el estado actual (no adivines si ya está encendido)
model="res.config.settings", method="default_get",
args=[["group_analytic_accounting", "group_stock_adv_location", "group_uom"]]

# 2. escribir: create con SOLO lo que cambias, y execute() para aplicarlo
model="res.config.settings", method="create",
args=[{"group_analytic_accounting": true, "group_stock_adv_location": true}]
model="res.config.settings", method="execute", args=[[<id_devuelto>]]
```

- **`create` sin `execute` no cambia nada.** El `create` solo arma el formulario en memoria; `execute` escribe los grupos y los `ir.config_parameter`. Un `create` que devolvió un id y ningún `execute` es el fallo silencioso típico: la llamada respondió OK y el ajuste sigue apagado.
- **Solo pones en el `create` los campos que cambias.** El resto lo rellena `default_get` con el estado vigente, así que no pisas ajustes ajenos.
- **Verifica después con `default_get`**, no con el valor que enviaste.

## La línea que no cruzas: `group_*` sí, `module_*` no

- Los campos `group_<algo>` encienden un grupo: son un `write` y los haces tú.
- Los campos `module_<algo>` **instalan un módulo** cuando `execute()` corre. Es exactamente la acción que no te corresponde (`E510`/`E520`), y por esta vía Odoo **no te la bloquea**, así que la barrera tienes que ponerla tú.
- Un `module_*` que el diseño pide es una definición `modulo_faltante` con el nombre del módulo, nunca un `True` en tu payload.

## Capacidad, no configuración

El ajuste enciende la **capacidad**; no la configura. `group_stock_adv_location` hace visibles las rutas; cuántos pasos tiene cada almacén sigue siendo `stock.warehouse.reception_steps` / `delivery_steps`, que es una decisión del blueprint y se escribe como cualquier otro objeto `fuente: configuracion`.

## El menú cacheado

El cliente web cachea el menú. Después de encender un ajuste, el menú nuevo aparece al recargar la página: que el usuario no lo vea al instante no significa que el ajuste no se aplicó. Compruébalo con `ir.ui.menu` (`search_read` por nombre, con el campo de grupos y `active`) antes de dudar del `execute`.

## Ajustes observados

Se han usado por RPC en proyectos anteriores: `group_analytic_accounting`, `group_stock_multi_locations`, `group_stock_adv_location`, `group_stock_production_lot`, `group_uom`, `group_multi_currency`. **Es una observación, no una garantía**: los campos disponibles dependen de la instancia y de los módulos instalados. Confírmalos con `default_get`, y lo que se enciende en esta instancia se registra en `08-carga/capacidades-instancia.json` (`ajustes_aplicados`), no aquí.

## Registro

Anota cada ajuste que encendiste en `08-carga/bitacora-configuracion.jsonl` y en `capacidades-instancia.json` con su valor anterior: `{"campo": "group_uom", "de": false, "a": true, "visto": "<iso8601>"}`. Un ajuste aplicado sin registro es indistinguible de uno que ya venía puesto, y esa es justo la pregunta que aparece cuando alguien reporta que un menú no está.

## Nunca

- Poner un `module_*` en el payload.
- Dar un ajuste por aplicado sin `execute()` y sin releer con `default_get`.
- Apagar un ajuste que ya venía encendido sin una instrucción explícita del diseño.
- Aplicar ajustes en producción sin la autorización de `entornos-y-seguridad`.
