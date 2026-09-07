# Flujo: contabilidad

> Esqueleto. Completar siguiendo `_plantilla-flujo.md`. Leer junto con `l10n-cl.md`,
> que es donde vive la mayor parte de la complejidad chilena.

## 1. Alcance funcional

Plan de cuentas, diarios, impuestos, facturación de clientes y proveedores,
conciliación bancaria, saldos iniciales y cierre. Es el flujo que recibe el impacto
de todos los demás: si ventas o inventario están mal configurados, se ve acá.

## 2. Módulos requeridos

`account`, `l10n_cl`, `l10n_cl_edi`. Conciliación bancaria automática según banco.

## 3. Objetos de configuración

- Plan de cuentas: se parte del chileno de la localización y se extiende.
- Diarios por tipo de documento.
- Ejercicio fiscal y períodos de bloqueo.
- Método de valorización de inventario y sus cuentas.
- Cuentas por defecto en categorías de producto.

## 4. Objetos de carga

| NN | Modelo | Campos mínimos | Trampas |
|----|--------|----------------|---------|
| 05 | `account.account` | `id, code, name, account_type` | Solo las cuentas adicionales; el plan chileno ya viene con el módulo |
| 07 | `account.tax` | `id, name, amount, type_tax_use` | IVA viene con la localización; no duplicarlo |
| 11 | `account.journal` | `id, name, type, code` | [COMPLETAR] relación con tipos de documento |
| 82 | `account.move` (apertura) | `id, journal_id/id, date, line_ids/...` | El asiento de apertura debe cuadrar exactamente; una diferencia de un peso lo deja en borrador |
| 84 | `account.move` (documentos abiertos) | — | Facturas pendientes de cobro y pago: van una por una, no como saldo agregado, si el cliente necesita antigüedad de saldos |

## 5. Reglas de validación propias

- Asiento de apertura cuadrado: suma de débitos igual a suma de créditos.
- [COMPLETAR] Cuenta de cada línea existente y activa.
- Documentos abiertos con fecha anterior a la fecha de corte.
- [COMPLETAR] Coherencia entre saldo de clientes en apertura y suma de facturas
  abiertas cargadas.

## 6. Casos de QA canónicos

1. Factura de cliente completa: emisión, contabilización, cobro, conciliación.
2. Factura de proveedor: recepción, contabilización, pago.
3. [COMPLETAR] Cierre de período: verificar que el balance cuadra y que el informe de
   IVA refleja lo esperado.
4. Antigüedad de saldos contra los documentos abiertos cargados.

## 7. Preguntas al cliente

- ¿Fecha de corte para el arranque?
- ¿Migra documentos abiertos o solo saldos?
- ¿Cuántos ejercicios anteriores necesita en el sistema?
- ¿Quién concilia el banco y con qué frecuencia?
- ¿Usa centros de costo o contabilidad analítica?
