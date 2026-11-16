---
name: "lenguaje-consultor-migracion"
description: "Vocabulario y estados que ve el consultor en la migración contable: tabla Di esto / No digas esto, estados visibles, etiquetas de duda y palabras de control. Cárgalo antes de redactar cualquier correo al consultor."
metadata:
  author: addval
  version: "1.0"
  category: "odoo_migracion"
  icon: "💬"
  color: "#6D28D9"

---

# Lenguaje con el consultor (migración)

Cómo se nombra el trabajo de la migración cuando le escribes al consultor. El tono lo da `voz-humana`; el formato, las plantillas del skill de correo de este flujo. Lo que el consultor usa para responder (los números de ítem `D-NN`) se mantiene tal cual.

## Di esto / No digas esto

| No digas esto | Di esto |
|---|---|
| P1 | los archivos de origen y la fecha de corte |
| P2 | las definiciones pendientes |
| P3 | el diseño y las tablas de mapeo |
| P4 | la cuadratura previa a la carga |
| P5 | la autorización para publicar en producción |
| hash, idempotencia | es el mismo archivo que ya revisamos |
| lote, lotes (en el cuerpo del correo) | cada grupo de datos que se carga de una vez (por validar; si la evidencia de cuadratura cita ids de lote, esos quedan tal cual porque el consultor los usa para responder) |
| cargable (veredicto) | listo para cargar |
| instancia_no_preparada | la base de Odoo destino no está lista para recibir la carga |
| diario_no_verificable | un diario no se pudo verificar |
| BLOQUEANTE | un bloqueo que detiene todo lo que sigue |
| staging | el entorno de pruebas |
| agente, Analista, Transformador, Auditor, CARGA (nombres de agentes) | el equipo (los roles se cuentan por lo que hacen: quien preparó la propuesta, quien la revisó) |
| control-fuente.json, estrategia.yaml, estado.json, 00-entrada/, 05-validados/ | el resultado, sin nombrar dónde vive |
| códigos de tarea o de etapa, sesion_id en el cuerpo | no se mencionan en el cuerpo (el prefijo del asunto va según el skill de correo) |
| JEV, veredicto | no se mencionan; la pregunta va tal cual en el ítem |

Las palabras que el consultor ya usa con este flujo se mantienen: tablas de mapeo, fecha de corte, sistema de origen, cuadratura, respaldo. Los valores de las celdas de las tablas de mapeo (por ejemplo, `propuesto` o `sin_equivalente`) se muestran tal cual, porque son datos de la tabla, no prosa.

## Estados visibles al consultor

Cuando cuentes en qué está el trabajo, usa estos nombres y su significado:

| Estado | Qué significa |
|---|---|
| Esperando tus archivos | Falta el paquete del sistema de origen o la fecha de corte; nada puede empezar sin eso. |
| Esperando tu respuesta | Hay definiciones por cerrar o aprobaciones tuyas pendientes (mapeos, cuadratura, autorización). |
| En trabajo | El equipo está preparando, revisando o cargando en borrador; no hay nada que te toque todavía. |
| Bloqueado | Algo del entorno detiene todo: la base de Odoo destino no está lista, o un diario no se pudo verificar; hace falta una acción fuera del trabajo. |
| Verificado en pruebas | El ensayo de carga en el entorno de pruebas quedó con los controles en verde; falta tu autorización para publicar. |

## Etiquetas de duda

En el correo, cada duda abierta se marca con una de estas etiquetas, una sola por ítem:

- **Para decidir:** criterio que solo el consultor puede definir. Ejemplo: "(Para decidir) ¿Los movimientos sin RUT se migran agrupados o quedan fuera?"
- **Para hacer en el sistema:** algo que alguien debe ejecutar en Odoo o en el entorno, distinto de decidir. Ejemplo: "(Para hacer en el sistema) Corregir las credenciales de Odoo para que la carga pueda conectarse."

## Palabras de control

- **apruebo la cuadratura:** la frase literal que aprueba la cuadratura previa a la carga. Va con las diferencias aceptadas, si las hay. "Ok" no es una aprobación.
- **autorizo:** la palabra literal que autoriza publicar en producción. Va acompañada del nombre de la base de datos y de la rama, escritos completos y exactos, no por referencia. "Sí, dale" no autoriza.

Estas palabras se piden tal cual en el correo, para que el consultor sepa qué se espera exactamente de su respuesta. La primera vez que aparezca "cuadratura" en un correo, se explica en una frase: el cuadre de los totales contra el origen.
