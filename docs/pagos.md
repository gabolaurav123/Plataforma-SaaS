# Métodos de pago y confirmaciones

## Comprador → negocio

Telegram Stars usa facturas reales, validación de precheckout y `successful_payment`. Para bienes y servicios digitales dentro de Telegram se exige Stars. No se habilitan enlaces de otros proveedores para eludir esa regla. [Documentación oficial](https://core.telegram.org/bots/payments-stars).

Transferencia muestra banco, titular, cuenta, moneda, instrucciones y QR del negocio. Los comprobantes son imágenes o PDF, cifrados y accesibles solo a los roles autorizados. Se detectan hashes exactos y similitudes entre los 500 comprobantes recientes del último año; esto es una señal de revisión, no prueba de pago ni garantía antifraude. La aprobación sospechosa pide confirmación expresa de que se verificó el ingreso.

Stripe y PayPal tienen credenciales cifradas por bot. Los importes salen del servidor y de la compra guardada. La página de retorno nunca activa una suscripción. Las confirmaciones verifican proveedor, firma, cuenta, referencia, importe, moneda y estado; los duplicados no vuelven a activar acceso.

Una confirmación que llega antes de guardar el pago se reintenta durante un intervalo acotado. Si sigue sin correspondencia queda para revisión y puede reconciliarse desde Pagos → Confirmaciones del proveedor. El cuerpo cifrado se conserva hasta 14 días en fallos/revisión; al completarse se elimina.

## Requisitos de Stripe y PayPal

El despliegue actual tiene `PAYMENT_WEBHOOKS_ENABLED=false`, por lo que no permite activar esos medios todavía. Las pruebas son contra respuestas simuladas; no se han utilizado credenciales ni pagos reales.

Para habilitarlos se necesita una entrada pública HTTPS. Puede convertirse la misma instancia en servicio Web, manteniendo un solo proceso y sin página visible, cuando se autorice ese cambio de configuración. No crear un segundo servicio automáticamente.

Configuración del proceso: `DEPLOYMENT_MODE=telegram`, `PAYMENT_WEBHOOKS_ENABLED=true`, `PUBLIC_API_URL=https://dominio-del-servicio`, `PORT=8000`. El puerto publicado debe coincidir. El mismo build e inicio siguen siendo válidos. `TELEGRAM_TRANSPORT=polling` puede mantenerse; cambiar a `webhook` es una decisión distinta y requiere secreto del maestro.

En el bot del negocio → Métodos de pago:

| Proveedor | Datos |
|---|---|
| Stripe | Secret key y webhook signing secret |
| PayPal | Client ID, Client secret, Webhook ID y entorno sandbox/live |

El menú muestra una URL aleatoria `/payments/hooks/<identificador>` propia de ese método. Registrarla en la cuenta correcta del proveedor.

Stripe: `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`, `checkout.session.expired`, `charge.refunded`.

PayPal: `CHECKOUT.ORDER.APPROVED`, `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DENIED`, `PAYMENT.CAPTURE.PENDING`, `PAYMENT.CAPTURE.REFUNDED`.

Stripe y PayPal realizan pagos individuales con renovación manual en esta entrega. La renovación automática implementada corresponde a Stars. Los contracargos/disputas exigen revisión del proveedor; no se presentan como una devolución confirmada automáticamente.

Validar primero en sandbox: compra, firma inválida, importe incorrecto, evento repetido, devolución y revocación de acceso. Después repetir la prueba elegida por el titular en live. [Stripe Checkout](https://docs.stripe.com/api/checkout/sessions/create), [firmas Stripe](https://docs.stripe.com/webhooks/signature), [PayPal Orders](https://developer.paypal.com/api/orders/v2), [webhooks PayPal](https://developer.paypal.com/api/rest/webhooks/rest/).

## Negocio → plataforma

Transferencia y cripto de las facturas SaaS son un registro de liquidación separado. El propietario configura destino y revisa el ingreso. No existe integración con claves privadas de carteras ni movimiento automático de fondos. [Detalle de facturación](facturacion.md).
