# Paquete: sistema multiagente de implementación Odoo 19

Prompt del Coordinador y skills para los seis agentes que cuelgan de él. Todo en español, en markdown.

## Contenido

```
00-coordinador/
  00-system-prompt-coordinador.md
  skills/ orquestacion-del-proyecto · puntos-de-control-consultor · correo-consultor · jev-decisiones-coordinador
01-d0/
  descubrimiento-odoo · catalogo-de-flujos
02-flujos/
  flujo-entendimiento · flujo-configuracion · flujo-implementacion
  introspeccion-odoo-solo-lectura · plantilla-skill-de-dominio
03-carga/
  bucle-de-correccion · ajustes-de-aplicacion · entornos-y-seguridad
04-compartidos/
  contrato-implementacion-odoo · jev-decisiones-agentes · odoo-rpc-transporte
  taxonomia-errores-odoo · odoo19-diferencias · localizacion-chile
AJUSTES-A-SKILLS-EXISTENTES.md
```

## Qué skill carga cada agente

| Skill | Coord. | D0 | Flujos (×4) | CARGA |
|---|:-:|:-:|:-:|:-:|
| `contrato-implementacion-odoo` | ● | ● | ● | ● |
| `jev-decisiones-agentes` | | ● | ● | ● |
| `orquestacion-del-proyecto` | ● | | | |
| `puntos-de-control-consultor` | ● | | | |
| `correo-consultor` | ● | | | |
| `jev-decisiones-coordinador` | ● | | | |
| `descubrimiento-odoo` | | ● | | |
| `catalogo-de-flujos` | | ● | | |
| `flujo-entendimiento` | | | ● | |
| `flujo-configuracion` | | | ● | |
| `flujo-implementacion` | | | ● | |
| `introspeccion-odoo-solo-lectura` | | | ● | |
| `flujo-<flujo>` (solo el suyo) | | | ● | |
| `odoo-rpc-transporte` | | | ● | ● |
| `taxonomia-errores-odoo` | | | ● | ● |
| `odoo19-diferencias` | | | ● | ● |
| `localizacion-chile` | | | ● | ● |
| `convencion-ids-externos` (existente) | | | ● | ● |
| `sandbox-de-codigo-en-opencompany` (existente) | | | ● | ● |
| `carga-a-odoo-y-verifica` (existente, con ajustes) | | | | ● |
| `administrar-casos-de-borde-odoo` (existente, con ajustes) | | | | ● |
| `scripts-verificados-de-carga-odoo` (existente, con ajustes) | | | | ● |
| `bucle-de-correccion` | | | | ● |
| `ajustes-de-aplicacion` | | | | ● |
| `entornos-y-seguridad` | | | | ● |

Skills de plataforma del Coordinador: `task-manager`, `write-todos`, `jev`. Los demás agentes también cargan `jev`.

`plantilla-skill-de-dominio` no la carga ningún agente: es la guía para escribir los cuatro `flujo-<flujo>`.

## Cómo instalarlo

1. Crea los seis nodos con estos nombres: D0 Descubrimiento · Flujo Financiero (Contabilidad, Tesorería y Facturación) · Flujo de Ventas y Servicios · Flujo de Compras y Aprobaciones · Flujo de Inventario y Fabricación · CARGA.
2. Conéctalos todos al `input-teammates` del Coordinador y copia el ID de cada uno a la tabla de equipo del prompt (`<NODE_ID_…>`).
3. Carga a cada agente los skills de la tabla de arriba.
4. Credenciales de Odoo: usuario de **solo lectura** en los cuatro flujos, usuario con escritura solo en CARGA. `ms_mail` y `jev` en el Coordinador; `jev` también en D0, flujos y CARGA.
5. Trigger del Coordinador: correo entrante, filtrado por el prefijo `[<empresa>-<sesion_id_corto>]` del asunto.
6. Al arrancar un proyecto, entrega al Coordinador las direcciones del consultor (`consultores_autorizados` en `coordinador/estado.json`). Sin ellas no actúa sobre ninguna respuesta.
7. Aplica los cambios de `AJUSTES-A-SKILLS-EXISTENTES.md` a los skills que ya tenías.

## Lo que falta

- Los cuatro skills de dominio `flujo-<flujo>` (siguen la estructura de `plantilla-skill-de-dominio`). Cuando existan, `catalogo-de-flujos` se regenera desde su sección 1. **Ubicación**: carpetas planas en `server/skills/odoo_impl/` (`flujo-financiero/`, `flujo-ventas-servicios/`, `flujo-compras-aprobaciones/`, `flujo-inventario-fabricacion/`) — la plataforma descubre skills a dos niveles (grupo/skill) y los nombres no admiten `/`.
- Los umbrales de JEV (0,8 general, 0,7 y 0,3 en usos puntuales) son valores iniciales sin calibrar; se ajustan con los logs `jev-*.jsonl`.
- `odoo19-diferencias` y `localizacion-chile` marcan cada hecho como observado o hipótesis; hay que confirmarlos con `fields_get` en tu instancia y ponerles fecha.
