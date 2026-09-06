# Seenode: un Worker y tu Neon existente

Esta configuración reemplaza la propuesta anterior de cuatro servicios. Repositorio: [gabolaurav123/Plataforma-SaaS](https://github.com/gabolaurav123/Plataforma-SaaS), rama `main`. Usar la versión con `platform_app.polling` y migración `0004`.

## Formulario de Seenode

Crear nuevo → **Worker** → Git repository → **Plataforma-SaaS** → Conectar.

| Campo | Valor |
|---|---|
| Nombre sugerido | `plataforma-saas-telegram` |
| Tipo | Worker |
| Repositorio | `gabolaurav123/Plataforma-SaaS` |
| Rama | `main` |
| Imagen | Python 3.13 |
| Directorio raíz | `.` |
| Plan | Basic, 512 MB, 0.25 vCPU |
| Réplicas | **1** |
| Puerto / dominio | **No aplica** |

Build:

```sh
pip install -r requirements.lock && pip install --no-deps -e .
```

Inicio:

```sh
alembic upgrade head && python scripts/grant_api.py && python scripts/seed.py && python -m platform_app.polling
```

El inicio migra únicamente la base indicada, aplica los permisos del rol limitado, conserva o crea los planes SaaS y configura el nuevo Master con comandos. Comprueba el @usuario del token antes de cambiar su configuración. Usa long polling (`getUpdates`): no registra webhooks ni expone un servidor HTTP. Los bots hijos se atienden dentro del mismo proceso.

No crear API Web, frontend, Redis ni otra base en Seenode. No editar el servicio `telegram-saas-bot` existente. El coste nuevo parte de **US$3/mes en Seenode**, además del consumo de tu plan Neon y de los servicios que ya tenías. [Precios Seenode](https://seenode.com/docs/reference/pricing), [Workers](https://seenode.com/docs/how-to/deploy-a-worker).

## Variables de entorno

Pegar [worker.env.example](../deploy/seenode/worker.env.example) en el formulario. Seenode acepta `NOMBRE*=valor` para marcar una variable secreta. En un archivo `.env` local se usa `NOMBRE=valor`, sin asterisco.

| Variable | Valor o finalidad |
|---|---|
| `ENVIRONMENT` | `production` |
| `DEPLOYMENT_MODE` | `telegram` |
| `DATABASE_URL` | Conexión Neon agrupada del rol limitado `platform_api` |
| `SYSTEM_DATABASE_URL` | Conexión Neon agrupada de `neondb_owner`, solo en este Worker |
| `MIGRATION_DATABASE_URL` | Conexión Neon directa de `neondb_owner` para Alembic |
| `MASTER_BOT_TOKEN` | Token del **nuevo** bot maestro, secreto |
| `MASTER_BOT_USERNAME` | Usuario del nuevo Master, sin `@`; debe corresponder al token |
| `PLATFORM_OWNER_IDS` | Tu ID numérico de Telegram; varios IDs separados por comas |
| `ENCRYPTION_KEYS` | JSON con clave aleatoria AES de 32 bytes codificada en Base64, secreto |
| `ACTIVE_KEY_VERSION` | `v1`; debe existir en el JSON anterior |
| `RECEIPT_STORAGE` | `database`, imágenes cifradas en Neon |
| `STORAGE_PATH` | `./storage`, usado para el bloqueo local del proceso |
| `MAX_UPLOAD_BYTES` | `5242880` (5 MB) |
| `POLLING_TIMEOUT` | `25`, duración de cada consulta larga a Telegram |
| `MAINTENANCE_INTERVAL` | `900`, mantenimiento cada 15 minutos |
| `POLLING_MAX_BOTS` | `20`, límite inicial de bots hijos para esta instancia pequeña |
| `TRIAL_DAYS` | `7`, prueba inicial del creador |
| `WORKER_LEASE_SECONDS` | `180`, recuperación de trabajos interrumpidos |
| `BOT_RPS` / `TENANT_RPS` | `20` / `30`, límites de envío por bot y negocio |
| `GLOBAL_RPS` / `USER_RPS` | `300` / `1`, límites global y por destinatario |
| `DEMO_ENABLED` | `false` |
| `TELEGRAM_TEST_ENVIRONMENT` | `false` |

No hacen falta `REDIS_URL`, `PORT`, `PUBLIC_API_URL`, `MINI_APP_URL`, `ALLOWED_ORIGINS` ni `MASTER_WEBHOOK_SECRET` en este modo. Las librerías del modo web pueden seguir instaladas; no crean servicios ni cargos por sí solas.

## Neon y secretos

Las tres conexiones apuntan a **la misma base nueva**, no son tres bases ni tres servicios. La conexión agrupada contiene `-pooler` en el host; la directa no. Usar `postgresql+psycopg://.../neondb?sslmode=require&channel_binding=require` y codificar caracteres especiales de las contraseñas en la URL.

En el proyecto Neon nuevo ya preparado se usan `neondb_owner` y `platform_api`. Este último no debe ser propietario de tablas ni tener `BYPASSRLS`. El arranque verifica las políticas de aislamiento y que las tablas privadas de botones, diálogos y cursores no sean accesibles con ese rol. No reutilizar credenciales del bot anterior.

Conserva una copia segura de `ENCRYPTION_KEYS`: perder esta clave impide recuperar los tokens cifrados. No la regeneres en cada despliegue. La base y la clave deben incluirse en tu estrategia de respaldo.

## BotFather y primer uso

1. Abre el **nuevo** Master en @BotFather y activa **Bot Management Mode** en sus ajustes. Telegram puede mostrar esta configuración en la interfaz propia de BotFather.
2. Completa token, usuario e ID administrador en Seenode. El ID es numérico, no tu @usuario. No hace falta enviarlo mediante una página web de la plataforma.
3. Inicia el Worker. El arranque configura `/start`, `/admin`, `/id`, `/cancel`, `/support` y `/paysupport`, y deja el menú de comandos de Telegram.
4. Abre el Master desde tu cuenta y pulsa Iniciar. Tu cuenta verá **Administrar plataforma**; las demás no.
5. Crea un negocio y su bot. Usa el botón oficial «Crear mi bot»; no pegues tokens de bots hijos.
6. En el Master, abre el bot hijo y configura soporte, términos, privacidad y reembolso; añade el canal y crea un plan en Stars.
7. Abre también el bot hijo y pulsa Iniciar para permitirle enviarte la prueba. Vuelve al Master y pulsa **Comprobar y publicar**.
8. Desde otra cuenta, prueba catálogo, políticas, una compra de importe elegido por ti, acceso al canal y soporte. No dar por verificado un pago real hasta terminar esta prueba.

El administrador configura precios SaaS en `/admin → Precios SaaS`. Los precios iniciales están vacíos: el sistema no inventa tarifas. Puede conceder días gratis desde `/admin → Negocios → negocio → Conceder días / reactivar`, sin registrar cobros ficticios.

## Mantenimiento y consumo

El proceso espera mensajes en Telegram sin consultar Neon por cada espera vacía. La cola despierta al recibir un update o al llegar el próximo trabajo pendiente. El mantenimiento agrupa vencimientos y limpieza cada 15 minutos; retirar miembros vencidos puede demorarse ese tiempo. El acceso nuevo siempre verifica el vencimiento exacto.

Neon puede suspender el cómputo tras cinco minutos de inactividad; el plan gratuito tiene cuotas propias, por lo que no se promete coste cero bajo actividad continua. Reducir `MAINTENANCE_INTERVAL` acelera las tareas periódicas y puede aumentar consumo. [Scale to zero](https://neon.com/docs/introduction/scale-to-zero), [plan Neon](https://neon.com/pricing).

Mantener **una sola réplica**, sin otro Worker ni sesión local usando el mismo token. Para actualizar, detener la instancia anterior antes de iniciar la siguiente. El bloqueo local impide dos procesos en un contenedor; un conflicto de Telegram detiene el proceso y queda en logs. Los cursores y trabajos persistentes permiten reanudar al reiniciar. Telegram conserva updates pendientes un máximo de 24 horas; evitar interrupciones prolongadas. [getUpdates](https://core.telegram.org/bots/api#getupdates).

La seguridad depende del token, los IDs autorizados, los roles y las claves. Usar Telegram evita publicar endpoints propios en esta fase; no convierte las conversaciones con bots en chats cifrados de extremo a extremo.
