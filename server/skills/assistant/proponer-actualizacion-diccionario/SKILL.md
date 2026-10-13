---
name: "proponer-actualizacion-diccionario"
description: "Es la auto-mejora del sistema y la capacidad más riesgosa: una propuesta"
metadata:
  author: opencompany
  version: "1.0"
  category: "assistant"
  icon: "📖"
  color: "#10B981"

---

# Proponer actualización de diccionario

Es la auto-mejora del sistema y la capacidad más riesgosa: una propuesta
incorrecta publicada sin revisión contaminaría en silencio todas las cartolas
futuras del custodio. Por eso esta skill nunca escribe la versión que consumen las
sesiones — solo prepara un borrador con evidencia para que un humano decida.

## Dónde vive la propuesta (workspace)

Se escribe como borrador en el workspace (ej.
`propuestas/propuesta-<diccionario_id>-<fecha>.json`) con **file_modify**, y su ruta
se devuelve en el resultado. El COORD la surge al equipo Tax vía chat. NO se toca el
diccionario vigente en el directorio de diccionarios: esa transición a `vigente` la
hace un humano fuera de este flujo. Para reunir evidencia, lee páginas con
**file_read** y localiza patrones con **fs_search**.

## Cuándo se activa

- Una columna, código (ej. `REUS`, `DIUS` en Ameris) o descripción no está en
  ninguna regla del diccionario vigente.
- Un patrón enviado repetidamente a `requiere_confirmacion` con el mismo motivo a
  través de varias cartolas del mismo custodio.
- Se procesó una cartola con compras/ventas reales de un custodio cuyo diccionario
  se construyó sin transacciones (Itaú, BICE, Merrill) y el comportamiento difiere.

## Procedimiento

1. Reúne evidencia con **file_read** / **fs_search**: cartola de origen, número de
   página, línea exacta y el fragmento textual que no encaja.
2. Redacta el cambio como un **diff** sobre el diccionario vigente — no reescribas la
   ficha completa salvo que el hueco sea estructural.
3. Explicita, por cada cambio, a qué destino (1-4) debería ir el patrón y por qué,
   citando la evidencia.
4. Escribe el borrador con **file_modify**, marcado con: `diccionario_id`,
   `version_base` (versión vigente sobre la que se propone), `estado: "borrador"`.
5. **Nunca** marques `vigente` por tu cuenta ni sobrescribas el diccionario vigente:
   requiere aprobación humana nominal (con quién y cuándo) fuera de esta skill.
6. Si la propuesta reclasifica un patrón de `excluidos`/`requiere_confirmacion` hacia
   destino 1 (Kárdex), señálalo como cambio de alto impacto — afecta qué se carga a
   Odoo.

## Salida

Resultado de la TeamTask con la ruta del borrador. El COORD la surge al equipo Tax.

```json
{
  "propuesta_diccionario": {
    "ruta_borrador": "propuestas/propuesta-diccionario-ameris-v1-20240712.json",
    "diccionario_id": "diccionario-ameris-v1",
    "version_base": "1",
    "estado": "borrador",
    "cambio_propuesto": "Agregar regla: código 'REUS' en líneas VEHÍCULO=CAJA corresponde a reparto de dividendo, según N cartolas revisadas.",
    "evidencia": [
      { "cartola": "AMERIS_ALC_072024.pdf", "pagina": 4, "linea": "REUS CFIAMG3R-E", "fecha": "2024-07-12" }
    ],
    "impacto": "medio",
    "requiere_aprobacion_de": "equipo Tax / responsable de diccionarios"
  }
}
```

## Reglas que nunca rompas

- Toda sesión consume solo la versión `vigente`, nunca un `borrador`, aunque lo haya
  generado una sesión anterior del mismo custodio.
- Una propuesta no resuelve la sesión actual: la línea que la motivó sigue su camino
  por `requiere_confirmacion` en esta sesión; la propuesta es para sesiones futuras.
- Un diccionario, una propuesta. No acumules cambios de distintos custodios.
