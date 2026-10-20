# Flujo: <nombre>

Plantilla para agregar un flujo nuevo. Copiar, renombrar y completar. No crear una
skill nueva para un flujo: toda la lógica ya existe en las ocho skills, lo que falta
son estos datos.

## 1. Alcance funcional

Qué procesos de negocio cubre y dónde termina. Explícitar qué queda fuera: la mitad
de los conflictos de alcance en implementación nacen de un flujo que "obviamente"
incluía algo.

## 2. Módulos requeridos

| Módulo técnico | Para qué | Enterprise/Community |
|----------------|----------|----------------------|

## 3. Objetos de configuración

Los que ejecuta un agente por API, sin planilla. Con las decisiones que hay que tomar
antes.

## 4. Objetos de carga

Los que van a planilla para el consultor. Con `NN` del orden de carga, campos
mínimos, campos frecuentes y trampas conocidas.

## 5. Reglas de validación propias del flujo

Además de las genéricas del validador. Las que si no se chequean revientan en la
carga o, peor, dejan datos consistentes pero funcionalmente inútiles.

## 6. Casos de QA canónicos

El recorrido punta a punta con aserciones sobre estados, stock y asientos. Un flujo
no está implementado hasta que su caso canónico corre verde.

## 7. Preguntas al cliente

Las que el discovery debe resolver antes de generar el blueprint de este flujo.
