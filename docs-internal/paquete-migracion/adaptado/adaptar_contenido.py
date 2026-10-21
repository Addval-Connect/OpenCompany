#!/usr/bin/env python3
"""Genera el contenido adaptado (prompts + skills inline) para ArmandoMigrador.

Origen: paquete skills-migracion-odoo (zip del 21-oct) + 2 skills de biblioteca de
server/skills/odoo_impl. Salida: /tmp/opencode/mut_migrador/contenido/{prompts,skills}/

Adaptaciones de plataforma (sandbox retirado el 20-oct, patrón v2 process_manager+data):
- sandboxed_python / sandbox-de-codigo-en-opencompany -> process_manager + data
- fileRead -> data
- odoo-rpc-transporte: + Override de instancia por llamada (#50), ruta introspeccion.json
- convencion-ids-externos: validador -> Auditor; + abreviaturas move/move_line
- scripts-verificados-de-carga-odoo: rutas del contrato migracion (06-lotes/, 08-carga/)
"""
import os
import re
import shutil

PAQUETE = "/tmp/opencode/skills-migracion/skills-migracion-odoo"
REPO_SKILLS = "/home/inframaya/OpenCompany/server/skills/odoo_impl"
SALIDA = "/tmp/opencode/mut_migrador/contenido"

OVERRIDE = """
### Override de instancia por llamada (opcional, todo o nada)

Por defecto la llamada corre contra la instancia configurada en el nodo. Para apuntar a **otra** instancia, pasa la conexión completa en la llamada: `host` (sin esquema ni ruta), `db`, `username` y `api_key` — **los cuatro juntos o ninguno**; un override parcial se rechaza antes de salir a la red, porque emparejaría un host con las credenciales de otra instancia. Nunca mezcles un override con las credenciales guardadas del nodo. Usos legítimos: credenciales entregadas explícitamente por el consultor en la sesión y verificación de instancia; para el trabajo planificado del proyecto manda `entornos-y-seguridad`.
"""

# (archivo_origen, archivo_destino, [(old_exact, new_exact), ...])
REEMPLAZOS = [
    # ---- PROMPTS ----
    ("00-prompts/system-prompt-coordinador-migracion.md", "prompts/coordinador.md", [
        # Los <NODE_ID_...> se llenan en la mutación con los IDs reales; sin cambios de texto aquí.
    ]),
    ("00-prompts/system-prompt-analista-migracion.md", "prompts/analista.md", [
        ("Archivos del proyecto, `odoo_jsonrpc` **solo lectura**, `sandboxed_python` con `workspace_read` (para perfilar los archivos del cliente sin cargarlos al contexto) y `jev`. No tienes correo.",
         "`data` (archivos del proyecto), `odoo_jsonrpc` **solo lectura**, `process_manager` con `python3` (escribes el script en el workspace con `data` y lo corres con `process_manager`; la salida vuelve por stdout — para perfilar los archivos del cliente sin cargarlos al contexto), `document_parser` para extraer el texto de los documentos del cliente (los `.docx` se leen con `parser: \"docx\"`) y `jev`. No tienes correo."),
    ]),
    ("00-prompts/system-prompt-transformador-migracion.md", "prompts/transformador.md", [
        ("También `convencion-ids-externos`, `localizacion-chile` y `sandbox-de-codigo-en-opencompany`.",
         "También `convencion-ids-externos` y `localizacion-chile`."),
        ("Archivos del proyecto, `sandboxed_python` con `workspace_read` **y una capacidad de escritura del workspace** (para generar los lotes; si no existe, detén la misión y repórtalo), y `odoo_jsonrpc` **solo lectura**. No tienes JEV ni correo.",
         "`data` (archivos del proyecto), `process_manager` con `python3` — el script que escribes con `data` corre como `python3` real y **lee y escribe el workspace**: escribe los lotes en `06-lotes/` y devuelve por stdout solo el resumen, nunca los lotes completos —, y `odoo_jsonrpc` **solo lectura**. No tienes JEV ni correo."),
    ]),
    ("00-prompts/system-prompt-auditor-migracion.md", "prompts/auditor.md", [
        ("También `taxonomia-errores-odoo`, `odoo-rpc-transporte`, `localizacion-chile` y `sandbox-de-codigo-en-opencompany`.",
         "También `taxonomia-errores-odoo`, `odoo-rpc-transporte` y `localizacion-chile`."),
        ("Archivos del proyecto, `odoo_jsonrpc` **solo lectura** y `sandboxed_python` con `workspace_read`.",
         "`data` (archivos del proyecto), `odoo_jsonrpc` **solo lectura** y `process_manager` con `python3` (scripts de solo lectura: el script lo escribes con `data` y corre con `process_manager`; la salida vuelve por stdout)."),
    ]),
    ("00-prompts/system-prompt-carga-migracion.md", "prompts/carga.md", [
        ("`localizacion-chile`, `odoo19-diferencias`, `sandbox-de-codigo-en-opencompany` y `scripts-verificados-de-carga-odoo`.",
         "`localizacion-chile`, `odoo19-diferencias` y `scripts-verificados-de-carga-odoo`."),
        ("Archivos del proyecto, `odoo_jsonrpc` **con escritura** (usuario de integración dedicado) y `sandboxed_python` con `workspace_read`.",
         "`data` (archivos del proyecto), `odoo_jsonrpc` **con escritura** (usuario de integración dedicado) y `process_manager` con `python3` (los scripts S1/S2 de `scripts-verificados-de-carga-odoo`)."),
    ]),
    # ---- SKILLS DEL PAQUETE ----
    ("02-analista/migracion-analisis.md", "skills/migracion-analisis.md", [
        ("Cargas también `dominio-migracion`, `contrato-migracion`, `jev-migracion`, `odoo-rpc-transporte` y `sandbox-de-codigo-en-opencompany`.",
         "Cargas también `dominio-migracion`, `contrato-migracion`, `jev-migracion` y `odoo-rpc-transporte`."),
        ("Los lees con `sandboxed_python` (`workspace_read`) y devuelves solo perfiles, conteos y muestras enmascaradas.",
         "Los lees con scripts `python3` corridos por `process_manager` (el script lo escribes en el workspace con `data` y la salida vuelve por stdout) y devuelves solo perfiles, conteos y muestras enmascaradas."),
        ("2. **Perfila cada archivo** con un script en el sandbox.",
         "2. **Perfila cada archivo** con un script `python3` corrido por `process_manager`."),
    ]),
    ("02-analista/migracion-diseno.md", "skills/migracion-diseno.md", []),
    ("03-transformador/migracion-transformacion.md", "skills/migracion-transformacion.md", [
        ("Cargas también `dominio-migracion`, `contrato-migracion`, `convencion-ids-externos`, `localizacion-chile` y `sandbox-de-codigo-en-opencompany`.",
         "Cargas también `dominio-migracion`, `contrato-migracion`, `convencion-ids-externos` y `localizacion-chile`."),
        ("**Capacidad requerida del sandbox.** La transformación genera archivos grandes en `06-lotes/`. Necesitas un sandbox que pueda **leer y escribir** el workspace (`workspace_read` y una capacidad de escritura; el nombre exacto es `[VERIFICAR]` en tu plataforma). Si no puede escribir, no devuelvas lotes enormes por el contexto: detén la misión con una definición `otro` explicando la limitación.",
         "**Capacidad: `process_manager` con `python3`.** La transformación genera archivos grandes en `06-lotes/`. En esta plataforma el script que escribes con `data` corre como `python3` real vía `process_manager` y **puede leer y escribir el workspace**: escribe los lotes como archivos y devuelve por stdout solo el resumen (manifiesto, conteos, hash). Nunca devuelvas lotes enormes por el contexto."),
    ]),
    ("04-auditor/migracion-auditoria.md", "skills/migracion-auditoria.md", [
        ("Cargas también `dominio-migracion`, `contrato-migracion`, `taxonomia-errores-odoo`, `odoo-rpc-transporte`, `localizacion-chile` y `sandbox-de-codigo-en-opencompany`.",
         "Cargas también `dominio-migracion`, `contrato-migracion`, `taxonomia-errores-odoo`, `odoo-rpc-transporte` y `localizacion-chile`."),
        ("Validas cada lote en el sandbox (no por `fileRead`) y escribes",
         "Validas cada lote con un script `python3` corrido por `process_manager` (no leyéndolo a trozos con `data`) y escribes"),
    ]),
    ("05-carga/migracion-carga.md", "skills/migracion-carga.md", [
        ("`entornos-y-seguridad`, `localizacion-chile`, `odoo19-diferencias`, `sandbox-de-codigo-en-opencompany` y `scripts-verificados-de-carga-odoo` (lectura de CSV).",
         "`entornos-y-seguridad`, `localizacion-chile`, `odoo19-diferencias` y `scripts-verificados-de-carga-odoo` (conversión CSV→payload)."),
    ]),
    ("05-carga/bucle-de-correccion.md", "skills/bucle-de-correccion.md", []),
    ("06-compartidos/contrato-migracion.md", "skills/contrato-migracion.md", []),
    ("06-compartidos/dominio-migracion.md", "skills/dominio-migracion.md", []),
    ("06-compartidos/entornos-y-seguridad.md", "skills/entornos-y-seguridad.md", []),
    ("06-compartidos/localizacion-chile.md", "skills/localizacion-chile.md", []),
    ("06-compartidos/taxonomia-errores-odoo.md", "skills/taxonomia-errores-odoo.md", []),
    ("06-compartidos/odoo19-diferencias.md", "skills/odoo19-diferencias.md", []),
    ("06-compartidos/odoo-rpc-transporte.md", "skills/odoo-rpc-transporte.md", [
        ("Devuelve `{ok: true, result: …}` o `{ok: false, error: {...}}`. El esquema es cerrado: un argumento inventado se rechaza antes de salir a la red.",
         "Devuelve `{ok: true, result: …}` o `{ok: false, error: {...}}`. El esquema es cerrado: un argumento inventado se rechaza antes de salir a la red.\n" + OVERRIDE.rstrip() + "\n"),
        ("Todo lo marcado `[VERIFICAR]` se confirma contra la instancia y el resultado se guarda en `02-instancia/introspeccion-<flujo>.json`.",
         "Todo lo marcado `[VERIFICAR]` se confirma contra la instancia y el resultado se guarda en `02-instancia/introspeccion.json`."),
    ]),
    ("06-compartidos/jev-migracion.md", "skills/jev-migracion.md", [
        ("El enmascarado lo hace el script del sandbox antes de armar el `state`;",
         "El enmascarado lo hace el script de perfilado corrido por `process_manager` antes de armar el `state`;"),
    ]),
    ("01-coordinador/skills/orquestacion-migracion.md", "skills/orquestacion-migracion.md", [
        ("(comprobable con `fileRead`)", "(comprobable con `data`)"),
        ("2. **Relee los artefactos** con `fileRead` y compáralos con el criterio.",
         "2. **Relee los artefactos** con `data` y compáralos con el criterio."),
    ]),
    ("01-coordinador/skills/puntos-de-control-migracion.md", "skills/puntos-de-control-migracion.md", [
        ("1. **Lee el archivo** del punto con `fileRead`.",
         "1. **Lee el archivo** del punto con `data`."),
    ]),
    ("01-coordinador/skills/correo-consultor-migracion.md", "skills/correo-consultor-migracion.md", []),
    # ---- SKILLS DE BIBLIOTECA (repo odoo_impl v2, adaptadas al dominio migración) ----
    (REPO_SKILLS + "/convencion-ids-externos/SKILL.md", "skills/convencion-ids-externos.md", [
        ("| `account.journal` | `journal` | `product.pricelist` | `pricelist` |",
         "| `account.journal` | `journal` | `product.pricelist` | `pricelist` |\n| `account.move` | `move` | `account.move.line` | `move_line` |"),
        ("es trabajo\ndel validador: `flujo-implementacion`, misión `validacion`. La regla de orden que allí se verifica dice\nque **el grafo `depende_de` es acíclico y ninguna referencia apunta a un objeto que se cargue\ndespués** (ya no se infiere de los nombres de archivo).",
         "es trabajo\ndel Auditor: `migracion-auditoria`, misión `auditoria previa`. La regla de orden que allí se verifica\ndice que **las referencias de un lote apuntan a la instancia o a lotes anteriores de la fase\n`preparacion`**, y que un asiento nunca se parte entre lotes."),
    ]),
    (REPO_SKILLS + "/scripts-verificados-de-carga-odoo/SKILL.md", "skills/scripts-verificados-de-carga-odoo.md", [
        ('ARCHIVO = "06-completadas/product.template.csv"',
         'ARCHIVO = "06-lotes/lotes/asientos_2025-01.csv"'),
        ('PREFIJO = "ecominera"',
         'PREFIJO = "adv_acme"'),
        ('cap = json.loads(leer("02-instancia/capacidades-instancia.json"))',
         'cap = json.loads(leer("08-carga/capacidades-instancia.json"))'),
        ("Cada cosa que el script tuvo que aprender de ti va a `02-instancia/capacidades-instancia.json`",
         "Cada cosa que el script tuvo que aprender de ti va a `08-carga/capacidades-instancia.json`"),
    ]),
]

# Quita frontmatter (los snapshots inline llevan solo el cuerpo)
def quitar_frontmatter(texto: str) -> str:
    if texto.startswith("---"):
        m = re.match(r"^---\n.*?\n---\n", texto, re.DOTALL)
        if m:
            return texto[m.end():].lstrip("\n")
    return texto

def main() -> None:
    if os.path.isdir(SALIDA):
        shutil.rmtree(SALIDA)
    os.makedirs(SALIDA + "/prompts")
    os.makedirs(SALIDA + "/skills")

    avisos = []
    for origen, destino, pares in REEMPLAZOS:
        ruta = origen if origen.startswith("/") else os.path.join(PAQUETE, origen)
        with open(ruta, encoding="utf-8") as f:
            texto = f.read()
        es_repo = origen.startswith("/")
        texto = quitar_frontmatter(texto) if es_repo else texto
        for old, new in pares:
            if old not in texto:
                avisos.append(f"SIN MATCH: {destino} :: {old[:80]}...")
            texto = texto.replace(old, new)
        with open(os.path.join(SALIDA, destino), "w", encoding="utf-8") as f:
            f.write(texto)

    # Verificación global: nada que la plataforma ya no tenga
    prohibidos = ["sandbox-de-codigo-en-opencompany", "sandboxed_python", "workspace_read", "fileRead"]
    problematico = []
    for raiz, _, files in os.walk(SALIDA):
        for fn in sorted(files):
            p = os.path.join(raiz, fn)
            with open(p, encoding="utf-8") as f:
                texto = f.read()
            for token in prohibidos:
                if token in texto:
                    for i, linea in enumerate(texto.splitlines(), 1):
                        if token in linea:
                            problematico.append(f"{p}:{i}: [{token}] {linea.strip()[:100]}")
    if problematico:
        print("== PENDIENTES DE ADAPTAR ==")
        print("\n".join(problematico))
    else:
        print("OK: 0 menciones de sandbox/fileRead/workspace_read en el contenido adaptado")

    if avisos:
        print("== REEMPLAZOS SIN MATCH ==")
        print("\n".join(avisos))

    n_prompts = len(os.listdir(SALIDA + "/prompts"))
    n_skills = len(os.listdir(SALIDA + "/skills"))
    print(f"Generados: {n_prompts} prompts, {n_skills} skills en {SALIDA}")

if __name__ == "__main__":
    main()
