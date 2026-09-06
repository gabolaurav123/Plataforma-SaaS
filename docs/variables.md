# Variables y secretos

La plantilla es [.env.example](../.env.example). El script de bootstrap crea valores aleatorios locales y no imprime las claves. `apps/web/.dev.vars` sirve solo para el desarrollo del Worker; queda ignorado y fuera del ZIP.

| Variable | Uso y valor inicial |
|---|---|
| `ENVIRONMENT` | `development`; usar `production` en el despliegue real |
| `DATABASE_URL` | SQLite local; en producción DSN PostgreSQL del rol `platform_api` sin privilegios de RLS |
| `SYSTEM_DATABASE_URL` | DSN separado, privado, para bootstrap autenticado, routing, workers y operaciones de plataforma |
| `MIGRATION_DATABASE_URL` | DSN opcional del migrador; si falta se usa el rol de sistema |
| `POSTGRES_PASSWORD` | Contraseña del PostgreSQL nuevo en Compose, generada por bootstrap |
| `PLATFORM_API_PASSWORD` | Contraseña distinta del rol API en Compose, generada por bootstrap |
| `REDIS_URL` | Vacío local; Compose usa su servicio privado Redis |
| `MASTER_BOT_TOKEN` | Token del **nuevo** Master, vacío inicialmente |
| `MASTER_WEBHOOK_SECRET` | Secreto aleatorio de al menos 32 caracteres para autenticar su webhook |
| `MASTER_BOT_USERNAME` | Nombre del nuevo Master sin `@`; las capacidades consultadas a Telegram son la fuente de identidad |
| `PLATFORM_OWNER_IDS` | IDs numéricos Telegram autorizados como propietarios, separados por coma |
| `ENCRYPTION_KEYS` | JSON `{ "v1": "base64-de-32-bytes" }`; secreto, no un ejemplo para copiar literalmente |
| `ACTIVE_KEY_VERSION` | Versión usada para nuevas envolturas, inicialmente `v1` |
| `PUBLIC_API_URL` | Origen HTTPS público del backend, sin barra final |
| `MINI_APP_URL` | Origen HTTPS de ambas Mini Apps, sin barra final |
| `ALLOWED_ORIGINS` | Orígenes de interfaz permitidos, separados por coma; sin comodín |
| `SESSION_TTL_SECONDS` | 1800, sesión de 30 minutos |
| `INIT_DATA_MAX_AGE_SECONDS` | 300, máximo de antigüedad al autenticar |
| `TRIAL_DAYS` | 7; duración configurable de la prueba SaaS |
| `STORAGE_PATH` | `./storage`; volumen privado compartido por API y workers |
| `MAX_UPLOAD_BYTES` | 5242880, máximo 5 MiB por imagen |
| `TELEGRAM_TEST_ENVIRONMENT` | `false`; usar `true` solo con credenciales del entorno de pruebas correspondiente |
| `DEMO_ENABLED` | `false`; no se admite `true` en producción. Los ejemplos visuales fuera de Telegram no crean cuentas ni simulan guardados |
| `WORKER_LEASE_SECONDS` | 180, reserva temporal de trabajo |
| `BOT_RPS` | 20, límite conservador configurable de mensajes salientes por bot |
| `TENANT_RPS` | 30, mensajes salientes por espacio |
| `GLOBAL_RPS` | 300, límite compartido; no es una garantía de capacidad de Telegram |
| `USER_RPS` | 1, mensajes por usuario y bot |
| `PLATFORM_API_URL` | **Solo frontend Worker**: origen del backend, sin `/api`; local `http://localhost:8000`, real HTTPS |

Configura `PLATFORM_API_URL` en el entorno de Sites cuando exista el backend real. El proxy no contiene credenciales Telegram y reenvía la sesión de la Mini App. Nunca pongas tokens en variables públicas del frontend.

En producción conserva la clave de cifrado fuera de los backups de datos, pero con su propia copia recuperable. Perder todas las versiones del keyring hace irrecuperables tokens y comprobantes. Para rotar una clave de envoltura, conserva las anteriores mientras haya registros cifrados con ellas; esta entrega no elimina claves automáticamente.
