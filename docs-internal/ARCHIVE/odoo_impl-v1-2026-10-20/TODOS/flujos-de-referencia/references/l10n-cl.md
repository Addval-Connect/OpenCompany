# Flujo transversal: localización chilena

No es un flujo funcional, es una capa que condiciona ventas, compras y contabilidad.
Se instala y configura **antes** de cargar terceros y productos, porque agrega campos
obligatorios a `res.partner` y determina la estructura de diarios.

Todo lo de este archivo requiere verificación contra la instancia: los nombres
técnicos de módulos y campos de la localización cambian entre versiones y este
esqueleto se escribió sin una instancia 19 a la vista.

## 1. Módulos

| Módulo | Para qué | Nota |
|--------|----------|------|
| `l10n_cl` | Plan de cuentas chileno, impuestos, RUT | Community |
| `l10n_cl_edi` | Documentos tributarios electrónicos ante el SII | Enterprise [VERIFICAR] |
| `l10n_cl_edi_boletas` | Boletas electrónicas | Solo si el cliente emite boletas [VERIFICAR] |

## 2. Configuración previa a cualquier carga

1. Datos de la compañía: RUT, giro, actividad económica, dirección con comuna.
2. Certificado digital de firma electrónica cargado y vigente.
3. Resolución del SII: número y fecha.
4. Ambiente: certificación vs. producción. **El proceso completo de implementación
   corre en certificación.** Pasar a producción es una tarea aparte del backlog, con
   su propia aprobación.
5. Tipos de documento habilitados y su correspondencia con diarios.
6. CAF (folios) cargados por tipo de documento. Sin CAF vigente no se emite nada y el
   QA de facturación falla con un error que no parece de configuración.

## 3. Impacto en los objetos de carga

**`res.partner`** gana campos que no son opcionales en la práctica:

- `vat` con RUT en formato válido, incluido dígito verificador
- tipo de contribuyente (primera categoría, boleta de honorarios, extranjero, etc.)
- giro y actividad económica
- comuna, que en Chile no es un campo de texto libre sino una entidad

**`account.journal`**: cada tipo de documento electrónico necesita su diario o su
configuración de tipo de documento asociada. Un diario de ventas genérico no alcanza
para emitir factura y boleta al mismo tiempo.

**`account.tax`**: IVA 19% viene con la localización. Los impuestos adicionales
(ILA, específicos, retenciones de honorarios) se cargan aparte y hay que confirmar
cuáles aplican al giro del cliente.

## 4. Impacto en el orden de carga

Se inserta antes del bloque de terceros:

```
01 res.company (con datos SII)
02 certificado + resolución + ambiente
09 l10n_latam.document.type (viene con el módulo, se habilita)
11 account.journal (por tipo de documento)
   ── recién acá ──
20 res.partner
```

Cargar partners antes de tener la localización lista significa recargarlos después
para completar los campos tributarios. Con IDs externos eso es una actualización
limpia, pero igual es trabajo doble para el consultor.

## 5. Validaciones propias

- RUT con dígito verificador correcto (módulo 11). Es la validación que más filas
  rechaza en un proyecto chileno típico.
- RUT único entre partners.
- Tipo de contribuyente coherente con los documentos que se le van a emitir: no se
  puede emitir factura afecta a alguien registrado como no contribuyente.
- Comuna existente en el catálogo, no texto libre.
- Fechas de vigencia del certificado y del CAF por delante de la fecha de arranque.

## 6. QA específico

El QA funcional de ventas y compras no basta. Se agrega:

1. Emisión de cada tipo de documento en uso (33, 34, 39, 52, 56, 61) en ambiente de
   certificación, con verificación de que el DTE fue aceptado.
2. Recepción y acuse de documentos de proveedores.
3. Nota de crédito con referencia al documento original.
4. Consumo de folios: verificar que el correlativo avanza y que hay CAF suficiente.

El set de pruebas de certificación del SII es un hito propio del proyecto, con su
tarea, su responsable y su fecha. No es un caso de QA más.

## 7. Preguntas al cliente

- ¿Qué tipos de documento emite hoy y cuáles necesita en Odoo?
- ¿Ya está certificado ante el SII o hay que certificar?
- ¿Quién administra el certificado digital y cuándo vence?
- ¿Emite boletas? ¿Por punto de venta o desde facturación?
- ¿Hay retenciones (honorarios, cambio de sujeto) en su operación?
- ¿Maneja precios o contratos en UF?
