# Telegram: investigación y configuración inicial

Documentación oficial consultada el **6 de septiembre de 2026**, antes de implementar. La página consultada presentaba Bot API **10.3, 24 de agosto de 2026**. Vuelve a comprobar cambios antes de activar producción. [Bot API oficial](https://core.telegram.org/bots/api).

## Master nuevo en BotFather

1. Abre el [BotFather oficial](https://t.me/BotFather), crea otro bot y conserva su token únicamente en el entorno privado de este proyecto.
2. Abre la Mini App de BotFather, selecciona ese nuevo Master y activa **Bot Management Mode** en sus ajustes.
3. Configura la **Main Mini App** del Master con la URL HTTPS del frontend. Para probar con otras personas, la audiencia de ese despliegue debe permitirles entrar; la vista privada entregada es solo para revisión del propietario.
4. Rellena `MASTER_BOT_TOKEN`, `PLATFORM_OWNER_IDS`, `PUBLIC_API_URL` y `MINI_APP_URL` en el servidor.
5. Ejecuta `python scripts/configure_master.py`. El script configura webhook, menú y comandos, y consulta `getMe`.
6. En el panel de propietario pulsa Verificar Master Bot. Debe mostrar `can_manage_bots = true`; si falta la capacidad, vuelve al ajuste de BotFather.

Si necesitas identificar tu ID numérico, pulsa Start en el Master nuevo una vez configurado su webhook y ejecuta `docker compose exec -T api python scripts/list_users.py` en el servidor. El listado privado muestra los últimos usuarios registrados; identifica tu propia cuenta, guarda su número en `PLATFORM_OWNER_IDS` y recrea API/worker con `docker compose up -d --force-recreate api worker`. El script solo lee; nunca concede permisos automáticamente al primer usuario que llegue.

La creación se inicia con la interfaz oficial, mediante botón preparado o un enlace `https://t.me/newbot/{manager}/{username}?name=...`. Esta integración evita pedirle al creador que copie un token. [Guía oficial de management bots](https://core.telegram.org/bots/features#creating-your-own-management-bot).

## Decisiones verificadas

| Área | Contrato aplicado |
|---|---|
| Creación | `KeyboardButtonRequestManagedBot`, `savePreparedKeyboardButton`, `ManagedBotCreated`, `ManagedBotUpdated` |
| Credenciales y acceso | `getManagedBotToken`, `replaceManagedBotToken`, `getManagedBotAccessSettings`, `setManagedBotAccessSettings`: `user_id` identifica al bot administrado |
| Actualizaciones | `Update.managed_bot` identifica propietario y bot; el mensaje `managed_bot_created` identifica el bot y usa `message.from` para el creador |
| Provisioning | `setWebhook`, `setMyName`, `setMyDescription`, `setMyShortDescription`, `setMyCommands`, `setChatMenuButton` |
| Foto | `setMyProfilePhoto` con `InputProfilePhotoStatic` y archivo multipart |
| Acceso | `createChatInviteLink`, `approveChatJoinRequest`, `declineChatJoinRequest`, `revokeChatInviteLink`, `getChatMember`, `banChatMember`, `unbanChatMember` |

Los contratos, campos y permisos están definidos en la [Bot API](https://core.telegram.org/bots/api). La correlación entre solicitud y espacio de trabajo es una decisión del backend; no se inventa un `request_id` dentro de `ManagedBotCreated`.

## Mini Apps

`WebApp.requestChat` usa el ID de un botón preparado, con detección de versión/capacidad; el enlace oficial de creación queda como alternativa. El backend valida `initData` con HMAC y la clave del Master o child correspondiente. Rechaza datos caducados, duplicados o alterados y no confía en `initDataUnsafe`. [Mini Apps oficiales](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app), [requestChat](https://core.telegram.org/bots/webapps#initializing-mini-apps).

Para los clientes, el menú del child apunta a `/b/{public_id}`. El servidor usa la identidad del child para validar su sesión; cambiar el ID en la URL no cambia el acceso autorizado.

## Stars y transferencias

Los bienes y servicios digitales vendidos dentro de Telegram se cobran con Stars. El flujo implementado usa `currency=XTR`, `provider_token` vacío y un precio. Las suscripciones recurrentes usan periodos de 2.592.000 segundos; el precio recurrente admite hasta 10.000 Stars. La suscripción nativa de canal tiene un flujo distinto al invoice del bot. [Pagos digitales con Stars](https://core.telegram.org/bots/payments-stars), [createInvoiceLink](https://core.telegram.org/bots/api#createinvoicelink), [suscripción nativa de canal](https://core.telegram.org/bots/api#createchatsubscriptioninvitelink).

El pre-checkout no concede acceso; lo concede el pago confirmado. `editUserStarSubscription` modifica futuras renovaciones, y `refundStarPayment` permite el reembolso de un cargo. [Renovaciones](https://core.telegram.org/bots/api#edituserstarsubscription), [reembolsos](https://core.telegram.org/bots/api#refundstarpayment).

La transferencia se registra únicamente para un pedido originado fuera del checkout digital de Telegram. Cambiar su nombre o abrir un checkout externo desde la Mini App no lo convierte en una alternativa permitida para estas membresías digitales. El contrato de tarjetas está deshabilitado hasta disponer de una integración y actividad aprobadas.
