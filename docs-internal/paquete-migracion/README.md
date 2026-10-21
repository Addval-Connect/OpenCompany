# Flujo independiente: migración contable a Odoo 19

Sistema multiagente **propio** para migrar la contabilidad histórica de un sistema de origen a Odoo. No depende del sistema de implementación ni se orquesta con él: tiene su propio Coordinador, contrato, puntos de control y agentes. Parte de una instancia que **ya tiene su configuración contable base** (compañía, localización, plan de cuentas, impuestos); si falta algo, lo reporta y no lo configura.

## Los cinco agentes

| Nodo | System prompt | Skills propios | Odoo |
|---|---|---|---|
| Coordinador de Migración | `00-prompts/system-prompt-coordinador-migracion.md` | `orquestacion-migracion`, `puntos-de-control-migracion`, `correo-consultor-migracion`, `jev-migracion` | no |
| Analista de Migración | `00-prompts/system-prompt-analista-migracion.md` | `migracion-analisis`, `migracion-diseno` | solo lectura |
| Transformador de Migración | `00-prompts/system-prompt-transformador-migracion.md` | `migracion-transformacion` | solo lectura |
| Auditor de Migración | `00-prompts/system-prompt-auditor-migracion.md` | `migracion-auditoria` | solo lectura |
| CARGA Migración | `00-prompts/system-prompt-carga-migracion.md` | `migracion-carga`, `bucle-de-correccion` | **escritura** |

El **Auditor es independiente** a propósito: no construye (Transformador) ni carga (CARGA) lo que audita.

## Skills compartidos (`06-compartidos/`)

Los cargan todos o casi todos: `contrato-migracion`, `dominio-migracion`, `odoo-rpc-transporte`, `taxonomia-errores-odoo`, `entornos-y-seguridad`, `localizacion-chile`, `odoo19-diferencias`, `jev-migracion`.

`odoo-rpc-transporte`, `taxonomia-errores-odoo`, `bucle-de-correccion`, `entornos-y-seguridad`, `localizacion-chile` y `odoo19-diferencias` son **copias** de los del paquete de implementación, con los roles adaptados a este flujo. Si corriges un hecho en uno (por ejemplo, un campo de Odoo), corrígelo en ambos.

## Skills de tu biblioteca que este flujo también usa

No están en este paquete (ya los tienes): `convencion-ids-externos`, `sandbox-de-codigo-en-opencompany`, `scripts-verificados-de-carga-odoo`. Y los de plataforma: `task-manager`, `write-todos`, `jev`.

## El proceso

```
P1 Entrada      archivos de origen + fecha de corte
   analisis (Analista)
P2 Análisis     el consultor cierra las definiciones
   diseno (Analista)
P3 Diseño       el consultor aprueba el diseño y valida las tablas de mapeo
   transformacion (Transformador) · auditoria previa (Auditor)
P4 Cuadratura   el consultor aprueba la cuadratura previa
   carga por fases (CARGA): preparacion → apertura → partidas_abiertas → historicos → conciliaciones
   auditoria posterior (Auditor)
P5 Producción   autorización explícita, solo si el entorno objetivo es production
```

Cada lote se carga en **borrador, se verifica y recién entonces se publica**. Lo migrado **no genera documentos tributarios ni consume folios**: se verifica antes de cargar, y un solo documento electrónico generado detiene todo.

## Cómo instalarlo

El instructivo completo, con diagrama, checklist de requisitos y pruebas, está en `00-INSTRUCTIVO.md`. Resumen:

1. Crea los cinco nodos con los nombres de la tabla y conecta los cuatro workers al `input-teammates` del Coordinador. Copia sus IDs a la tabla de equipo del prompt (`<NODE_ID_…>`).
2. Pega en cada nodo su system prompt y carga sus skills (propios, compartidos y de tu biblioteca).
3. Credenciales: usuario de Odoo de **solo lectura** para Analista, Transformador y Auditor; con escritura solo para CARGA. `ms_mail` solo en el Coordinador. `jev` en el Analista y el Coordinador.
4. Trigger del Coordinador: correo entrante, filtrado por el prefijo `[<empresa>-<sesion_id_corto>]` del asunto.
5. Al arrancar, entrega al Coordinador las direcciones del consultor (`consultores_autorizados` en `coordinador/estado.json`). Sin ellas no actúa sobre ninguna respuesta.
6. Entrega los workspaces de cada proyecto con la carpeta `migracion/` vacía y `00-entrada/fuente/` con permiso de escritura para el Coordinador.

## Requisitos de plataforma que no resuelve este paquete

- **El sandbox del Transformador debe poder escribir el workspace.** Genera lotes grandes; si solo puede leer, la transformación no es viable así.
- **Cómo llegan los archivos de origen al workspace.** El Coordinador los guarda al recibirlos por correo, pero el tamaño máximo de adjuntos y la vía alternativa dependen de tu plataforma.
- **Confidencialidad.** Los archivos del cliente tienen RUT, nombres y montos. Ningún agente los carga completos a su contexto y JEV solo recibe muestras enmascaradas; que el Analista y el Transformador los procesen debe estar permitido por tu política de datos.

## Lo que falta confirmar

- Los nombres de campo y de método de Odoo de los skills (`parent_state`, `balance`, `action_post`, `reconcile`, los campos de formato electrónico del diario) están marcados `[hipótesis]` o `[VERIFICAR]`: confírmalos en staging con una fila de prueba antes de diseñar sobre ellos.
- Las 18 preguntas de P2 y sus propuestas por defecto son una primera versión, a revisar contra cómo trabajas con tus clientes.
- Los umbrales de JEV (0,8 general, 0,3 para ambigüedad contable) son valores iniciales sin calibrar; los logs `jev-*.jsonl` sirven para ajustarlos.
