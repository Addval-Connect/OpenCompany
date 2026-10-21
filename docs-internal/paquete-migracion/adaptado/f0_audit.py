#!/usr/bin/env python3
"""F0 — Auditoría read-only del workflow ArmandoMigrador en addval-connect.

Corre en el EC2:  sudo -u oc-app-user python3 /tmp/f0_audit.py
Imprime: esquema de la BD, workflows existentes, y todo el detalle del workflow
cuyo slug/nombre contenga 'Migrador' (grafo, parámetros de nodos, snapshots de skills).
"""
import json
import sqlite3

DB = "/home/oc-app-user/.opencompany/namespaces/addval-connect/workflow.db"
FILTRO = "Migrador"
TRUNC = 160  # truncado de valores largos para la auditoría


def trunc(v):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s[:TRUNC] + f"…[{len(s)} chars]" if len(s) > TRUNC else s


con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
cur = con.cursor()

print("=" * 30, "ESQUEMA", "=" * 30)
for row in cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"):
    print(f"\n-- {row['name']}\n{row['sql']}")

print("\n" + "=" * 30, "WORKFLOWS", "=" * 30)
tablas = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
wtab = next((t for t in tablas if "workflow" in t.lower() and "parameter" not in t.lower()
             and "snapshot" not in t.lower()), None)
print("tabla de workflows:", wtab)
wrows = list(cur.execute(f"SELECT * FROM {wtab}")) if wtab else []
cols_w = wrows[0].keys() if wrows else []
objetivo = None
for r in wrows:
    blob = " ".join(str(r[c]) for c in r.keys())
    marca = " <== MIGRADOR" if FILTRO.lower() in blob.lower() else ""
    # línea de resumen por workflow
    ident = {c: trunc(r[c]) for c in r.keys() if c.lower() in ("id", "slug", "name", "title", "nombre")}
    print(json.dumps(ident, ensure_ascii=False) + marca)
    if marca and objetivo is None:
        objetivo = r

if objetivo is None:
    print(f"\n!! Ningún workflow contiene '{FILTRO}' en sus columnas. Revisa arriba.")
    raise SystemExit(0)

print("\n" + "=" * 30, f"WORKFLOW OBJETIVO: fila completa", "=" * 30)
for c in objetivo.keys():
    print(f"{c}: {trunc(objetivo[c])}")

wid = objetivo["id"] if "id" in objetivo.keys() else None

# Tablas hijas que referencian el workflow
print("\n" + "=" * 30, "FILAS RELACIONADAS", "=" * 30)
for t in sorted(tablas):
    if t == wtab:
        continue
    cols = [r[1] for r in cur.execute(f"PRAGMA table_info({t})")]
    ref_col = next((c for c in cols if c.lower() in ("workflow_id", "workflowid")), None)
    if ref_col:
        n = cur.execute(f"SELECT COUNT(*) FROM {t} WHERE {ref_col}=?", (wid,)).fetchone()[0]
        print(f"\n-- {t} ({n} filas del workflow {wid}); columnas: {cols}")
        for r in cur.execute(f"SELECT * FROM {t} WHERE {ref_col}=?", (wid,)):
            d = {c: trunc(r[c]) for c in r.keys()}
            print(json.dumps(d, ensure_ascii=False))
    elif wtab in t or (cols and "node" in t.lower()):
        print(f"\n-- {t} (sin FK directa; columnas: {cols}) — primeras 3 filas:")
        for r in list(cur.execute(f"SELECT * FROM {t} LIMIT 3")):
            print(json.dumps({c: trunc(r[c]) for c in r.keys()}, ensure_ascii=False))

con.close()
print("\nF0 AUDIT OK")
