# Telegram: respuestas, conversaciones y cripto

La versión 0.3.0 usa la migración aditiva `0006`. Conserva un solo Worker, Neon y los menús de los negocios.

## Responder a los clientes

El cliente escribe normalmente en el bot del negocio. El propietario y los administradores con permiso **Soporte** reciben el mensaje en ese mismo bot. Para contestar, mantienen pulsado el mensaje y eligen **Responder** de Telegram (en escritorio, clic derecho → Responder). La respuesta llega al chat privado del cliente desde el bot.

Se admiten texto, fotos, vídeos, documentos, audio, notas de voz, animaciones, stickers y videomensajes. Los archivos llegan acompañados de un aviso con el nombre y el ID del cliente. Se puede responder al aviso o al archivo. La conversación queda en la bandeja del negocio.

El equipo debe haber iniciado el bot para que Telegram permita enviarle avisos. Cada respuesta comprueba nuevamente los permisos y el destinatario original. Responder no borra un formulario de configuración abierto. Una entrega incierta no se reenvía automáticamente.

Si hay una transferencia o un pago cripto pendiente, una foto/PDF puede corresponder al comprobante. El botón **Enviar comprobante** selecciona el pedido; si hay varios pendientes, el bot pide elegir uno.

## Obtener el ID y añadir equipo

Cada persona envía `/id` al bot del negocio para obtener su propio ID numérico. También funciona en el maestro y como `/id@usuario_del_bot`. No necesita abrir primero el maestro: usar `/id` registra su identidad verificada para poder añadirla al equipo. El propietario usa ese número en **Administradores** y asigna los permisos necesarios.

## Binance y billeteras de depósito

En el **bot del negocio**: `/admin` → **Métodos de pago** → **Cripto / Binance** → **Añadir billetera**.

1. Elegir USDT, USDC, BTC, BNB, ETH, SOL, TON o XRP.
2. Elegir o escribir la red exacta de depósito.
3. Copiar la dirección pública de esa moneda y red.
4. Añadir Memo / Tag cuando corresponda; escribir `-` si no se exige.
5. Añadir instrucciones y una foto del QR, o `-` para omitirlos.
6. Revisar y confirmar; habilitar el método.

Se pueden guardar hasta 20 direcciones por bot, con distintas monedas y redes. La disponibilidad de cada depósito se comprueba en la billetera del titular: las redes del menú son ejemplos, no una conexión ni una validación en Binance. Deben coincidir activo, red, dirección y memo. [Ayuda oficial de Binance](https://www.binance.com/en/support/faq/detail/85a1c394ac1d489fb0bfac0ef2fceafd).

En **Planes → Precios**, añadir un precio **Cripto / Binance** en la moneda correspondiente. El comprador elige una red disponible y recibe el importe, dirección, memo, instrucciones y QR. El pedido conserva esas instrucciones aunque se cambie la configuración posteriormente.

El cliente envía una imagen o PDF del comprobante. En **Comprobantes**, un administrador verifica el ingreso y puede **aprobar**, **rechazar**, pedir otro comprobante o marcarlo sospechoso. Aprobar activa la suscripción una sola vez. Los reembolsos se realizan en la billetera y se registran después con su referencia; el bot no mueve fondos ni consulta una cuenta de Binance.

Se mantiene la regla existente de Telegram: compras de contenido o acceso digital dentro de Telegram usan Stars; los métodos manuales se ofrecen para operaciones permitidas. [Telegram Stars](https://core.telegram.org/bots/payments-stars).

Los métodos anteriores corresponden a **comprador → negocio**. Los cobros de tus facturas SaaS siguen en el maestro, dentro de **Pagos SaaS**, con su propio historial y saldo.

## Invitaciones y prueba

**Invitaciones** conserva los enlaces asociados a planes: duración, canales incluidos, vencimiento y usos máximos. Su historial muestra quién utilizó el enlace; repetirlo no suma días otra vez.

Las nuevas pruebas gratuitas de la plataforma duran **tres días exactos**, una sola vez por propietario. `TRIAL_DAYS=3`; el antiguo valor 7 se normaliza a 3. La actualización conserva los vencimientos de accesos ya concedidos.

## Rendimiento

La recepción por polling guarda el mensaje cifrado, el avance del lector y el trabajo en una operación PostgreSQL. La selección de trabajos respeta el orden antes de ocupar un consumidor. Se redujeron consultas repetidas y esperas de cola; el acuse de los botones se solapa con el procesamiento.

El recorrido del maestro `/start` y `/admin` bajó de 36 a 17 consultas SQL en la comparación aislada. Con 100 ms añadidos por consulta, la mediana pasó de 3.678 a 1.767 ms. Telegram estaba simulado: esto **no es una medición del tiempo real en Seenode**. [Datos de la comparación](performance-0006.json).

Los registros del Worker incluyen `telegram_response bot=master response_ms=…`, medido desde la entrada al proceso hasta la confirmación de envío de Telegram. Permiten comprobar la mejora real sin registrar el contenido ni el ID de la persona.
