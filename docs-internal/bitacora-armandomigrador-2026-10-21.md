# Bitácora — ArmandoMigrador: 5 agentes por API de workers.bluedoc-ai.com (21 oct 2026)

> Registro de la sesión del 21/oct/2026 sobre el workflow **ArmandoMigrador_1** del namespace
> **`addval-connect`** en el host EC2 `i-019e13ccd38631d6e` (IP `98.83.165.137`, dominio
> `workers.bluedoc-ai.com`). Workflow id `82cf40bda56a4daba32cb8cde027caaa`.
> Acceso usado en esta sesión: **API REST del app con cookie de sesión** (el SSH del host está
> roto; ver §2). Estado al cierre: **flujo mutado a 5 agentes, desplegado en la BD y verificado**.

## 1. Contexto

Tarea: crear un flujo **ArmandoMigrador** (migración de contabilidad histórica a Odoo 19) a partir
de la copia que el operador ya había recortado a 3 agentes (Coordinador, D0 Descubrimiento, CARGA;
19 nodos / 22 aristas). Fuente de diseño: paquete **`skills-migracion-odoo`** (24 archivos) que el
consultor recibió — carpeta `~/ADDVAL/Armando/ArmandoMigrador/`, idéntica byte a byte al zip
`~/Descargas/skills-migracion-odoo_0691.zip` (verificado con `diff -rq`). Los prompts vigentes de
los 3 agentes del flujo están en `~/ADDVAL/Armando/ArmandoOdoo/` (`COORD SM`, `DO SM`,
`CARGA SM`) — ahí se confirmaron los nombres reales de las herramientas de plataforma:
`data`, `odoo_jsonrpc`, `process_manager`, `jev`, `ms_mail`, `task_manager`, `write_todos`,
`document_parser`, `taskTrigger`.

Decisiones del operador: **5 agentes** (fiel al paquete; D0→Analista, +Transformador, +Auditor),
skills **inline en el canvas** (repo solo como consolidación posterior), correo al consultor igual
que ArmandoOdoo, homologación crea cuentas nuevas y mapea a existentes, asientos se cargan en
**borrador** (publicación por lotes verificados).

## 2. Bloqueo de acceso y cómo se resolvió

1. `deploy/ec2/ssh.sh` colgaba: TCP a :22 abría, pero la sesión moría post-auth. `ssh -vvv`
   mostró la secuencia completa: llave aceptada (`Server accepts key` tras EC2 Instance Connect
   push `Success: true`), sesión abierta, comando enviado → **sin respuesta del lado remoto**
   (`channel free` sin salida). Con llave errada el rechazo era instantáneo, con la válida el
   cuelgue era post-autenticación: patrón de `systemd-logind`/PAM wedged o sshd roto.
2. **Reboot de la instancia** (autorizado por el operador; `aws ec2 reboot-instances`): boot
   limpio (consola nueva: `Reached target graphical.target`), pero sshd quedó **sin banner**
   (TCP acepta, `head -c 60 </dev/tcp/...` expira). Sigue roto — pendiente de diagnóstico por
   consola AWS (Session Manager no está configurado: sin rol SSM en la cuenta).
3. Mientras tanto el app **sí responde**: `/health` → 200 OK; nginx canonicaliza a
   `workers.bluedoc-ai.com` (DNS de ese dominio = la misma IP del EC2 — el `addvalconnect.com`
   de `core/config.py` es un ejemplo de plantilla, no el despliegue).
4. Vía elegida: **API REST con la cookie `opencompany_token`** del operador (JWT con
   `active_namespace: addval-connect`, exp 28-oct). Ciclo:
   `GET /api/database/workflows/{id}` (grafo normalizado) + `GET/POST
   /api/database/node-parameters/{node_id}` (params por nodo) + `POST /api/database/workflows`
   (guardado atómico por `handle_save_workflow`). Mejor que el SQL directo: el handler hidrata
   los params **desde la BD** (`load_node_parameters`), normaliza y sanitiza el grafo — el
   roundtrip no borra el almacén de parámetros.

## 3. Ejecución

### 3.1 Backup lógico (antes de escribir)
`backup_grafo_completo.json` + `backup_params_<nodo>.json` para los 19 nodos, en
`/tmp/opencode/mut_migrador/`. Reversible: re-POST del grafo y params originales.

### 3.2 Contenido adaptado (paquete → plataforma)
Script `adaptar_contenido.py`: 5 prompts + 19 skills; sustituciones exactas y verificadas
(0 menciones `sandbox`/`fileRead`/`workspace_read`):
- `sandboxed_python` / skill `sandbox-de-codigo-en-opencompany` (retirada el 20-oct) →
  **`process_manager` + `data`** (patrón S1: script por `data`, `python3` real, stdout 1 línea
  JSON; el Transformador escribe `06-lotes/` así).
- `archivos`/`fileRead` → `data`.
- `odoo-rpc-transporte` del paquete: **+ Override de instancia por llamada** (PR #50, el paquete
  no lo traía) y ruta de introspección → `02-instancia/introspeccion.json` (contrato migración).
- `convencion-ids-externos`: validador → Auditor; + abreviaturas `account.move`/`account.move.line`.
- `scripts-verificados-de-carga-odoo`: rutas al contrato migración (`06-lotes/lotes/…`,
  `08-carga/capacidades-instancia.json`).
- Las 6 skills "compartidos" del paquete **no son copias exactas** de `odoo_impl`: están
  adaptadas al dominio migración (rutas `07-auditoria/`, roles, fases). Se usaron las del paquete.

### 3.3 Mutación del flujo (script `mutar.py`, `apply` idempotente)
- **Nodos +5**: `aiAgent:3` (Transformador de Migración), `aiAgent:4` (Auditor de Migración),
  `masterSkill:4/5` (sus skills), `odooJsonRpc:2` (Odoo JSON-RPC (lectura)); **+2**: `msMail:1` y
  `msMailReceive:1` **clonados de ArmandoOdoo_1** (mailbox compartido `8699b75d-…`, poll 60s,
  `msMailReceive --output-main--> input-main`).
- **Params**: 13 escrituras `POST node-parameters`: `system_message` nuevo en los 5 agentes
  (el Coordinador direcciona por **label** — convención del flujo vigente — no por id crudo:
  placeholders `<NODE_ID_…>` → `Analista de Migración` / `Transformador de Migración` /
  `Auditor de Migración` / `CARGA Migración`), `skills_config` en los 5 masterSkill (Coord 10 /
  Analista 12 / CARGA 12 / Transformador 7 / Auditor 8 entradas, proyecto con
  `isCustomized: true`), y params clonados para el `odooJsonRpc:2` (sin credenciales) y el par
  de correo.
- **Aristas**: +14 (skills de los 2 agentes nuevos, `odooJsonRpc:2`→A/T/Au, `dataSource:2`→T/Au
  compartido, `processManager:1`→T/Au, ambos `output-top → input-teammates` al Coordinador, par
  de correo), **−5** (`jev:2→CARGA` — el paquete: "CARGA no tiene JEV ni correo";
  `documentParser:1→CARGA` — lee lotes CSV, no documentos; y 3 filas del **duplicado**
  `masterSkill:3→aiAgent:2` que traía la copia).
- **Agentes renombrados** (label en grafo y params): D0 → `Analista de Migración`, Carga →
  `CARGA Migración`.

Resultado: **26 nodos / 32 aristas**. Model/provider intactos (`openrouter` /
`z-ai/glm-5.3-flash`, heredados).

## 4. Verificación (read-back completo)

`mutar.py verify`: 12 aristas nuevas `OK ×1` (ninguna duplicada), 5 prompts **byte-iguales** al
contenido adaptado, 5 `skills_config` con **exactamente** el set esperado por agente, y sin
leftovers de las aristas eliminadas. El `masterSkill:3` de CARGA — que en la copia estaba
**vacío** (solo `process-manager-skill` con `instructions: ""`) — quedó con el runbook completo.

## 5. Estado al cierre

- Flujo mutado y verificado en la BD del namespace; el canvas del operador debe **refrescarse**
  para verlo.
- Repo: `server/skills/odoo_migracion/` (19 skills con frontmatter + README) y
  `docs-internal/paquete-migracion/` (paquete original + `adaptado/` = lo desplegado inline)
  creados, **sin commit** (rama/PR es decisión del operador). Tests de skills/nodos: 42 passed.

## 6. Pendientes

1. **D-00-21 (heredado de ArmandoOdoo, bitácora 20-oct §7.2)**: base Odoo objetivo —
   `addval-connect-ines-ordenes-main-30408809` vs `addval-connect-odoo-ecominera-main-36600018`.
   La confirma el consultor; **los 2 `odooJsonRpc` del migrador deben apuntar a la instancia
   que recibirá la migración** (precondición del paquete: contabilidad base ya configurada), y
   la `estrategia.yaml` (P2/P3) debe coincidir literalmente con esas credenciales.
2. **Credenciales Odoo** (F3): `odooJsonRpc:1` con usuario de integración **de escritura**;
   `odooJsonRpc:2` con usuario **solo-lectura** (hoy vacíos; el flujo heredó el patrón de
   "usuario de integración dedicado", no el admin compartido).
3. **Mailbox compartido**: ArmandoMigrador clona el buzón `8699b75d-…` de ArmandoOdoo — dos
   Coordinadores hacen poll del mismo inbox y compiten. Decidir buzón dedicado para migración o
   convivencia por el prefijo `[<empresa>-<sesion_id_corto>]`; verificar que el nodo Outlook
   Mail muestre su credencial Microsoft tras el clon.
4. **SSH del host** (independiente del flujo): diagnóstico por consola AWS
   (`systemctl status ssh`, `journalctl -u ssh`); sin él no hay backup binario de
   `workflow.db` — recomendado antes de la primera carga a producción.
5. **F4 — pruebas del instructivo en staging**: asiento de prueba (0 documentos tributarios /
   0 folios consumidos), `name` al publicar (secuencia vs número origen), `action_post`,
   `reconcile`, cuadratura en cero; corrida P1→P5 con archivo pequeño y **ensayo desde cero**
   antes de la primera migración real.
6. **Consolidación en repo**: rama + PR con `server/skills/odoo_migracion/` y
   `docs-internal/paquete-migracion/`; si se corrige un hecho de Odoo en una skill, en ambos
   folders (ver README de `odoo_migracion`).

## 7. Lecciones

- **Transcribir un JWT a mano lo rompe**: el token con `\u00ed` escapado se corrompió al
  reescribirlo (`\udued`) y la firma murió con un error engañoso ("Invalid or expired session").
  La vía robusta fue decodificar el payload para ver qué tramo estaba dañado y retranscribir
  byte a byte; la mejor es que el token no pase por el chat (heredoc local del operador).
- **Bug de aridad en las comparaciones**: eliminar aristas comparando tuplas de 4 contra pares de
  2 no matchea nunca y el paso se ejecuta "con éxito" en silencio (0 eliminadas). El verify con
  conteos exactos (`x1` por arista esperada) fue lo que lo hizo visible.
- **La API de la plataforma es una alternativa completa al SSH para mutar flujos**: el handler
  `handle_save_workflow` hidrata parámetros desde la BD y normaliza el grafo — un roundtrip
  GET→POST no destruye el almacén de `node_parameters` (verificado en
  `services/workflow_context_migration.py:load_node_parameters`).
- **Auditar siempre el grafo resultante contra el diseño, no contra la intención**: la copia del
  operador traía aristas duplicadas, un masterSkill de CARGA vacío y sin nodos de correo — nada
  de eso se ve en el conteo de nodos.
