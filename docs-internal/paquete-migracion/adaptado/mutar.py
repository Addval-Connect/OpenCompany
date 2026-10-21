#!/usr/bin/env python3
"""Mutación de ArmandoMigrador_1 (vía API del app, con backup lógico previo).

  python3 mutar.py backup   -> descarga params de los 19 nodos + grafo (JSON locales)
  python3 mutar.py apply    -> escribe params + grafo mutado (5 agentes)
  python3 mutar.py verify   -> re-GET y compara contra lo esperado

Pasos previos ya hechos: backup del grafo (backup_*.json) y adaptación de contenido
(contenido/prompts/*.md, contenido/skills/*.md).
"""
import glob
import json
import sys
import urllib.request

BASE = "https://workers.bluedoc-ai.com"
W = "82cf40bda56a4daba32cb8cde027caaa"
PREFIJO = f"{W}:"
CK = "opencompany_token=" + open("/tmp/opencode/mut_migrador/cookie.txt").read().strip()
DIR = "/tmp/opencode/mut_migrador"

NODO_TIPOS = {
    "ai_employee:1": "Coordinador",
    "aiAgent:1": "Analista",
    "aiAgent:2": "Carga",
    "aiAgent:3": "Transformador",
    "aiAgent:4": "Auditor",
    "masterSkill:1": "ms_coord",
    "masterSkill:2": "ms_analista",
    "masterSkill:3": "ms_carga",
    "masterSkill:4": "ms_transformador",
    "masterSkill:5": "ms_auditor",
    "odooJsonRpc:1": "odoo_escritura",
    "odooJsonRpc:2": "odoo_lectura",
}

SETS = {
    "ms_coord": {
        "platform": ["skill", "task-manager", "jev-decisions", "ms-mail-skill", "write-todos-skill"],
        "proyecto": ["orquestacion-migracion", "puntos-de-control-migracion", "correo-consultor-migracion",
                     "jev-migracion", "contrato-migracion"],
    },
    "ms_analista": {
        "platform": ["skill", "jev-decisions", "process-manager-skill"],
        "proyecto": ["migracion-analisis", "migracion-diseno", "dominio-migracion", "contrato-migracion",
                     "jev-migracion", "odoo-rpc-transporte", "taxonomia-errores-odoo", "localizacion-chile",
                     "convencion-ids-externos"],
    },
    "ms_carga": {
        "platform": ["skill", "process-manager-skill"],
        "proyecto": ["migracion-carga", "bucle-de-correccion", "odoo-rpc-transporte", "taxonomia-errores-odoo",
                     "entornos-y-seguridad", "contrato-migracion", "dominio-migracion", "localizacion-chile",
                     "odoo19-diferencias", "scripts-verificados-de-carga-odoo"],
    },
    "ms_transformador": {
        "platform": ["skill", "process-manager-skill"],
        "proyecto": ["migracion-transformacion", "dominio-migracion", "contrato-migracion",
                     "convencion-ids-externos", "localizacion-chile"],
    },
    "ms_auditor": {
        "platform": ["skill", "process-manager-skill"],
        "proyecto": ["migracion-auditoria", "dominio-migracion", "contrato-migracion",
                     "taxonomia-errores-odoo", "odoo-rpc-transporte", "localizacion-chile"],
    },
}

# fuente de cada snapshot de plataforma, para clonarlo a los masterSkill nuevos
PLATAFORMA_FUENTE = {"skill": "masterSkill:2", "jev-decisions": "masterSkill:2",
                     "process-manager-skill": "masterSkill:2", "task-manager": "masterSkill:1",
                     "ms-mail-skill": "masterSkill:1", "write-todos-skill": "masterSkill:1"}

# PROMPTS/SETS de skills por agente (system_message)
PROMPTS = {
    "Coordinador": ("ai_employee:1", "prompts/coordinador.md"),
    "Analista": ("aiAgent:1", "prompts/analista.md"),
    "Carga": ("aiAgent:2", "prompts/carga.md"),
    "Transformador": ("aiAgent:3", "prompts/transformador.md"),
    "Auditor": ("aiAgent:4", "prompts/auditor.md"),
}

LABELS = {
    "aiAgent:1": "Analista de Migración",
    "aiAgent:2": "CARGA Migración",
    "aiAgent:3": "Transformador de Migración",
    "aiAgent:4": "Auditor de Migración",
    "odooJsonRpc:2": "Odoo JSON-RPC (lectura)",
}

EDGES_ADD = [  # (source, target, sourceHandle, targetHandle)
    ("msMail:1", "ai_employee:1", "output-tool", "input-tools"),
    ("msMailReceive:1", "ai_employee:1", "output-main", "input-main"),
    ("masterSkill:3", "aiAgent:2", "output-tool", "input-skill"),  # re-agregada sin el duplicado
    ("masterSkill:4", "aiAgent:3", "output-tool", "input-skill"),
    ("masterSkill:5", "aiAgent:4", "output-tool", "input-skill"),
    ("odooJsonRpc:2", "aiAgent:1", "output-tool", "input-tools"),
    ("odooJsonRpc:2", "aiAgent:3", "output-tool", "input-tools"),
    ("odooJsonRpc:2", "aiAgent:4", "output-tool", "input-tools"),
    ("dataSource:2", "aiAgent:3", "output-tool", "input-tools"),
    ("dataSource:2", "aiAgent:4", "output-tool", "input-tools"),
    ("processManager:1", "aiAgent:3", "output-tool", "input-tools"),
    ("processManager:1", "aiAgent:4", "output-tool", "input-tools"),
    ("aiAgent:3", "ai_employee:1", "output-top", "input-teammates"),
    ("aiAgent:4", "ai_employee:1", "output-top", "input-teammates"),
]
EDGES_REMOVE = [  # (source, target) — todas sus variantes
    ("jev:2", "aiAgent:2"),            # CARGA migrador: sin JEV (paquete)
    ("documentParser:1", "aiAgent:2"), # CARGA lee lotes CSV, no documentos
    ("masterSkill:3", "aiAgent:2"),    # duplicada; se re-agrega una sola
]

# node-parameters a escribir: {node: {..params..}} — se construye en run()
NODE_IDS = [f"{W}:{n}" for n in NODO_TIPOS]
FUENTES_NODO = {"aiAgent:3": "aiAgent:1", "aiAgent:4": "aiAgent:1",
                "masterSkill:4": "masterSkill:2", "masterSkill:5": "masterSkill:2",
                "odooJsonRpc:2": "odooJsonRpc:1"}


def api(path: str, payload: dict | None = None, method: str = "GET") -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Cookie": CK, "Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def cargar_grafo() -> dict:
    d = api(f"/api/database/workflows/{W}")
    return d["workflow"]


def clave(e):
    return (e.get("source", "").replace(PREFIJO, ""), e.get("target", "").replace(PREFIJO, ""),
            e.get("sourceHandle"), e.get("targetHandle"))


def backup() -> None:
    grafo = cargar_grafo()
    json.dump(grafo, open(f"{DIR}/backup_grafo_completo.json", "w"), ensure_ascii=False, indent=1)
    nodos = grafo["data"]["nodes"]
    print(f"grafo: {len(nodos)} nodos / {len(grafo['data']['edges'])} aristas")
    ok = 0
    for n in nodos:
        ref = n["id"]
        d = api(f"/api/database/node-parameters/{urllib.request.quote(ref, safe='')}")
        params = d.get("parameters") or {}
        out = f"{DIR}/backup_params_{ref.replace(PREFIJO, '').replace(':', '_')}.json"
        json.dump(params, open(out, "w"), ensure_ascii=False, indent=1)
        ok += 1
        print(f"  {ref.replace(PREFIJO,''):>24} -> {out.split('/')[-1]} ({len(json.dumps(params))} chars)")
    print(f"BACKUP OK: {ok} nodos")


ID_PLACEHOLDERS = [  # el prompt del paquete usa <NODE_ID_...>; el flujo real direcciona por label
    ("<NODE_ID_ANALISTA>", "Analista de Migración"),
    ("<NODE_ID_TRANSFORMADOR>", "Transformador de Migración"),
    ("<NODE_ID_AUDITOR>", "Auditor de Migración"),
    ("<NODE_ID_CARGA>", "CARGA Migración"),
]


def prompt_texto(rol: str) -> str:
    archivo = PROMPTS[rol][1]
    texto = open(f"{DIR}/contenido/{archivo}", encoding="utf-8").read().strip()
    if rol == "Coordinador":
        for ph, label in ID_PLACEHOLDERS:
            texto = texto.replace(ph, label)
    return texto


def _params_agente(rol: str) -> dict:
    nodo, archivo = PROMPTS[rol]
    fuente = FUENTES_NODO.get(nodo, nodo)
    base = json.load(open(f"{DIR}/backup_params_{fuente.replace(':', '_')}.json"))
    base["label"] = LABELS.get(nodo, base.get("label", ""))
    base["system_message"] = prompt_texto(rol)
    return base


def _params_masterskill(ms: str) -> dict:
    cfg = {}
    fuentes_ms = {**PLATAFORMA_FUENTE}
    for nombre in SETS[ms]["platform"]:
        f = fuentes_ms.get(nombre, "masterSkill:2")
        src = json.load(open(f"{DIR}/backup_params_{f.replace(':', '_')}.json"))["skills_config"][nombre]
        cfg[nombre] = src  # entrada platform completa (enabled/required/isCustomized/instructions)
    for nombre in SETS[ms]["proyecto"]:
        cuerpo = open(f"{DIR}/contenido/skills/{nombre}.md", encoding="utf-8").read().strip()
        cfg[nombre] = {"enabled": True, "isCustomized": True, "instructions": cuerpo}
    return {"skills_config": cfg}


def _params_odoo(ms: str = "odooJsonRpc:2") -> dict:
    base = json.load(open(f"{DIR}/backup_params_odooJsonRpc_1.json"))
    base["label"] = LABELS["odooJsonRpc:2"]
    return base


def apply() -> None:
    # 1) parámetros
    escrituras = {}
    for rol, (nodo, _) in PROMPTS.items():
        escrituras[f"{W}:{nodo}"] = _params_agente(rol)
    for ms in SETS:
        escrituras[f"{W}:{ms}"] = _params_masterskill(ms)
    escrituras[f"{W}:odooJsonRpc:2"] = _params_odoo()
    for t, pf in {"msMail:1": "backup_params_msMail_1.json",
                  "msMailReceive:1": "backup_params_msMailReceive_1.json"}.items():
        escrituras[f"{W}:{t}"] = json.load(open(f"{DIR}/{pf}"))

    for node_id, params in escrituras.items():
        r = api("/api/database/node-parameters", {"node_id": node_id, "parameters": params}, "POST")
        estado = "OK" if r.get("success") else f"FALLO {r}"
        print(f"params {node_id.replace(PREFIJO,''):>24}: {estado}")
        if not r.get("success"):
            sys.exit(1)

    # 2) grafo
    grafo = cargar_grafo()
    data = grafo["data"]
    nodos = data["nodes"]
    existentes = {n["id"].replace(PREFIJO, "") for n in nodos}
    faltantes = [t for t in NODO_TIPOS if t not in existentes]
    posiciones = {n["id"].replace(PREFIJO, ""): n.get("position", {"x": 0, "y": 0}) for n in nodos}

    for t in faltantes:
        fuente = FUENTES_NODO.get(t)
        plantilla = next(n for n in nodos if n["id"] == PREFIJO + fuente)
        nuevo = json.loads(json.dumps(plantilla))
        nuevo["id"] = PREFIJO + t
        off = {"aiAgent:3": (420, 0), "aiAgent:4": (840, 0),
               "masterSkill:4": (420, -260), "masterSkill:5": (840, -260),
               "odooJsonRpc:2": (420, 320)}[t]
        nuevo["position"] = {"x": posiciones[fuente]["x"] + off[0], "y": posiciones[fuente]["y"] + off[1]}
        nuevo["data"] = dict(plantilla.get("data") or {})
        nuevo["data"]["label"] = LABELS.get(t, nuevo["data"].get("label", t))
        nodos.append(nuevo)
        print(f"nodo +   {t} ({NODO_TIPOS[t]}) en ({nuevo['position']['x']:.0f},{nuevo['position']['y']:.0f})")

    # nodos de correo clonados de ArmandoOdoo_1 (mismo namespace/dueño)
    ao = json.load(open(f"{DIR}/armandoodoo_grafo.json"))["workflow"]["data"]
    coord_pos = posiciones["ai_employee:1"]
    for t, tipo in {"msMail:1": "msMail", "msMailReceive:1": "msMailReceive"}.items():
        if t in {n["id"].replace(PREFIJO, "") for n in nodos}:
            continue
        plantilla = next(n for n in ao["nodes"] if n["type"] == tipo)
        nuevo = json.loads(json.dumps(plantilla))
        nuevo["id"] = PREFIJO + t
        nuevo["position"] = ({"x": coord_pos["x"] - 420, "y": coord_pos["y"] + 80} if tipo == "msMailReceive"
                             else {"x": coord_pos["x"] - 160, "y": coord_pos["y"] + 360})
        nodos.append(nuevo)
        print(f"nodo +   {t} ({tipo}, clon de ArmandoOdoo) en ({nuevo['position']['x']:.0f},{nuevo['position']['y']:.0f})")

    for t in ("aiAgent:1", "aiAgent:2"):
        for n in nodos:
            if n["id"] == PREFIJO + t:
                n["data"]["label"] = LABELS[t]

    aristas = data["edges"]
    antes = len(aristas)
    a_eliminar = {(src, tgt) for src, tgt in EDGES_REMOVE}
    aristas[:] = [e for e in aristas if (e.get("source", "").replace(PREFIJO, ""),
                                        e.get("target", "").replace(PREFIJO, "")) not in a_eliminar]
    print(f"aristas -  {antes - len(aristas)} eliminadas (jev/docparser a CARGA, duplicada)")

    plantilla_arista = aristas[0]
    for src, tgt, sh, th in EDGES_ADD:
        ya = any(clave(e) == (src, tgt, sh, th) for e in aristas)
        if ya:
            continue
        e = json.loads(json.dumps(plantilla_arista))
        e["id"] = f"edge-{src.split(':')[-1]}-{tgt.split(':')[-1]}-{th.replace('input-', '')}"
        e["source"], e["target"], e["sourceHandle"], e["targetHandle"] = PREFIJO + src, PREFIJO + tgt, sh, th
        for k in ("markerEnd", "markerStart", "style", "animated", "type"):
            e.pop(k, None) if k in e and k not in plantilla_arista else None
        aristas.append(e)
        print(f"arista + {src} --{th}--> {tgt}")

    data["nodes"], data["edges"] = nodos, aristas
    r = api("/api/database/workflows", {"workflow_id": W, "name": grafo["name"], "data": data}, "POST")
    print("save:", "OK" if r.get("success") else r)
    if not r.get("success"):
        sys.exit(1)
    print(f"APPLY OK: {len(data['nodes'])} nodos / {len(data['edges'])} aristas")


def verify() -> None:
    grafo = cargar_grafo()
    data = grafo["data"]
    nodos = {n["id"].replace(PREFIJO, ""): n for n in data["nodes"]}
    print(f"grafo: {len(nodos)} nodos / {len(data['edges'])} aristas")
    esperados = set(NODO_TIPOS) | {"masterSkill:1", "masterSkill:2", "masterSkill:3", "dataSource:1",
                                    "dataSource:2", "dataSource:3", "jev:1", "jev:2", "writeTodos:1",
                                    "taskManager:1", "console:1", "chatTrigger:1", "taskTrigger:1",
                                    "processManager:1", "documentParser:1", "odooJsonRpc:1",
                                    "msMail:1", "msMailReceive:1"}
    faltan = esperados - set(nodos)
    sobran = set(nodos) - esperados
    if faltan or sobran:
        print("FALTAN:", faltan, "| SOBRAN:", sobran)
    aristas = [clave(e) for e in data["edges"]]
    for e in EDGES_REMOVE:
        if e in aristas:
            print(f"ARISTA QUE DEBÍA IR Y SIGUE: {e}")
    for src, tgt, sh, th in EDGES_ADD:
        n = sum(1 for a in aristas if a[:2] == (src, tgt) and a[2] == sh and a[3] == th)
        print(f"{'OK ' if n == 1 else 'MAL'} {src} --{th}--> {tgt} (x{n})")
    # prompts y sets
    for rol, (nodo, archivo) in PROMPTS.items():
        p = api(f"/api/database/node-parameters/{urllib.request.quote(PREFIJO + nodo, safe='')}")["parameters"]
        sm = p.get("system_message", "")
        esperado = prompt_texto(rol)
        print(f"prompt {nodo:>14}: {'OK' if sm == esperado else 'DIFIERE'} ({len(sm)} chars)")
    for ms, cfg in SETS.items():
        p = api(f"/api/database/node-parameters/{urllib.request.quote(PREFIJO + ms, safe='')}")["parameters"]["skills_config"]
        esperado = set(cfg["platform"]) | set(cfg["proyecto"])
        print(f"skills {ms:>14}: {'OK' if set(p.keys()) == esperado else 'DIFIERE ' + str(set(p.keys()) ^ esperado)} ({len(p)} entradas)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"backup": backup, "apply": apply, "verify": verify}.get(cmd, lambda: print("usa: backup | apply | verify"))()
