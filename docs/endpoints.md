# API y permisos

Contrato generado desde la aplicación: [OpenAPI completo](openapi.json). Swagger se sirve en `/docs` del backend.

El frontend usa `/api/backend/` como proxy. Las rutas de la tabla parten directamente del origen del backend.

## Autorización

| Contexto | Control |
|---|---|
| Login | initData HMAC del Master o child correspondiente |
| Creador | Authorization: Bearer + sesión MASTER + membresía vigente en el workspace |
| Cliente | Bearer CUSTOMER vinculado al bot validado y su public_id |
| Propietario | Sesión MASTER y telegram_user_id en PLATFORM_OWNER_IDS |
| Webhook | X-Telegram-Bot-Api-Secret-Token de esa identidad |

| Rol | Operaciones |
|---|---|
| OWNER | Lectura, configuración, pagos, ventas, soporte, equipo, exportación, facturación |
| SUPERVISOR | Lectura, configuración, pagos, ventas, soporte, exportación |
| PAYMENTS | Lectura y pagos |
| SALES | Lectura y ventas |
| SUPPORT | Lectura y soporte |
| READ_ONLY | Lectura |

Retirar un miembro invalida su acceso al workspace aunque conserve una sesión. La suspensión SaaS mantiene lectura y exportación autorizada. Para invocar rutas protegidas desde un cliente HTTP, añadir explícitamente la cabecera Authorization; la documentación automática no emite sesiones de prueba.

## Operaciones

| Método | Ruta | Operación |
|---|---|---|
| POST | `/api/auth/master` | Auth Master |
| GET | `/api/me` | Me |
| POST | `/api/workspaces` | Workspace |
| GET | `/api/saas-plans` | Saas Plans |
| GET | `/api/t/{workspace_id}/onboarding` | Onboarding |
| PUT | `/api/t/{workspace_id}/onboarding` | Save Onboarding |
| GET | `/api/t/{workspace_id}/templates` | Templates |
| GET | `/api/t/{workspace_id}/text-defaults` | Text Defaults |
| POST | `/api/t/{workspace_id}/bots/create` | Create Bot |
| GET | `/api/t/{workspace_id}/bots/{bot_id}/settings` | Bot Settings |
| PUT | `/api/t/{workspace_id}/bots/{bot_id}/settings` | Update Bot |
| POST | `/api/t/{workspace_id}/bots/{bot_id}/photo` | Upload Photo |
| PUT | `/api/t/{workspace_id}/bots/{bot_id}/texts/{key}` | Text Save |
| POST | `/api/t/{workspace_id}/bots/{bot_id}/repair` | Repair |
| POST | `/api/t/{workspace_id}/bots/{bot_id}/rotate-token` | Rotate |
| GET | `/api/t/{workspace_id}/bots/{bot_id}/access` | Access |
| PUT | `/api/t/{workspace_id}/bots/{bot_id}/access` | Access Save |
| GET | `/api/t/{workspace_id}/bots/{bot_id}/readiness` | Readiness |
| POST | `/api/t/{workspace_id}/bots/{bot_id}/publish` | Publish |
| GET | `/api/t/{workspace_id}/bots/{bot_id}/connect-channel` | Channel Link |
| POST | `/api/t/{workspace_id}/channels/{channel_id}/test` | Channel Test |
| POST | `/api/t/{workspace_id}/channels/{channel_id}/native-subscription` | Native Channel |
| POST | `/api/t/{workspace_id}/plans` | Create Plan |
| PUT | `/api/t/{workspace_id}/plans/{plan_id}` | Update Plan |
| PUT | `/api/t/{workspace_id}/providers/{provider}` | Save Provider |
| POST | `/api/t/{workspace_id}/payments/off-platform-bank` | Bank Payment |
| POST | `/api/t/{workspace_id}/receipts/{receipt_id}/review` | Receipt Review |
| GET | `/api/t/{workspace_id}/receipts/{receipt_id}/image` | Receipt Image |
| POST | `/api/t/{workspace_id}/charges/{charge_id}/refund` | Refund |
| PATCH | `/api/t/{workspace_id}/contacts/{contact_id}` | Update Contact |
| POST | `/api/t/{workspace_id}/contacts/{contact_id}/notes` | Note |
| GET | `/api/t/{workspace_id}/conversations/{conversation_id}/messages` | Messages |
| POST | `/api/t/{workspace_id}/conversations/{conversation_id}/messages` | Send Message |
| POST | `/api/t/{workspace_id}/team` | Add Member |
| DELETE | `/api/t/{workspace_id}/team/{member_id}` | Remove Member |
| POST | `/api/t/{workspace_id}/billing/checkout/{plan_id}` | Billing Checkout |
| POST | `/api/support/tickets` | Support Ticket |
| POST | `/api/auth/b/{public_id}` | Auth Customer |
| GET | `/api/b/{public_id}/me` | Profile |
| GET | `/api/b/{public_id}/plans` | Plans |
| POST | `/api/b/{public_id}/checkout` | Checkout |
| POST | `/api/b/{public_id}/payments/{payment_id}/receipt` | Receipt |
| POST | `/api/b/{public_id}/subscriptions/{subscription_id}/renewal` | Renewal |
| POST | `/api/b/{public_id}/support` | Support |
| GET | `/api/t/{workspace_id}/resources/{resource}` | Resources |
| POST | `/api/t/{workspace_id}/campaigns` | Campaign Create |
| POST | `/api/t/{workspace_id}/campaigns/{campaign_id}/action` | Campaign Action |
| POST | `/api/t/{workspace_id}/automations` | Automation Create |
| POST | `/api/t/{workspace_id}/coupons` | Coupon Create |
| POST | `/api/t/{workspace_id}/links` | Link Create |
| GET | `/api/t/{workspace_id}/analytics` | Analytics |
| GET | `/api/t/{workspace_id}/export/{resource}` | Export |
| GET | `/api/owner/health` | Health |
| GET | `/api/owner/master/capabilities` | Capabilities |
| POST | `/api/owner/master/configure` | Configure Master |
| GET | `/api/owner/resources/{resource}` | Resources |
| POST | `/api/owner/tenants/{tenant_id}/action` | Tenant Action |
| PUT | `/api/owner/saas-plans/{plan_id}` | Saas Plan |
| PUT | `/api/owner/tenants/{tenant_id}/features/{key}` | Feature Flag |
| POST | `/telegram/webhook/{public_id}` | Webhook |
| GET | `/health/live` | Live |
| GET | `/health/ready` | Ready |

Total: 62 operaciones HTTP.

## Convenciones

- Importes: enteros de unidades menores al escribir; strings al leer para preservar precisión. XTR no tiene fracciones, MXN/USD usan centavos.
- Listas: limit entre 1 y 100; after y next_cursor. Exportación: hasta 1.000 filas y cabecera X-Next-Cursor.
- Reusar la misma clave de idempotencia al reintentar el mismo checkout o respuesta. Datos incompatibles con una clave previa producen conflicto.
- PUT de un plan conserva su bot/canal; para cambiar acceso se crea otro plan.
- El checkout del cliente fija TELEGRAM_STARS y XTR. El pedido bancario requiere endpoint de creador y referencia externa.
- No hay endpoint que devuelva tokens de bots ni webhook de tarjetas operativo.
- Errores: {code, message}; validación devuelve solo nombres de campos, sin reflejar valores sensibles. X-Request-ID permite correlación.
- El reembolso Stars y las operaciones de acceso requieren permisos; no reintentar ciegamente envíos con estado DELIVERY_UNKNOWN.
