# Guía de los menús de Telegram

## Creador

`/start → Crear mi negocio → nombre → Crear bot → nombre y usuario → Crear mi bot`.

El botón abre el mecanismo oficial de Telegram para crear un bot administrado. Al terminar, vuelve al Master con `/start`. La conexión se prepara automáticamente y recibes un aviso. Si BotFather no habilitó Bot Management Mode, se indica el requisito.

Desde el negocio puedes abrir tus bots, estadísticas, plan SaaS, clientes, membresías, pagos, comprobantes, conversaciones, equipo, campañas, automatizaciones y otros registros. Los listados tienen paginación. Los permisos de cada acción dependen del rol.

En cada bot:

- **Nombre, textos y políticas:** cambia un dato por mensaje. Los asistentes se conservan durante 24 horas; `/cancel` los descarta.
- **Foto de perfil:** envía una imagen; se normaliza y se actualiza en el bot hijo.
- **Conectar canal:** usa el enlace de Telegram, concede permisos y pulsa Verificar canales. El propietario del bot debe añadirlo al canal.
- **Planes y precios:** indica nombre, duración, precio, renovación y canal. Se habilita Stars al crear el plan. Después puedes cambiar el precio o desactivar el plan. Las membresías y pagos ya iniciados conservan sus condiciones.
- **Comprobar y publicar:** verifica conexión, textos, plan, cobro, canal y políticas. Primero debes iniciar una conversación con el bot hijo para que pueda enviarte la prueba.
- **Campaña:** escribe el mensaje para guardar un borrador; inicia y confirma el envío desde el registro. Respeta las bajas con `/stop` y los límites de cada plan.
- **Automatización:** esta interfaz permite crear recordatorios de vencimiento y activarlos/desactivarlos. El constructor avanzado del modo web queda aplazado.

En Conversaciones puedes leer mensajes y responder desde el bot correspondiente. En Clientes puedes añadir notas internas. En Equipo puedes asignar SUPERVISOR, PAYMENTS, SALES, SUPPORT o READ_ONLY a una persona que haya iniciado el Master. El propietario no se puede retirar con este menú.

Los comprobantes corresponden a pedidos externos previamente registrados; pueden visualizarse y revisarse desde Telegram. Esta versión no inicia ventas digitales por transferencia dentro del bot: los cobros digitales de Telegram usan Stars. Las integraciones externas y sus formularios quedan aplazados.

## Propietario de la plataforma

Solo los IDs de `PLATFORM_OWNER_IDS` pueden entrar a `/admin` o ver Administrar plataforma.

El administrador consulta cifras globales, negocios, usuarios, bots, cola, errores, auditoría, soporte y precios SaaS. Puede abrir cualquier negocio con acceso administrativo auditado, suspenderlo o conceder días de acceso sin cobro. Suspensiones, concesión de días, campañas y reembolsos presentan una confirmación antes de aplicarse.

No se muestran tokens ni claves. El acceso se determina por ID numérico y permisos actuales, no por el @usuario ni por ocultar botones. Un botón de otra persona, otro bot, caducado o ya utilizado no ejecuta acciones.

## Cliente

En el bot del creador: `/start → Ver planes → plan → políticas → continuar → pago en Stars`. Telegram pide la confirmación de pago. Después de confirmar el cobro, se registra la membresía y se facilita acceso al canal con un enlace individual.

En **Mi membresía** se ven vigencia, acceso y renovación automática. Soporte permite escribir al equipo o abrir el usuario de contacto. `/stop` desactiva campañas y `/start` vuelve a habilitarlas.

## Alcance de esta fase

El funcionamiento se prueba con Telegram simulado y PostgreSQL; todavía debe verificarse con el nuevo Master real. La web existente se conserva para después y no forma parte del despliegue actual. Los listados permiten consultar los registros existentes; las funciones avanzadas de segmentación, edición general de automatizaciones, cupones e integraciones de pago externas no se presentan como implementadas en estos asistentes.
