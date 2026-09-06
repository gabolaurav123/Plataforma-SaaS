# Configurar Creator Engine en Seenode con Neon

Repositorio: https://github.com/gabolaurav123/Plataforma-SaaS · rama `main`.
Usar el commit más reciente que incluya `build:seenode` y la migración `0003`.
Crear servicios nuevos; no editar `telegram-saas-bot` ni conectar su token o su base de datos.

## Servicios

En Seenode: **Crear nuevo → tipo de servicio → Git repository → Conectar Plataforma-SaaS**.

| Nombre sugerido | Tipo | Imagen | Directorio raíz | Puerto | Réplicas |
|---|---|---|---|---|---|
| plataforma-saas-api | Web | Python 3.13 | `.` | `8000` | 1 |
| plataforma-saas-worker | Worker | Python 3.13 | `.` | Sin puerto | 1 |
| plataforma-saas-web | Web | Node 24 | `apps/web` | `3000` | 1 |
| plataforma-saas-redis | Servicio privado | Docker `redis:8.2.9-alpine` | No aplica | `6379` | 1 |

Neon conserva la base PostgreSQL. Redis se utiliza para límites compartidos y caché; la cola persistente está en PostgreSQL.
No hace falta crear PostgreSQL en Seenode. Con `RECEIPT_STORAGE=database`, los comprobantes se guardan cifrados en Neon y no requieren discos de Seenode.

Un inicio con cuatro instancias Basic cuesta **US$12/mes** en Seenode, con cobro proporcional diario. Neon se factura según su propio plan. Cada Basic tiene 512 MB y 0.25 vCPU; es una configuración inicial, cuya capacidad debe medirse con tráfico real. El Worker consulta PostgreSQL continuamente y mantiene el cómputo de Neon activo.
Fuentes: [precios](https://seenode.com/docs/reference/pricing), [imágenes Docker](https://seenode.com/docs/how-to/deploy-from-a-docker-image), [tipos de servicio](https://seenode.com/docs/concepts/services-overview).

## Comandos exactos

API y Worker, **Comando de build**:

```sh
pip install -r requirements.lock && pip install --no-deps -e .
```

API, **Comando de inicio**:

```sh
alembic upgrade head && python scripts/grant_api.py && python scripts/seed.py && python scripts/configure_master.py && uvicorn platform_app.main:app --host 0.0.0.0 --port 8000 --no-access-log
```

Este inicio migra únicamente la base configurada, aplica permisos al rol limitado, inicializa los planes editables y configura webhook, comandos y botón del nuevo Master. Las credenciales y ambas URLs HTTPS deben estar completas antes del arranque. Una sola réplica de API ejecuta las migraciones; para escalar, mover migraciones a una fase de despliegue única.

Worker, **Comando de inicio**:

```sh
python -m platform_app.worker
```

Mini App, **Comando de build**:

```sh
npm ci --include=dev && npm run build:seenode
```

Mini App, **Comando de inicio**:

```sh
npm run start:seenode
```

La Mini App tiene un servidor Node de producción independiente. `npm start` corresponde al desarrollo con Wrangler del otro destino de hosting. Seenode requiere que el puerto del formulario coincida con el del proceso y que escuche en `0.0.0.0`; no inyecta automáticamente una variable `PORT`. [Puertos](https://seenode.com/docs/how-to/configure/port), [monorepo](https://seenode.com/docs/how-to/configure/monorepo).

## Neon: dos roles en la base nueva

Identificar primero el proyecto, la rama y la base destinados a esta plataforma. No ejecutar estas instrucciones en la base del bot existente.

- `SYSTEM_DATABASE_URL`: conexión del propietario de la base nueva, normalmente `neondb_owner`. Se usa para operaciones internas entre tenants.
- `MIGRATION_DATABASE_URL`: la conexión **directa, sin pooler**, del propietario, en la API.
- `DATABASE_URL`: misma base y rama, usuario limitado **`platform_api`**. Su contraseña será distinta.

Neon concede privilegios elevados a los roles creados desde su consola. Crear `platform_api` mediante SQL para que no pertenezca a `neon_superuser`. [Roles y compatibilidad de Neon](https://neon.com/docs/reference/compatibility).

En el editor SQL de la base nueva, como propietario, ejecutar una sola vez tras sustituir la contraseña:

```sql
CREATE ROLE platform_api LOGIN PASSWORD 'SUSTITUIR_POR_UNA_CLAVE_ALEATORIA_LARGA'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
GRANT USAGE ON SCHEMA public TO platform_api;
```

Si el rol ya existe, verificar sus permisos y usar su contraseña; no restablecerla a ciegas. `scripts/grant_api.py` concede los permisos de tablas después de las migraciones. La API comprueba que este rol no pueda saltarse RLS ni modificar las tablas como propietario.

Formato de conexión Python:

```text
postgresql+psycopg://platform_api:CLAVE@HOST_NEON/BASE?sslmode=require&channel_binding=require
postgresql+psycopg://neondb_owner:CLAVE@HOST_NEON/BASE?sslmode=require&channel_binding=require
```

Copiar los valores reales desde Neon. Cambiar el prefijo `postgresql://` a `postgresql+psycopg://`; conservar el resto. Codificar caracteres especiales de la contraseña para una URL. No pegar el comando `psql` ni las comillas exteriores.

## Variables de API y Worker

La plantilla [api.env.example](../deploy/seenode/api.env.example) se pega en el cuadro **Variables de entorno** de Seenode. Sustituir todos los marcadores. El sufijo `*` marca una clave como secreta en Seenode y no forma parte del nombre que recibe Python.

El Worker usa las mismas variables, con las mismas claves de cifrado y webhook, excepto `MIGRATION_DATABASE_URL`, que se necesita solo en la API.

| Variable | Valor/origen |
|---|---|
| `ENVIRONMENT` | `production` |
| `DATABASE_URL` | Neon, rol `platform_api` |
| `SYSTEM_DATABASE_URL` | Neon, propietario de la base nueva |
| `MIGRATION_DATABASE_URL` | Neon directo, propietario; solo API |
| `REDIS_URL` | `redis://:CLAVE@HOST_PRIVADO_REAL:6379/0` |
| `MASTER_BOT_TOKEN` | Token del nuevo Master en BotFather |
| `MASTER_BOT_USERNAME` | Usuario del nuevo Master sin `@`; se compara con el token antes de cambiar su webhook |
| `MASTER_WEBHOOK_SECRET` | Secreto aleatorio nuevo, al menos 32 caracteres |
| `PLATFORM_OWNER_IDS` | ID numérico de tu usuario de Telegram; varios separados por coma |
| `ENCRYPTION_KEYS` | JSON como `{"v1":"BASE64_DE_32_BYTES_ALEATORIOS"}` |
| `ACTIVE_KEY_VERSION` | `v1` |
| `PUBLIC_API_URL` | URL HTTPS pública real de `plataforma-saas-api`, sin `/` final |
| `MINI_APP_URL` | URL HTTPS pública real de `plataforma-saas-web`, sin `/` final |
| `ALLOWED_ORIGINS` | Misma URL de Mini App; orígenes adicionales separados por coma |
| `RECEIPT_STORAGE` | `database` |
| `STORAGE_PATH` | `./storage`; no se usa para comprobantes nuevos en modo database |
| `DEMO_ENABLED` | `false` |
| `TELEGRAM_TEST_ENVIRONMENT` | `false` para el bot real nuevo |
| `SESSION_TTL_SECONDS` | `1800` |
| `INIT_DATA_MAX_AGE_SECONDS` | `300` |
| `TRIAL_DAYS` | `7` |
| `MAX_UPLOAD_BYTES` | `5242880` |
| `WORKER_LEASE_SECONDS` | `180` |
| `JOBS_PER_TENANT_ROUND` | `5` (opción reservada; no modifica aún la planificación) |
| `BOT_RPS` / `TENANT_RPS` / `GLOBAL_RPS` / `USER_RPS` | `20` / `30` / `300` / `1` |

`POSTGRES_PASSWORD` y `PLATFORM_API_PASSWORD` pertenecen al arranque local con Compose y no se necesitan en Seenode con Neon.

Generar cada secreto hexadecimal con `python -c "import secrets; print(secrets.token_hex(32))"`.
Generar el JSON de cifrado con `python -c "import os,base64,json; print(json.dumps({'v1':base64.b64encode(os.urandom(32)).decode()}))"`.
Guardar las claves de cifrado en tu gestor de secretos y conservarlas entre despliegues: se necesitan también para recuperar copias de seguridad. No subir secretos a GitHub ni ponerlos en la Mini App.

## Variables de la Mini App

```dotenv
NODE_ENV=production
HOST=0.0.0.0
PORT=3000
PLATFORM_API_URL=https://URL_REAL_DE_LA_API
```

Solo necesita la URL del backend; la conexión se realiza desde el servidor Node. No recibe credenciales de Telegram, PostgreSQL ni Redis.

## Redis privado

En **Crear nuevo → Servicio privado → Docker image**, imagen oficial `redis`, tag `8.2.9-alpine`, credenciales de pull `Ninguna (pública)`.
Puerto `6379`. Variable secreta `REDIS_PASSWORD*=TU_SECRETO_HEXADECIMAL`.
Comando Docker:

```sh
sh -c 'exec redis-server --bind 0.0.0.0 --port 6379 --requirepass "${REDIS_PASSWORD:?Define REDIS_PASSWORD}" --maxmemory 128mb --maxmemory-policy noeviction --save "" --appendonly no'
```

Usar en `REDIS_URL` el hostname privado que Seenode muestre al crear el servicio. Verificar conectividad desde la API con `/health/ready`; no inventar el hostname. No se requiere disco persistente para esta caché. Los [volúmenes de Seenode](https://seenode.com/docs/how-to/persistent-storage) no se comparten entre servicios; por eso aquí los comprobantes usan Neon.

## Orden y Telegram

1. Confirmar la base nueva de Neon y crear el rol limitado.
2. Crear Redis y la Mini App; obtener su hostname privado y la URL HTTPS de la Mini App. Se puede añadir `PLATFORM_API_URL` a la Mini App cuando Seenode asigne la URL de API.
3. Crear la API y completar ambas URLs y todas las credenciales. Si Seenode asigna la URL solo después de crear, mantenerla detenida mientras se completan esas variables y luego desplegarla.
4. Verificar `/health/live` y `/health/ready` en la API. Esta última debe devolver HTTP 200 y `status: ready`.
5. Crear el Worker cuando las migraciones de API hayan terminado. Completar `PLATFORM_API_URL` en la Mini App y desplegarla si aún faltaba.
6. En la Mini App oficial de **@BotFather**, elegir únicamente el nuevo Master, activar **Bot Management Mode** y configurar su **Main Mini App** con la URL HTTPS de `plataforma-saas-web`. Esto no se activa mediante `setWebhook`. [Guía oficial](https://core.telegram.org/bots/features#creating-your-own-management-bot).
7. Abrir el nuevo Master y pulsar `/start`. Debe mostrar **Crear mi bot**, **Ya tengo cuenta** y **Cómo funciona**. El botón permanente es **Mi negocio**. Los usuarios con espacio existente ven su panel y selección de espacio. El Worker debe estar activo para enviar estas respuestas.
8. Tu ID numérico identifica al administrador en `PLATFORM_OWNER_IDS`. Si ya abriste el bot, `python scripts/list_users.py` muestra los usuarios registrados al ejecutarlo con la configuración de esta base nueva.
9. En Owner, definir los precios de los planes SaaS; se entregan sin precios de cobro preestablecidos. Completar el alta de un creador y su bot en un canal de prueba antes de abrir ventas.

La configuración automática registra `/start` y `/paysupport`, menú Mini App y webhook `/telegram/webhook/master` con encabezado secreto. Los botones de bots hijos se configuran al provisionarlos. Los cobros digitales dentro de Telegram usan Stars. [Documentación de pagos](https://core.telegram.org/bots/payments-stars).

## Verificación de esta adaptación

Pruebas locales: 64 tests Python, migraciones hasta `0003` sin diferencias pendientes, 11 comprobaciones PostgreSQL/RLS en PGlite, compilación Node de producción, TypeScript/lint y peticiones HTTP reales al servidor Node para página principal, cliente y proxy GET/POST. Telegram y el upstream se simularon en estas pruebas; un despliegue real y la prueba de `/start` requieren las credenciales del nuevo bot y de Neon.
