---
name: entornos-y-seguridad
description: Reglas de credenciales, entornos y producción — qué puede escribir CARGA y qué verifican los flujos al leer.
allowed-tools: odoo_jsonrpc
metadata:
  author: addval
  version: "1.0"
  category: odoo_migracion

---

# Entornos y seguridad

Reglas de credenciales, entornos y producción. Las aplica CARGA al escribir; el Analista, el Transformador y el Auditor las respetan al leer. El Coordinador verifica la autorización de producción con `correo-consultor-migracion`.

## Credenciales

- La API key vive en el parámetro `api_key` del nodo (marcado secreto) o en la variable de entorno `ODOO_API_KEY`. **Nunca** en el repositorio, en `estrategia.yaml`, en un mapeo, en un artefacto del proyecto, ni en una bitácora o informe. Si ves una clave en un archivo, es un hallazgo de seguridad: repórtala como alerta, no la copies.
- **Usuario dedicado de integración con lectura y escritura (R+W)**, nunca la cuenta personal de un consultor: la trazabilidad de la carga y la rotación de la clave dependen de eso. Ambos nodos `odooJsonRpc` (escritura y consulta) usan ese mismo usuario: **este despliegue no dispone de un usuario de solo lectura**, y no es posible crearlo.
- **El candado "solo CARGA escribe" es topológico y conductual, no de permisos.** El nodo de escritura (`odooJsonRpc:1`) está cableado como herramienta únicamente a CARGA — esa es la garantía estructural. El canal de consulta (`odooJsonRpc:2`), compartido por Analista, Transformador y Auditor con el mismo usuario R+W, se rige por regla del flujo: solo operaciones de consulta (`search`, `read`, `fields_get`, `read_group`); crear o escribir por ese canal está prohibido y el Auditor verifica esa restricción en cada revisión. Si en el futuro existiera un usuario de solo lectura disponible, la separación de credenciales se restablece.
- El acceso a la API externa solo está disponible en planes Custom de Odoo. Si `common.login` responde negativo con credenciales correctas, esa es la causa probable.
- Un fallo de login o permisos (`E500`) se resuelve en las credenciales del nodo: **no pruebes otro host**.

## Entornos

Ramas de Odoo.sh: `production`, `staging`, `development`. El entorno objetivo está en `03-diseno/estrategia.yaml` (`entorno_objetivo`, `base_datos`, `rama`).

- **QA y ensayos de carga van contra `staging`, jamás contra producción.** El QA crea documentos reales (órdenes, entregas, facturas, movimientos contables). Staging está neutralizado (correo saliente, crons y pagos deshabilitados), y eso es exactamente lo que lo hace seguro de repetir.
- Si `entorno_objetivo` es `production`, **no ejecutes el QA**: repórtalo como no ejecutado y por qué.
- **Antes de la primera escritura en producción**, confirma explícitamente base de datos y rama, y déjalo registrado. Sin esa confirmación, escribir en producción es una definición `entorno_produccion`, no una decisión del agente.

## Entorno del proyecto (leído del estado)

El flujo opera **exclusivamente contra la base y rama declaradas en `estado.json` → `entorno`** (`base`, `rama`, `produccion_habilitada`, `staging_confirmado`): es la única base con la que los nodos `odooJsonRpc` están conectados; ninguna escritura puede alcanzar otra base. La maquinaria de producción se activa por estado, no por texto del prompt:

- **`produccion_habilitada: false`** (despliegues de prueba y staging): toda la lógica de autorización de producción (P5, `autorizacion_produccion`, ensayo desde cero, confirmación de base y rama, respaldo previo) queda **fuera de alcance**: no la pidas, no la verifiques y no detengas cargas por ella. `ensayo_desde_cero` se reporta como `no_aplica_entorno`.
- **`produccion_habilitada: true`**: la P5 completa aplica — autorización con base de datos y rama en el texto de la respuesta de un remitente autorizado, registrada en `estado.json` antes de la primera escritura; el ensayo desde cero y el respaldo previo vuelven a ser requisito, y los aviso de producción de los skills vuelven a ser requisitos del turno.
- `staging_confirmado: true` declara que la base conectada cumple el rol de staging (neutralizada): QA y ensayos corren contra ella sin autorización adicional.

Las reglas de arriba (QA y ensayos jamás contra producción) conservan su valor como política del método; en cada despliegue, la base declarada en `estado.json` cumple el rol que su estado declara.

## Autorización de producción

La autorización exige, en el texto de la respuesta del consultor: el **nombre de la base de datos**, la **rama** y la palabra "autorizo", desde un remitente autorizado. "Adelante" o "sí, dale" no son una confirmación de entorno. La verificación es una regla fija sobre el texto (el Coordinador la hace); no la delega a un modelo. Sin autorización registrada en `coordinador/estado.json`, CARGA no escribe en producción, aunque el plan esté completo.

## El ensayo completo desde cero

Una carga incremental sobre una base ya ensuciada por intentos previos **no prueba que el orden de carga sea correcto**. El ensayo válido es reconstruir staging desde cero y repetir la carga entera: es el paso que todos se saltan y el único que detecta las dependencias ocultas entre archivos.

CARGA no puede reconstruir staging (es una operación de Odoo.sh, no de RPC). Lo que sí hace es **reportar si se hizo o no** (`ensayo_desde_cero`). Sin ese dato, el informe de cierre se lee como "listo para producción" y no lo es.

## Nunca

- Escribir en producción sin base de datos y rama confirmadas en el texto de la respuesta.
- Ejecutar QA o ensayos en producción.
- Escribir una credencial en un archivo o en un mensaje.
- Usar una cuenta personal para la integración.
- Cambiar de host para sortear un fallo de login.
- Reportar "listo para producción" sin declarar si el ensayo desde cero se hizo.
