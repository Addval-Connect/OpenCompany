---
name: "aplicar-respuestas-al-json"
description: "Único punto donde un humano cambia un valor que el sistema no determinó. Para"
metadata:
  author: opencompany
  version: "1.0"
  category: "statement_import"
  icon: "✅"
  color: "#6366F1"

---

# Aplicar respuestas al JSON

Único punto donde un humano cambia un valor que el sistema no determinó. Para
auditoría tributaria hay que registrar **quién decidió y con qué base**: la
decisión se persiste en el JSON de la cartola (campos por línea) y en el
resultado de la tarea `task_manager`.

## Entrada

El COORD re-asigna esta tarea vía `task_manager` cuando el usuario respondió el
lote por chat. En `context` vienen las rutas workspace-relativas del JSON de la
cartola y de `cartola/pendientes.json`, más las respuestas del usuario. Lee con
**fileRead** (`file_read`); escribe con **fileModify** (`file_modify`).

## Procedimiento

1. Por cada pendiente con `respuesta` no nula, localiza la línea/campo
   (`referencia.movimiento_idx`, `referencia.campo`) en el JSON.
2. Aplica la respuesta. Si cambia la clasificación de destino (ej.
   `requiere_confirmacion` → `movimientos`), **mueve físicamente** la línea al
   arreglo correcto; no la dejes marcada como resuelta en el arreglo original.
3. Registra en la línea: `respondido_por`, `respondido_en` y el `pendiente.id`
   que originó el cambio. No se descarta tras aplicarse.
4. Si se resolvió `cliente_ambiguo`, actualiza `cartola.cliente_resuelto` de
   toda la sesión, no solo de la línea que originó la pregunta.
5. **Revalida** la consolidación completa: el COORD re-asignará
   los pasos de validación y detección de duplicado de `consolida-informacion` si cambió
   el instrumento o cliente. La aritmética la valida Odoo en escritura (constraints del
   módulo carga_kdx) y el read-back la confirma. Considera efectos en cascada.
6. Si quedan pendientes nuevos, agrégalos a un nuevo lote
   (`armar-lote-de-pendientes`); no los mezcles como resueltos.

## Salida

Persistida en el JSON y retornada al COORD:

```json
{
  "pendientes": [
    {
      "id": "P-001",
      "respuesta": "dividendo",
      "respondido_por": "usuario:maria.jose",
      "respondido_en": "2026-08-06T15:32:00Z"
    }
  ],
  "pendientes_restantes": 0
}
```

`estado` avanza a `CONSOLIDADA` solo si no quedan pendientes sin responder tras
la revalidación. Si surgen nuevos, permanece en `REQUIERE_USUARIO` con el lote
actualizado.

## Casos de borde

- **Respuesta parcial** (contesta algunos ítems): aplica los respondidos y deja
  el resto abierto; no bloquees los ya respondidos.
- **Respuesta ambigua o fuera de las opciones ofrecidas**: no la interpretes.
  Devuelve el ítem al lote (vía COORD → chat) citando la respuesta recibida y
  por qué no calza.
