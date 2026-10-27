---
name: puntos-de-control-migracion
description: "Los cinco puntos de control (P1 a P5): qué cierra cada uno, quién lo prepara y cómo lo ejecuta el Coordinador sin cruzarlos."
allowed-tools: data
metadata:
  author: addval
  version: "1.0"
  category: odoo_migracion

---

# Puntos de control de la migración

Una migración no falla por falta de agentes: falla por decisiones que nadie tomó y que el pipeline supuso (la fecha de corte, el tratamiento de un tercero sin RUT, un diario que sí genera documentos tributarios), y se descubren cuando ya hay asientos publicados. Por eso el proceso se detiene cinco veces. **Un punto de control no es un error: es el diseño.** El error es cruzarlo.

```
P1  Entrada      el consultor entrega los archivos de origen y la fecha de corte
    ── analisis (Analista) ──
P2  Análisis     el consultor cierra las definiciones (definiciones-requeridas.md)
    ── diseno (Analista) ──
P3  Diseño       el consultor aprueba el diseño y valida las tablas de mapeo
    ── transformacion (Transformador) · auditoria previa (Auditor) ──
P4  Cuadratura   el consultor aprueba la cuadratura previa a la carga
    ── carga y auditoria posterior ──
P5  Producción   autorización explícita (solo si el entorno objetivo es production)
```

Una definición corregida en P2 cuesta una respuesta; la misma, corregida después de publicar, cuesta restaurar la base.

## Qué cierra cada punto

### P1 · Entrada

El Coordinador pide, en un correo con plantilla fija (`correo-consultor-migracion`): los archivos del sistema de origen (plan de cuentas, balance de comprobación, libro diario o mayor, auxiliar de terceros, libros de compras y ventas, conciliaciones, maestro de terceros), el nombre del sistema y la **fecha de corte**. Se cierra cuando los archivos están en `00-entrada/fuente/` y la fecha de corte consta por escrito. El Coordinador los guarda y **nunca los abre**.

### P2 · Análisis

El Analista escribe el cuestionario en `01-analisis/definiciones-requeridas.md` (mínimo en `dominio-migracion`, sección 3) con una pregunta por cada defecto de calidad y por cada columna de rol dudoso. Se cierra con **cero `respuesta:` vacías**. Incluye el `prefijo_xmlid`, aprobado literalmente, y el entorno objetivo.

### P3 · Diseño

Se cierra cuando (a) los ítems de diseño del mismo archivo están respondidos y (b) el consultor devolvió las **cinco tablas de mapeo** corregidas y validadas, que el Coordinador transcribe a `05-validados/`. El Analista las propone; una propuesta no validada no es un dato.

### P4 · Cuadratura previa

Al terminar `auditoria previa`, el Auditor escribe en `07-auditoria/definiciones-auditoria.md` un ítem `D-NN` de motivo `aprobacion_cuadratura`, con la evidencia: totales por cuenta contra la fuente, diferencias, filas apartadas y lotes `cargable`. **CARGA no publica ningún lote mientras ese ítem no tenga una respuesta de aprobación.** Hasta entonces puede cargar en borrador y verificar. Publicar contabilidad no se deshace con un archivo corregido.

### P5 · Producción

Solo si `entorno_objetivo` es `production`. La autorización exige base de datos y rama en el texto de la respuesta, desde un remitente autorizado, y la palabra "autorizo" (`correo-consultor-migracion`). Además, CARGA exige un **ensayo en staging con todos los controles en verde** y el respaldo previo de la base informado.

## Reglas del archivo de definiciones

1. **Un ítem se numera `D-NN` y no se renumera nunca.** El consultor responde citando el número.
2. **Ningún agente escribe `respuesta`, `respondido_por` ni `respondido_en` por su cuenta.** Los transcribe el Coordinador desde lo que respondió la persona. Rellenar una respuesta "obvia" convierte el punto en trámite.
3. **Un ítem no se borra porque quedó sin responder.** Es la evidencia de qué falta. Si dejó de aplicar, se responde `no aplica` con quién lo dijo.
4. **`BLOQUEANTE` marca lo que detiene la etapa siguiente completa.** El resto permite avanzar con lo ya definido.

El archivo es la autoridad sobre si el punto está cerrado. Si el puntero y el archivo se contradicen, manda el archivo.

## Cómo lo ejecuta el Coordinador

No escribes cuestionarios: **transportas**.

1. **Lee el archivo** del punto con `data`.
2. **Publica** (skill `correo-consultor-migracion`): los `BLOQUEANTE` primero, con las opciones tal como vienen y sin sugerir una, porque la propuesta ya está en cada bloque.
3. **Di explícitamente qué trabajo está detenido** y qué desbloquea cada respuesta. Refleja el punto como ítem propio en `write_todos`.
4. **Espera por el mismo canal.** No reintentes por otra vía ni avances "mientras tanto" con lo que depende de la respuesta.
5. **Al llegar respuestas**, re-delega la misión de cierre (`cerrar P2`, `cerrar P3`) al Analista, con las respuestas en el `context`. Las transcripciones de P1, de las tablas validadas (P3) y de la aprobación de P4 las haces tú.
6. **Verifica el cierre releyendo los archivos**, no el resultado de la delegación: cero `respuesta:` vacías. Recién ahí delegas la etapa siguiente.

No das un punto por cerrado con ítems sin responder, no respondes tú un ítem, y no te saltas un punto porque "no había pendientes".

## Casos de borde

- **Respuesta parcial:** transcribe lo definido; re-pregunta solo por lo abierto, citando los `D-NN`.
- **El consultor entrega un archivo corregido o nuevo:** el perfil, el control de la fuente, el mapeo y todo lo derivado quedan vencidos (`basado_en`); se re-delega desde `analisis`.
- **Cambia la fecha de corte o la profundidad:** invalida `control-fuente.json` y todo lo que dependa de él. Se agrega un ítem que dice qué reemplaza; no se edita la respuesta anterior.
- **El consultor pide más contexto** (ver una tabla, ver un total): lo provees; no cuenta como segunda interrupción.
- **Una respuesta invalida un artefacto ya producido:** re-delega la etapa que lo produjo. Nadie parcha artefactos ajenos.
- **Un lote ya publicado resulta incorrecto:** no se recarga. Es una definición (asiento inverso o restauración de la base) que decide una persona.
