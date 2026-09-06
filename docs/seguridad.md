# Seguridad y límites de la verificación

Esta revisión incluye controles y pruebas automatizadas; no equivale a una auditoría independiente ni a una garantía de ausencia de vulnerabilidades.

## Aislamiento y acceso

- Los registros comerciales están vinculados al negocio y al bot. Se validan recursos, roles y permisos en cada acción, incluida la entrega de trabajos diferidos.
- PostgreSQL usa claves compuestas, RLS forzado y un rol API sin privilegios de sistema. Los diálogos, botones, cursores y ajustes globales no se conceden a ese rol. Los libros financieros y el historial de suscripciones no admiten sus escrituras; la auditoría es de solo anexado para la API.
- El Worker emplea una conexión de sistema privilegiada. RLS no protege contra ese rol: el código de confianza debe comprobar siempre los límites de cada negocio y bot.
- Los callbacks son opacos, privados del actor y del bot, de un solo uso y con caducidad. Cambiar un username no cambia la identidad: se usa el ID numérico de Telegram.
- Las funciones de Mini App y API conservadas validan `initData`, sesión, edad, firma, audiencia y permisos; el despliegue actual no publica esa interfaz.

## Secretos, archivos y pagos

- Tokens, credenciales de proveedores, comprobantes, reportes y actualizaciones sensibles se cifran con AES-GCM y contexto autenticado. El token no se devuelve completo después de su conexión.
- El mensaje que contiene un token se intenta eliminar y su contenido no se conserva en texto claro en los trabajos. Esto no convierte los chats con bots en comunicaciones con cifrado de extremo a extremo.
- No se registran URLs autenticadas, cuerpos de proveedores ni secretos en errores. Los payloads privados se purgan al completar el trabajo; los fallidos se retienen hasta 14 días. Los CSV cifrados caducan a los siete días.
- Las imágenes tienen límites de bytes y píxeles y se normalizan; se admite PDF con inspección de formato y tamaño. No se ofrece un antivirus ni prueba de autenticidad de documentos. El hash exacto y la similitud ayudan a detectar reutilización de comprobantes; la aprobación sigue siendo humana.
- Los pagos validan bot, comprador, plan, moneda, importe e identidad del cargo. Confirmaciones, comisiones, liquidaciones y reembolsos parciales tienen claves de idempotencia e historial.
- Stripe valida la firma y el tiempo del webhook y vuelve a comprobar el pago. PayPal verifica el evento y consulta/captura la orden en servidor. Ambos requieren configuración real e ingreso HTTPS; permanecen desactivados en este Worker.
- El checkout digital dentro de Telegram exige Stars. Las transferencias del negocio se limitan a operaciones permitidas por su contexto; los registros de liquidación de la plataforma no acreditan por sí mismos que un método cumpla las reglas comerciales de Telegram.
- Reportes con aislamiento, permisos y protección contra fórmulas de hojas de cálculo. Campañas con confirmación, opt-out, cuotas, límites de envío, manejo de 429 y estados de entrega desconocida sin reenvío automático ciego.

## Evidencia y operación

Se verificaron aislamiento y permisos en PostgreSQL PGlite, migración con datos existentes y restauración de una copia cifrada real de la nueva base Neon. Consultar [pruebas](pruebas.md) y [recuperación](recuperacion.md) para alcance, cantidades y resultados.

El respaldo incluye tablas y registros administrados por las migraciones; no incluye roles del servidor ni archivos externos. El keyring se conserva por separado. La pérdida de claves impide recuperar datos cifrados.

Quedan como operación continua: respaldos periódicos, acceso restringido al panel de Seenode/Neon, revisión de trabajos fallidos, actualización de dependencias y pruebas de carga antes de crecer. La eliminación/anonimización de una cuenta completa no está automatizada; debe aplicarse una política de retención y atención a solicitudes de datos. Los proveedores de pago requieren pruebas reales con credenciales del negocio antes de habilitar cobros.
