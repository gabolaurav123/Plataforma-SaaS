# Operación y despliegue

## Límites del despliegue realizado

La interfaz se prepara en Sites con acceso privado del propietario. **El servidor de negocio, PostgreSQL, Redis y los webhooks Telegram no se han desplegado.** No se han proporcionado ni usado credenciales Telegram reales. Docker no está instalado en la máquina donde se preparó la entrega; Compose y los scripts requieren una prueba en el servidor de destino.

## Instalación en un servidor independiente

1. Usar un servidor o proyecto cloud separado del bot actual. Crear los DNS de `api.tu-dominio` y la URL de las Mini Apps. Preparar TLS y almacenamiento privado cifrado.
2. Copiar esta carpeta, instalar Docker/Compose y ejecutar `python scripts/bootstrap.py` una sola vez. Si no hay Python local, generar el `.env` mediante Python dentro de un contenedor temporal, manteniendo el archivo fuera de repositorios y sistemas de tickets.
3. Completar `.env`: `ENVIRONMENT=production`, token del Master nuevo, propietario, URLs HTTPS y orígenes. Conservar las dos contraseñas distintas generadas para PostgreSQL y el keyring aleatorio.
4. Ejecutar desde esta carpeta:

```bash
docker compose up -d --build
docker compose logs --tail=100 migrate api worker
curl --fail http://127.0.0.1:8000/health/ready
```

Compose crea PostgreSQL, un rol API restringido, Redis privado, un servicio de migración y los procesos API/worker. `migrate` aplica Alembic, siembra planes SaaS sin precios y concede permisos. Los procesos de aplicación corren sin root. PostgreSQL y Redis no publican puertos al host.

5. Instalar/configurar un reverse proxy TLS. [Caddyfile](../infra/Caddyfile) es una plantilla: sustituir el dominio y comprobar las cabeceras confiables del proxy. El puerto 8000 de Compose escucha solo en localhost. No permitir cabeceras de proxy arbitrarias como prueba de identidad o como base de controles de seguridad.
6. En el Worker del frontend configurar `PLATFORM_API_URL=https://api.tu-dominio` mediante las variables de entorno de Sites. No poner allí el token del Master, tokens child ni las claves de cifrado del backend.
7. Configurar la URL de la Main Mini App del Master en BotFather y ejecutar:

```bash
docker compose exec -T api python scripts/configure_master.py
```

8. Abrir el Master y completar la prueba de aceptación. Para aceptar otros creadores/clientes, habrá que preparar expresamente el dominio y audiencia adecuados de la interfaz; la vista privada de revisión no sirve como acceso general a una Mini App.

El script de configuración usa siempre el token configurado en **este** entorno. Verificar visualmente que corresponda al bot nuevo antes de ejecutarlo en un servidor con credenciales reales.

## Workers y cola

`python -m platform_app.worker` procesa una cola central persistente. No iniciar un worker por bot. Compose permite ampliar workers mediante `docker compose up -d --scale worker=3`, después de medir conexiones PostgreSQL, latencia y límites de Telegram.

Los trabajos incluyen UPDATE, PROVISION, SEND, CONFIGURE, GRANT_ACCESS, REVOKE_ACCESS, EVENT, AUTOMATION, CAMPAIGN, HEALTH, HEALTH_SCAN y TICK. El tick corre aproximadamente cada minuto; procesa vencimientos y pruebas SaaS. HEALTH_SCAN pagina bots y distribuye chequeos en ventanas de 15 minutos.

Las reservas usan `FOR UPDATE SKIP LOCKED` en PostgreSQL. El worker alterna tenants; las campañas se expanden en lotes de 100. Los errores temporales tienen reintentos limitados y backoff, y `retry_after` se respeta. El worker se detiene ordenadamente con SIGTERM/SIGINT.

Un SEND abandonado o con respuesta ambigua pasa a `DELIVERY_UNKNOWN`. No volver a ponerlo automáticamente en PENDING: puede haberse enviado antes de una caída. Revisar conversación, campaña y resultado remoto antes de decidir una nueva acción.

[creator-worker.service](../infra/creator-worker.service) ofrece una alternativa systemd para ejecución sin Compose. No correr ambos modos simultáneamente por accidente. Crear el usuario/directorio indicados y ajustar sus rutas antes de instalar la unidad.

## Salud y observabilidad

| Señal | Uso |
|---|---|
| `/health/live` | Proceso API vivo |
| `/health/ready` | DB, migraciones, Redis y frontera de RLS en producción |
| `/api/owner/health` | Totales de tenants/bots/trials, estados de cola e ingresos SaaS de 30 días |
| `/api/owner/resources/jobs` | Trabajos pendientes, fallidos e inciertos |
| `/api/owner/resources/bots` | Estado, última actualización, diagnóstico y chequeos por bot |
| `X-Request-ID` | Correlación de peticiones con logs JSON |

Los logs registran código, estado y latencia sin cuerpo, token ni URL de Telegram. El SDK HTTP no vuelca solicitudes. Conectar un colector y alertas externas es tarea del despliegue: caída de readiness, aumento sostenido de pendientes, fallos de provisioning, retraso del tick y expiración de backups. Aún no hay Prometheus/OpenTelemetry ni un proveedor de alertas integrados.

## Backups

Estrategia inicial: copia diaria, destino privado **cifrado**, al menos una copia fuera del servidor y keyring respaldado por separado. Objetivo propuesto RPO 24 horas; RTO pendiente de medir. Para un RPO menor, configurar backups continuos/WAL mediante el servicio PostgreSQL elegido.

Los scripts generan un `pg_dump` binario, un archivo del volumen de comprobantes cifrados y hashes SHA-256. **El dump de DB no se cifra por el script**: usar un volumen/bucket cifrado, cifrado adicional en la canalización de backup y control de acceso. No publicar el dump ni incluirlo en el ZIP de código.

```bash
BACKUP_DIR=/ruta/privada/cifrada bash scripts/backup.sh
```

En Windows:

```powershell
.\scripts\backup.ps1 -BackupDirectory 'D:\BackupsCifrados\CreatorPlatform'
```

[creator-backup.timer](../infra/creator-backup.timer) y [su servicio](../infra/creator-backup.service) automatizan la ejecución diaria en Linux. Ajustar ruta y destino; instalar las unidades y habilitar el timer. No se instaló una tarea en la máquina del usuario durante esta entrega.

## Restauración

Conservar juntos el dump, los comprobantes y la referencia a las versiones del keyring, con las claves en su vault separado. Verificar hashes antes de restaurar.

```bash
BACKUP_FILE=/ruta/backup.dump RESTORE_DATABASE=creator_restore_ensayo bash scripts/restore-drill.sh
```

El script crea una DB nueva cuyo nombre debe empezar por `creator_restore_`. Si ya existe, falla; no sobreescribe la DB operativa. Retiene la DB de prueba para inspección. El script comprueba versión y conteos; el ensayo completo debe además restaurar los comprobantes en un volumen de prueba, suministrar el keyring, verificar descifrado y probar RLS con el rol restringido.

No ejecutar workers del ensayo contra credenciales y webhooks reales. Tras validar el ensayo, un cambio de producción necesita su propio procedimiento de corte y rollback. No está automatizado en esta versión.

## Actualizaciones y rotación

Ejecutar tests y backup, aplicar `alembic upgrade head` con el rol migrador, conceder los permisos necesarios para tablas nuevas y reiniciar API/workers. Mantener `alembic check` sin diferencias antes de entregar un cambio.

La rotación del token de un Managed Bot se inicia desde su endpoint protegido o por el evento oficial. Primero se persiste cifrado el token actual, después se reconfiguran webhook/menú. La clave de cifrado del vault y el token de Telegram son secretos distintos y tienen procedimientos de rotación distintos.

La aplicación no modifica código, contenedores, archivos o credenciales del bot anterior.
