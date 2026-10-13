---
name: "cerrar-y-notificar-sesion"
description: "A4 sabe el detalle de la carga, pero una sesión puede cerrarse sin llegar a A4"
metadata:
  author: opencompany
  version: "1.0"
  category: "statement_import"

---

# Cerrar y notificar sesión

A4 sabe el detalle de la carga, pero una sesión puede cerrarse sin llegar a A4
(ej. `RECHAZADA` por duplicado o custodio sin diccionario). Centralizar el
cierre en el Coordinador garantiza que **toda** sesión termina con notificación.
El Coordinador (team-lead) recibe el resultado final del TeamTask de A4 (o el
estado terminal de un worker anterior) vía `taskTrigger`.

## Cuándo se activa

- `IMPORTADA`: carga completa sin errores de línea.
- `IMPORTADA_PARCIAL`: carga con algunas líneas en error (gestionadas por
  `administrar-casos-de-borde-carga` de A4).
- `RECHAZADA`: sesión detenida antes de interpretación/importación (formato
  ilegible, duplicado, custodio sin diccionario).

## Procedimiento

1. Reconstruye el resumen desde los TeamTask aceptados y los artefactos del
   workspace (`sesiones/<sesion_id>/`): líneas cargadas, excluidas por diseño
   (con motivo), en error, pendientes resueltos y respuestas. Lee con
   **fileRead** el `resultado_carga` de A4 (ej.
   `sesiones/<sesion_id>/resultado_carga.json`) y el JSON consolidado; usa el
   registro durable de los TeamTask como pista de auditoría.
2. Si hubo `resultado_carga`, incluye referencias directas a los movimientos
   creados en Odoo (`id` enteros de `kardex.import.log` / `kardex.import.line`;
   la identidad es el `id`, **nunca** `name`), no solo el conteo.
3. Si fue `RECHAZADA`, no reconstruyas resumen de carga: céntrate en el motivo
   del rechazo y, si aplica, en la sesión previa relacionada (duplicado).
4. Incluye siempre fees/diferencias detectados, aunque su tratamiento contable
   siga pendiente.
5. Entrega por el canal configurado (email, chat del chatTrigger, u otro) y
   cierra: marca el TeamTask como aceptado/cerrado y refleja el cierre con
   **writeTodos**. La sesión no se vuelve a derivar con `assign_task` salvo
   reapertura explícita.

## Salida

```
Sesión <sesion_id> — Custodio <custodio> — Cliente <cliente_nombre>
Resultado: IMPORTADA_PARCIAL

✔ 14 movimientos cargados al Kárdex
✘ 2 movimientos con error — requieren tu decisión
ℹ 3 movimientos excluidos por diseño (caja, traspasos)
ℹ 1 fee/diferencia detectado, sin tratamiento contable automático aún

Movimientos creados en Odoo (kardex.import.log id / line ids): […]
Pendientes resueltos durante la sesión: 2
```

## Casos de borde

- **`RECHAZADA` por duplicado**: cita el `sesion_id` anterior con el que
  coincidió el hash, para verificar si el reenvío fue intencional.
- **Cero movimientos de destino 1**: no es fallo. Indica que la cartola fue
  procesada sin movimientos que mover al Kárdex. Regla: si A3/A4 determinaron
  que no había operaciones, NO se crea `kardex.import.log` (nunca header sin
  líneas); el cierre refleja "procesada, sin movimientos".
- **Reapertura de sesión ya cerrada**: esta skill no la gestiona; requiere una
  nueva sesión o un mecanismo de corrección fuera de este flujo.
