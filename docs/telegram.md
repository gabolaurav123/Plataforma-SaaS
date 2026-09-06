# Uso de la plataforma desde Telegram

## Bot maestro: @Subscriptionwbot

`/start` muestra los espacios del propietario, crear un negocio, idioma y ayuda. `/admin` solo está disponible para los IDs configurados como propietarios de la plataforma. La identidad se basa en el ID numérico, nunca en el nombre de usuario.

Para comenzar: **Crear mi negocio → Activar prueba gratuita → Conectar mi bot**. La prueba dura tres días y solo se utiliza una vez por propietario. Un segundo espacio no reinicia el beneficio.

El creador obtiene un token de su bot en BotFather y lo envía en el diálogo privado indicado. El sistema consulta su identidad, muestra usuario e ID y pide confirmar antes de tomar el control. El token se cifra, se retira de la carga persistida de mensajes y se solicita borrar el mensaje de Telegram; Telegram puede impedir el borrado fuera de su ventana. No se garantiza borrar copias previas del historial del usuario.

Un bot ya vinculado a otro negocio no puede apropiarse mediante este formulario. Cambiar token, desconectar y reemplazar son operaciones auditadas; los registros históricos se conservan. El modo Managed Bots anterior sigue siendo compatible, pero la conexión principal usa el token del bot del cliente.

**Mi plan SaaS** entrega un resumen en segundo plano: periodo, tarifa, ventas y devoluciones por moneda, comisión, facturas, saldo, bots, contactos, administradores, difusiones y exportaciones utilizadas. Los límites de difusión y exportación se renuevan por mes calendario UTC; la facturación usa ciclos de 30 días.

## Bot del negocio

Su propietario abre `/start` o `/admin` y recibe el panel de administración. Las cuentas del equipo reciben las opciones permitidas por su rol. **Ver como usuario** abre el flujo de compra, con un botón para regresar al panel.

Configuración inicial:

1. Revisar nombre, descripciones, soporte y políticas del negocio.
2. Añadir el bot como administrador del canal/grupo y verificar permisos para invitar y restringir miembros.
3. Crear un plan, fijar duración, precios y canales incluidos; activar el plan.
4. Configurar el método de pago apropiado al producto. Telegram exige Stars para contenido/acceso digital comprado dentro de Telegram.
5. Revisar los mensajes, elegir idioma, zona horaria y formato de fecha.
6. Comprobar y publicar. La publicación verifica requisitos reales.

Planes permite modificar, duplicar y archivar. Cada compra conserva su precio y sus canales, aunque el plan cambie después. Las suscripciones tienen historial de concesión, extensión, cancelación, reactivación y cambio de plan. Una concesión gratuita no crea pagos ficticios.

Usuarios permite buscar por ID, nombre o usuario y filtrar por estado, vencimiento, plan o historial de compra; incluye notas, etiquetas y operaciones sobre suscripciones. Marcar una etiqueta `VIP` puede generar la alerta habilitada en notificaciones.

Invitaciones genera enlaces con plan, duración, canales, caducidad, límite de usos y nota. La reutilización por la misma persona no concede días adicionales. Su historial muestra quién usó el enlace. El origen de la suscripción es `invite_link`.

Difusiones incluye texto, imagen, video o documento y hasta cuatro botones HTTPS. Se elige audiencia, se revisa la vista previa y se confirma. La audiencia se guarda al comenzar; después puede pausarse o reanudarse. Los contadores reflejan enviados, fallidos, bloqueados y entregas inciertas. Telegram no proporciona lecturas individuales.

Mensajes permite personalizar cada idioma y restaurar los valores originales. Variables: `{name}`, `{username}`, `{plan}`, `{price}`, `{currency}`, `{expiration_date}`, `{days_remaining}`, `{channel}`, `{bot_name}`. No se ejecuta código dentro de las plantillas.

Reportes genera CSV privado con operaciones y referencias reales, por fechas y moneda. El archivo cifrado caduca a los siete días. Los resúmenes diario, semanal y mensual se habilitan en notificaciones y respetan la zona horaria del negocio.

## Propietario de la plataforma

`/admin` ofrece resumen, negocios, usuarios, bots, colas, soporte, auditoría y pagos SaaS. Puede configurar cuotas USD, porcentaje de comisión, periodo de tolerancia, conversiones y métodos de cobro de la plataforma.

Una extensión gratuita no inventa ingresos: amplía el ciclo sin una cuota fija adicional, mantiene la comisión de ventas y registra el motivo. Las deudas pendientes deben resolverse mediante pagos o ajustes explícitos. Una suspensión administrativa no se levanta automáticamente por un pago.

Transferencia y cripto se configuran en **Pagos SaaS → Métodos de cobro**. Allí se guardan banco, titular, cuenta y moneda, o activo, red y dirección pública. Nunca se necesitan claves privadas de una cartera. El cliente presenta la referencia y el comprobante; el propietario verifica el ingreso antes de aprobar.
