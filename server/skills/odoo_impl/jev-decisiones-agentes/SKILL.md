---
name: jev-decisiones-agentes
description: Usos de JEV en D0, flujos y CARGA — proponer clasificación cuando hay salida segura por defecto; nunca decidir criterio funcional.
allowed-tools: jev
metadata:
  author: opencompany
  version: "1.0"
  category: compartidos

---

# JEV en los agentes (D0, flujos y CARGA)

JEV (TypeSafe) devuelve decisiones tipadas con probabilidad y confianza; no genera texto. En los agentes se usa para **proponer una clasificación cuando hay una salida segura por defecto**, nunca para decidir criterio funcional, escribir respuestas de definiciones ni autorizar nada. La mecánica general (contrato de `questions`, tipos, respuesta) está en el skill de plataforma `jev`. Este skill fija los usos del proyecto. El Coordinador tiene los suyos en `jev-decisiones-coordinador`.

## Reglas comunes

- Llamada: `jev(state, questions)`, con `questions` como JSON string. Una llamada por unidad evaluada.
- **Preguntas atómicas**, con `instructions` completas y opciones mutuamente excluyentes. Combina las respuestas en tu código.
- `state` es solo material factual; sin tu opinión ni tu sugerencia.
- **Umbral común:** confianza ≥ 0,8 actúas; < 0,8 usas la **salida segura** del uso (indicada abajo). Es un punto de partida; ajústalo con el log.
- Un casi-empate en `probabilities` cuenta como baja confianza aunque la etiqueta sea una.
- Si `jev` falla o no está disponible, aplica la salida segura. Nada del pipeline depende de que JEV responda.
- Registra cada llamada en `01-analisis/jev-<flujo>.jsonl` (CARGA: `08-carga/jev-carga.jsonl`; D0: `01-analisis/jev-d0.jsonl`): `{ts, uso, ref, decisions, confidence, accion}`.

## Uso `descubrimiento` (D0)

Una llamada por historia de `propuesta-historias.csv`. `state` = la fila serializada.

```json
{
  "flujo_hu": {
    "type": "choice",
    "instructions": "Decide a qué flujo de implementación pertenece la historia según su objetivo principal",
    "criteria": {
      "financiero": "Plan de cuentas, impuestos, diarios, bancos, pagos, conciliación y emisión o contabilización de documentos tributarios y facturas",
      "ventas_servicios": "Cotizaciones, listas de precios, pedidos de venta, contratos, servicios, y la política de cuándo se factura un pedido o servicio",
      "compras_aprobaciones": "Solicitudes y órdenes de compra, proveedores, reglas y circuitos de aprobación",
      "inventario_fabricacion": "Bodegas, ubicaciones, stock, rutas, método de costeo y valorización del inventario, listas de materiales y órdenes de producción"
    }
  },
  "fuera_de_alcance_modular": {
    "type": "noul",
    "instructions": "La historia pide un desarrollo a medida o una integración con un sistema externo en lugar de configurar módulos estándar de Odoo"
  }
}
```

- `flujo_hu` ≥ 0,8: lo escribes en la columna `flujo` de `propuesta-historias.csv`. **Salida segura:** columna vacía y un ítem `D-00-NN` en `preguntas-descubrimiento.md` para que el consultor decida. Las fronteras que más se confunden son facturación (financiero) contra política de facturación (ventas) y costeo (inventario) contra cuentas de valorización (financiero): una confianza baja ahí es información útil para el consultor.
- `fuera_de_alcance_modular` ≥ 0,7: la historia se lista como candidata en `preguntas-descubrimiento.md`; JEV no la saca del alcance. Bajo 0,7 no se menciona.

## Uso `analisis` (agentes de flujo)

Una llamada por historia de tu flujo. `state` = `{"hu": <fila>, "instancia": {"modulos_instalados": [...], "modelo_existe": <bool>}}`, solo hechos de la introspección.

```json
{
  "modelo_principal": {
    "type": "choice",
    "instructions": "Decide cuál es el modelo de Odoo que mejor sostiene el dato central de la historia",
    "criteria": { "<modelo.a>": "<descripción del mapa de dominio>", "<modelo.b>": "<descripción>" }
  },
  "clasificacion": {
    "type": "choice",
    "instructions": "Decide cómo se resuelve la historia en Odoo 19 con la instancia descrita",
    "criteria": {
      "estandar": "Odoo lo cubre sin configurar nada especial",
      "parametrizable": "Se resuelve con ajustes, plantillas de datos o configuración del módulo",
      "desarrollo": "Requiere un desarrollo a medida dentro de Odoo",
      "integracion": "Requiere conectar con un sistema externo",
      "fuera_de_alcance": "No corresponde a un flujo de implementación"
    }
  },
  "esfuerzo": {
    "type": "score",
    "instructions": "Estima el esfuerzo de implementar la historia en la instancia descrita",
    "criteria": ["Pequeño: horas", "Mediano: pocos días", "Grande: semanas o más"]
  },
  "riesgo": {
    "type": "score",
    "instructions": "Estima el riesgo de que la implementación afecte datos, contabilidad u otros flujos",
    "criteria": ["Bajo", "Medio", "Alto"]
  }
}
```

Las opciones de `modelo_principal` salen del **mapa de modelos de tu skill `flujos/<flujo>`** (hasta 255): JEV solo puede elegir un modelo que tú ya listaste, nunca inventa uno.

- `modelo_principal` y `clasificacion` ≥ 0,8: los escribes en `matriz-brechas-<flujo>.csv`. **Salida segura:** escribes la propuesta de JEV igualmente en la fila, pero abres un ítem G1 `clasificacion_dudosa` para esa historia, que el consultor confirma. Una clasificación bajo umbral nunca llega a G2 sin confirmar.
- `esfuerzo` y `riesgo`: redondea el score al nivel más cercano (`S`/`M`/`L` y `bajo`/`medio`/`alto`). Son orientativos; se corrigen en G1 sin ítem aparte.
- Una HU con `clasificacion` = `desarrollo`, `integracion` o `fuera_de_alcance` se confirma siempre en G1, sin importar la confianza.

## Uso `validacion` (agentes de flujo)

Solo para **sugerir un candidato** en un `E220` (valor fuera de catálogo) o un `E300` (xmlid inexistente). `state` = `{"valor": "...", "campo": "...", "contexto": "<nombre del registro>"}`.

```json
{
  "candidato": {
    "type": "choice",
    "instructions": "Decide cuál de las claves del catálogo corresponde al valor que escribió el consultor, o ninguna si no hay una correspondencia clara",
    "criteria": { "<clave.1>": "<etiqueta>", "<clave.2>": "<etiqueta>", "ninguna": "El valor no corresponde con claridad a ninguna clave" }
  }
}
```

Las opciones salen del `catalogos` del sidecar (o de los xmlids más cercanos del lote). Siempre incluye `ninguna`.

- ≥ 0,8 y distinto de `ninguna`: lo pones como candidato en el `mensaje` de `errores-<modelo>.csv`. **Salida segura:** reportas el error sin candidato.
- **Un código de 2 o 3 caracteres que no calza exacto con ninguna clave ni etiqueta nunca recibe candidato**: un candidato plausible y equivocado es peor que un rechazo.
- JEV **nunca corrige una celda** ni cambia un veredicto.

## Uso `carga` (CARGA)

Solo cuando un mensaje de Odoo **no encaja en ninguna regla determinista** de `administrar-casos-de-borde-odoo`. Primero aplicas esas reglas por texto; JEV es el último recurso.

```json
{
  "codigo": {
    "type": "choice",
    "instructions": "Decide qué tipo de rechazo es este mensaje de Odoo al cargar una fila",
    "criteria": {
      "E110": "El campo indicado no existe en el modelo",
      "E200": "Falta un campo obligatorio",
      "E210": "Un valor tiene formato inválido: fecha, número, booleano o identificador",
      "E220": "Un valor no pertenece a las opciones permitidas de un campo de selección",
      "E300": "Una referencia por identificador externo no existe",
      "E400": "Una regla de negocio o restricción del modelo rechazó el registro"
    }
  }
}
```

- ≥ 0,8: usas el código para decidir la acción del bucle. **Salida segura:** `E400` con el mensaje literal de Odoo. Los códigos de instancia (`E500`, `E510`, `E520`) y de archivo (`E100`) **no están entre las opciones a propósito**: detienen la carga o un archivo, y solo se reconocen por reglas deterministas de texto.
- Nunca parafrasees el mensaje de Odoo al escalarlo, haya usado JEV o no.

## Límites

- JEV **nunca** escribe `respuesta:`, cierra un punto de control ni decide una `fuente`, un dueño o un valor de configuración.
- Una decisión de JEV es una propuesta con una salida segura. Si no hay salida segura clara, no se usa JEV.
