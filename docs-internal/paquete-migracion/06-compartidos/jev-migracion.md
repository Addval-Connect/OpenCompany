# JEV en la migración

JEV (TypeSafe) devuelve decisiones tipadas con probabilidad y confianza; no genera texto. En la migración lo usa **el Analista** para entender el formato de origen (tipo de archivo y rol de cada columna) y **el Coordinador** para filtrar las respuestas del consultor. La mecánica general (contrato de `questions`, tipos, respuesta) está en el skill de plataforma `jev`. Nunca se usa para decidir un mapeo de cuenta, tercero o impuesto, ni para cerrar un punto de control ni para autorizar nada.

## Reglas comunes

- Llamada: `jev(state, questions)`, con `questions` como JSON string. Una llamada por unidad evaluada (un archivo, una columna, una respuesta).
- **Preguntas atómicas**, con `instructions` completas y opciones mutuamente excluyentes.
- **Umbral:** confianza ≥ 0,8 actúas; bajo eso usas la **salida segura** del uso (siempre: preguntar al consultor). Un casi-empate en `probabilities` cuenta como confianza baja.
- Si `jev` falla o no está disponible, aplica la salida segura. Nada del flujo depende de que JEV responda.
- Registra cada llamada en `01-analisis/jev-analista.jsonl` (Coordinador: `coordinador/jev-log.jsonl`): `{ts, uso, ref, decisions, confidence, accion}`.

## Privacidad: JEV nunca recibe datos reales del cliente

Los archivos de origen contienen RUT, nombres y montos. **JEV recibe solo encabezados, tipos inferidos y una muestra enmascarada**: RUT como `NN.NNN.NNN-N`, montos como `#`, nombres como `X`, fechas como `DD/MM/AAAA`. El enmascarado lo hace el script del sandbox antes de armar el `state`; nunca se envía una fila real ni se escribe una en un resultado.

## Uso `fuente` (Analista)

Una llamada por archivo y otra por columna. `state` = `{"archivo": ..., "encabezados": [...], "tipos": [...], "muestra_enmascarada": [...]}`.

```json
{
  "tipo_archivo": {
    "type": "choice",
    "instructions": "Decide qué tipo de información contable contiene el archivo según sus encabezados y la muestra",
    "criteria": {
      "plan_de_cuentas": "Lista de cuentas con código y nombre",
      "balance_comprobacion": "Saldos por cuenta a una fecha",
      "libro_diario": "Asientos con sus líneas de debe y haber",
      "libro_mayor": "Movimientos agrupados por cuenta",
      "auxiliar_terceros": "Partidas abiertas o movimientos por cliente o proveedor",
      "libro_compras_ventas": "Documentos de compra o de venta con impuestos",
      "conciliacion_bancaria": "Partidas bancarias conciliadas o pendientes",
      "activos_fijos": "Listado de activos con valores y depreciación",
      "inventario_valorizado": "Productos con cantidades y valores",
      "maestro_terceros": "Clientes y proveedores con RUT",
      "otro": "No corresponde a ninguno de los anteriores"
    }
  },
  "rol_columna": {
    "type": "choice",
    "instructions": "Decide qué representa la columna dentro del archivo, según su encabezado y los valores enmascarados",
    "criteria": {
      "cuenta": "Código de la cuenta contable",
      "nombre_cuenta": "Nombre de la cuenta contable",
      "fecha": "Fecha del movimiento o documento",
      "fecha_vencimiento": "Fecha de vencimiento",
      "numero_comprobante": "Número del asiento o comprobante",
      "tipo_comprobante": "Tipo del comprobante",
      "numero_linea": "Número de línea dentro del asiento",
      "glosa": "Descripción o glosa",
      "debe": "Monto al debe",
      "haber": "Monto al haber",
      "monto_con_signo": "Monto único con signo positivo o negativo",
      "saldo": "Saldo acumulado",
      "rut_tercero": "RUT del cliente o proveedor",
      "nombre_tercero": "Nombre del cliente o proveedor",
      "tipo_documento": "Tipo de documento comercial",
      "numero_documento": "Número del documento comercial",
      "moneda": "Moneda del monto",
      "tipo_cambio": "Tipo de cambio aplicado",
      "centro_costo": "Centro de costo o análisis",
      "otro": "No corresponde a ninguno de los anteriores"
    }
  }
}
```

- ≥ 0,8: lo anotas en `perfil-fuente.json`. **Salida segura:** una pregunta `D-NN` al consultor ("¿qué representa la columna X?"), con las opciones; nunca una suposición.
- Una columna cuyo rol define un signo, un monto o la identidad de un registro (`debe`, `haber`, `monto_con_signo`, `numero_comprobante`, `rut_tercero`) **se confirma siempre** en P2, sin importar la confianza.

## Uso `respuesta` (Coordinador)

Una llamada por ítem `D-NN` respondido. `state` = `{"pregunta": ..., "opciones": [...], "respuesta": ...}` con el texto literal.

```json
{
  "estado_respuesta": {
    "type": "choice",
    "instructions": "Decide si la respuesta del consultor resuelve la pregunta planteada",
    "criteria": {
      "elige_opcion": "Elige una de las opciones listadas sin condiciones",
      "respuesta_libre_valida": "No usa las opciones pero define con claridad qué hacer",
      "ambigua": "Admite más de una interpretación o depende de algo que no dice",
      "sin_respuesta": "No contesta la pregunta, la posterga o la rechaza"
    }
  },
  "ambigua_contable": {
    "type": "noul",
    "instructions": "La respuesta deja dudas sobre cuentas contables, impuestos, tasas, saldos o fechas de corte"
  }
}
```

- `elige_opcion` o `respuesta_libre_valida` con confianza ≥ 0,8 **y** `ambigua_contable` < 0,3: transcribes el texto literal del consultor y cierras el ítem.
- Cualquier otro resultado: no transcribes; pides aclaración en el mismo hilo, citando el `D-NN`.
- Una respuesta sobre la fecha de corte, el tratamiento de saldos o la aprobación de cuadratura se aclara ante cualquier duda.

## Límites

- JEV **nunca** escribe `respuesta:`: lo que se transcribe son las palabras del consultor.
- JEV **no** interviene en la autorización de producción (regla fija en `correo-consultor-migracion`), ni en decidir un mapeo, ni en aceptar tareas, ni en aprobar una cuadratura.
- Una decisión de JEV es una propuesta con una salida segura. Si no hay salida segura clara, no se usa.
