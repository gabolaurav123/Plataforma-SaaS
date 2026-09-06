# Facturación y resumen de consumo

## Dos registros financieros separados

`payments/payment_charges/payment_refunds` registra dinero de compradores a negocios. `platform_invoices/platform_settlements/invoice_adjustments` registra obligaciones y liquidaciones del negocio a la plataforma. Aprobar una factura SaaS no crea ventas en el negocio.

| Plan | Cuota cada 30 días | Comisión |
|---|---:|---:|
| STARTER | USD 0 | 8% |
| PRO | USD 30 | 4% |
| AGENCY | USD 80 | 1% |

La cuenta comienza con una prueba explícita de tres días, sin comisión ni cuota SaaS. Al seleccionar un plan se inicia el ciclo comercial confirmado. La cuota y comisión se facturan al cierre. Los cambios posteriores de plan se programan para el ciclo siguiente. Las modificaciones de tarifas no reescriben ciclos ni ventas anteriores.

## Ejemplo del resumen que recibe el cliente

```text
Plan: PRO
Periodo: inicio → fin (30 días)

Ventas confirmadas: 1000.00 USD
Devoluciones: 0.00 USD
Cuota fija: USD 30.00
Comisión del plan: 4%
Comisión calculada: USD 40.00
Ajustes/descuentos: USD 0.00
Total facturado: USD 70.00
Pagos registrados: USD 0.00
SALDO A PAGAR: USD 70.00
Fecha límite: fin del ciclo + tolerancia

Bots: utilizados / límite
Contactos registrados: utilizados / límite
Administradores: utilizados / límite
Difusiones y exportaciones: uso / límite del mes UTC
```

Es un ejemplo, no una factura real. El resumen real se genera desde las operaciones confirmadas y acompaña el aviso de factura. El uso mostrado en una factura queda guardado al emitirla; la cuenta muestra también el uso actual. Los recursos no añaden cargos por unidad: el precio es cuota fija más comisión.

## Monedas, devoluciones y redondeo

Los importes se guardan como enteros en la unidad mínima de la moneda. USD usa centavos; XTR usa Stars. Se conserva por venta la tasa de comisión y la conversión a USD. No se suman monedas diferentes ni se aplica una conversión inventada.

El propietario configura una tasa acordada en **centavos USD por unidad mínima de la moneda**. Por ejemplo, para XTR la unidad es una Star. Sin tasa, la factura queda `NEEDS_RATE`: el saldo no se presenta como un importe cobrable conocido. Resolver la conversión queda auditado y concede el plazo de pago correspondiente.

Las devoluciones usan la comisión y conversión de la venta original. Los créditos se incorporan al ciclo abierto o como ajuste explícito de la factura cerrada cuando no hay ciclo abierto. Se redondea la comisión una vez por factura; los reembolsos parciales conservan el total acumulado. Un descuento es un ajuste, nunca un pago recibido.

El neto de reportes del negocio es cobros confirmados menos devoluciones registradas en el periodo, antes de tasas de procesamiento, impuestos o facturas SaaS. Se utiliza la fecha de reconocimiento en el sistema, no la visita del cliente a una página de éxito.

## Vencimientos y liquidación

Estados principales: `TRIAL`, `ACTIVE`, `PAYMENT_PENDING`, `OVERDUE`, `SUSPENDED`, `CANCELLED`; una factura puede requerir conversión antes de su cálculo definitivo. Hay avisos de prueba a 24 horas, tres horas y al terminar, y avisos de ciclo y deuda.

El impago suspende operaciones comerciales al vencer la tolerancia. Permite consultar información y resolver facturas; los datos se conservan. El sistema no sigue acumulando cuotas fijas durante meses de suspensión. Cancelar conserva el periodo vigente y su obligación final. Las suspensiones del propietario se mantienen hasta su intervención.

Transferencia/cripto requieren instrucciones de destino configuradas por el propietario. Las liquidaciones admiten comprobante, referencia, activo/red, importe USD y revisión con nota; pueden ser parciales. Una referencia repetida no se aplica a otra factura ni se aprueba dos veces. Aprobar requiere verificar el ingreso real: el bot no deduce que una imagen demuestra un pago.
