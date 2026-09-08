# Seenode · Un Worker y Neon

Actualizar el Worker existente **974896**, de este repositorio. No crear otros servicios ni modificar el servicio anterior `telegram-saas-bot` (974381).

| Campo | Valor |
|---|---|
| Tipo | Worker |
| Repositorio | `gabolaurav123/Plataforma-SaaS` |
| Rama / raíz | `main` / `.` |
| Runtime | Python 3.13 |
| Instancia | Basic: 512 MB, 0.25 vCPU |
| Réplicas | 1 |
| Puerto / dominio | No aplica |

Build: `pip install -r requirements.lock && pip install --no-deps -e .`

Inicio: `alembic upgrade head && python scripts/grant_api.py && python scripts/seed.py && python -m platform_app.polling`

El proceso ejecuta lectores de Telegram, colas interactivas, trabajos de fondo y mantenimiento. Usa conexiones HTTP persistentes y no consulta Neon por cada espera vacía de Telegram. La cola despierta con mensajes o trabajos pendientes.

## Variables

Usar [worker.env.example](../deploy/seenode/worker.env.example). El asterisco `NOMBRE*=` marca un secreto en el editor de Seenode; en `.env` local se escribe sin asterisco.

| Variable | Configuración |
|---|---|
| `ENVIRONMENT` | `production` |
| `DEPLOYMENT_MODE` | `telegram` |
| `DATABASE_URL` | Neon pooler, rol limitado `platform_api` |
| `SYSTEM_DATABASE_URL` | Misma base, pooler, rol `neondb_owner`; solo backend de confianza |
| `MIGRATION_DATABASE_URL` | Misma base, conexión directa de `neondb_owner` |
| `MASTER_BOT_TOKEN` | Token del nuevo maestro, secreto |
| `MASTER_BOT_USERNAME` | `Subscriptionwbot`, sin @, coincidente con el token |
| `PLATFORM_OWNER_IDS` | IDs numéricos de administradores de plataforma, separados por comas |
| `ENCRYPTION_KEYS` / `ACTIVE_KEY_VERSION` | Conservar el JSON secreto existente y `v1` |
| `RECEIPT_STORAGE` | `database` |
| `STORAGE_PATH` | `./storage` |
| `MAX_UPLOAD_BYTES` | `5242880` |
| `TRIAL_DAYS` | `3`; el antiguo valor 7 se normaliza a 3, sin recortar pruebas ya iniciadas |
| `BILLING_GRACE_DAYS` | `3`; el propietario puede modificar la política para ciclos futuros desde Telegram |
| `INTERACTIVE_WORKERS` / `BACKGROUND_WORKERS` | `2` / `2` |
| `TELEGRAM_TRANSPORT` | `polling` |
| `PAYMENT_WEBHOOKS_ENABLED` | `false` |
| `POLLING_TIMEOUT` | `25` segundos |
| `MAINTENANCE_INTERVAL` | `900` segundos |
| `POLLING_MAX_BOTS` | `20` |
| `WORKER_LEASE_SECONDS` | `180` |
| `BOT_RPS` / `TENANT_RPS` | `20` / `30` |
| `GLOBAL_RPS` / `USER_RPS` | `300` / `1`; límites, no promesas de capacidad |
| `DEMO_ENABLED` / `TELEGRAM_TEST_ENVIRONMENT` | `false` / `false` |

No se necesitan `REDIS_URL`, `PORT`, `PUBLIC_API_URL`, `MINI_APP_URL`, `ALLOWED_ORIGINS` ni `MASTER_WEBHOOK_SECRET` mientras solo se use polling. Las tres URL de base de datos apuntan a una única base.

## Actualización y verificación

1. Guardar una copia recuperable de la base y del keyring por separado. El [procedimiento de recuperación](recuperacion.md) incluye una restauración aislada.
2. Ejecutar las pruebas y verificar las migraciones antes de publicar el código.
3. Actualizar la misma instancia. Evitar que dos procesos hagan polling del mismo token. Un conflicto 409 se registra como error, no se ignora.
4. Verificar el registro `telegram_worker_ready`, la revisión `0006`, la ausencia de trabajos fallidos y `/start` seguido de `/admin` en el maestro.
5. El cliente activa la prueba y conecta su bot; el negocio se configura dentro del bot conectado.

La retirada de accesos vencidos puede demorarse hasta el intervalo de mantenimiento. Los accesos nuevos comprueban la fecha real. Bajar el intervalo aumenta actividad en Neon.

El Worker existente está activo con una réplica Basic; el panel muestra **US$4/mes**. Esta actualización conserva la misma instancia y no crea servicios adicionales. La tarifa se consulta en [Seenode](https://seenode.com/pricing). El consumo de Neon depende de su plan. [Workers](https://seenode.com/docs/how-to/deploy-a-worker).
