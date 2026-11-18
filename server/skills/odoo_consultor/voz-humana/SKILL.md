---
name: "voz-humana"
description: "Tono y contenido de todo correo al consultor: partir por lo que se necesita de él o lo que cambia para él, lenguaje llano, nada de componentes internos, nunca anunciar lo que no ocurrió. Cárgalo antes de redactar cualquier correo, junto con el skill de lenguaje del flujo."
metadata:
  author: opencompany
  version: "1.0"
  category: "odoo_consultor"
  icon: "🗣️"
  color: "#0E7490"

---

# Voz humana

Cómo suena y qué contiene un correo al consultor. Este skill habla solo de tono y contenido; el formato lo definen las plantillas del skill de correo y el vocabulario y los estados visibles, el skill de lenguaje del flujo (ver Precedencia).

## Parte por lo que le toca a él

El correo abre con lo que se necesita del consultor o con lo que cambia para él, nunca con lo que hizo el sistema. "Terminamos el análisis de tu contabilidad" no es una apertura; lo es "necesito que definas cómo se factura un servicio".

## Lenguaje llano

Frases cortas, una idea por párrafo, una petición por ítem. Sin siglas ni palabras que el consultor no usa en su trabajo: si un concepto técnico hace falta, tradúcelo con el vocabulario del skill de lenguaje del flujo.

## No nombres componentes internos

El consultor no ve agentes, nodos, herramientas, estados de tarea, códigos de tarea o de etapa, rutas de archivos, hashes ni JSON: nada de eso aparece en el correo. Se mantienen solo los ids que el consultor usa para responder (por ejemplo, D-00-01). Lo que el sistema hizo se cuenta por su efecto: "quedó cargado el plan de cuentas", sin decir quién ni con qué lo hizo.

## Nunca anuncies algo que no ocurrió

No digas "adjunto" si el envío no lleva adjunto, y no prometas acciones que no se hicieron. Si algo falló, dilo en una frase y déjalo pendiente: qué falló y qué queda esperando. No lo escondas ni lo disimules.

## Un correo por turno

Un solo correo por turno y por destinatario. Nunca un correo de "complemento" que agregue lo que faltó en el anterior: si faltaba algo, eso va en el correo del siguiente turno.

## Contexto justo

El consultor ya tiene el contexto de los correos anteriores del hilo: una línea para ubicar el tema y directo a lo nuevo. No repitas lo que ya sabe ni vuelvas a contar el historial.

## Si algo está bloqueado

Una frase con qué falta y quién lo desbloquea. Si lo desbloquea el consultor, la petición va en la lista de acciones; si lo desbloquea otra persona, nómbrala por su rol, sin detalles internos.

## Dudas numeradas

Cada duda va numerada, una pregunta por número. Separa dos clases de duda, con las etiquetas que defina el skill de lenguaje del flujo: la decisión que solo el consultor puede tomar, y la acción que alguien debe hacer en el sistema (por ejemplo, corregir credenciales de acceso). Nunca las mezcles en el mismo ítem.

## Ejemplo

ANTES (así no; un solo párrafo lleno de interno):

"[párrafo único lleno de siglas y términos internos]"

DESPUÉS (referencia; ajústalo al vocabulario del flujo):

"Recibí el modelamiento de Inés Órdenes. Es el mismo archivo que ya revisamos el 20/10, así que el listado de configuraciones pendientes sigue vigente y va adjunto. Ahí van el estado de las configuraciones y 5 riesgos; el principal: la base está en modo demo y eso bloquea pasar a producción. Para avanzar necesito tus respuestas a las 25 definiciones iniciales (D-00-01 a D-00-25)."

Seguido de la lista de acciones pendientes.

## Precedencia

tono y contenido manda `voz-humana`; formato del correo mandan las plantillas del skill de correo; vocabulario y estados visibles manda el skill de lenguaje del flujo.
