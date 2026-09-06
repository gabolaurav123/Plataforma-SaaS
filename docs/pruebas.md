# Pruebas de la versión solo Telegram · 6 de septiembre de 2026

**85 pruebas aprobadas** en Python 3.14.3, 110,93 segundos. Incluyen 21 pruebas nuevas del modo Telegram. Cobertura de sentencias del conjunto: **77.92%**. Telegram está simulado; no se hicieron cobros reales.

| Comprobación | Resultado |
|---|---|
| Suite completa de backend | 85 aprobadas |
| Ruff | Sin errores |
| Instalación del paquete editable | Correcta |
| Alembic SQLite hasta 0004 y `alembic check` | Sin diferencias de esquema |
| DDL PostgreSQL y aislamiento PGlite 17.5 | 12 comprobaciones aprobadas |
| Neon real, proyecto Telegram Saas, neondb | Migración 0004 y límite de permisos verificados |
| Worker único con proveedor simulado | Recibe, persiste y responde un mensaje; termina al recibir parada |
| Recepción sin actividad | Los polls vacíos no consultan PostgreSQL |
| Web y Mini Apps | Código conservado para una fase posterior; no forma parte del servicio actual |

Se comprobaron creación nativa, botones privados vinculados a usuario y bot, acceso cruzado entre negocios, revocación de roles, recuperación de asistentes tras reinicio, creación de planes, checkout Stars, publicación, equipo, campañas con confirmación, recordatorios, soporte y administración. También la persistencia de offsets y trabajos en una misma transacción, entrega repetida sin duplicación, ausencia de confirmación ante fallos de almacenamiento, respuesta rápida de pre-checkout y parada ante conflicto de polling.

Las 12 comprobaciones PostgreSQL cubren RLS, claves compuestas, restauración de snapshot y denegación de acceso a diálogos, botones, sesiones y cursores privados desde el rol de API. Las pruebas previas de pagos, renovación, comprobantes, accesos y reembolsos siguen pasando.

Se observaron avisos de deprecación de Starlette/AnyIO y un aviso del cierre de una conexión SQLite en pruebas. No se midió capacidad sostenida ni latencia bajo tráfico real. El límite inicial de 20 bots es configurable y no constituye una garantía de rendimiento de una instancia Basic.

Antes de recibir clientes, probar desde Telegram con el nuevo Master: creación de un bot hijo, configuración, publicación, pago de prueba autorizado por el propietario, enlace personal, vencimiento, cancelación de renovación y reembolso. Mantener una sola réplica y comprobar los logs tras el despliegue. Ver [guía Seenode](seenode.md) y [menús](telegram.md).

Los resultados de esta ejecución están en [test-summary.json](test-summary.json). El archivo histórico `test-output.txt` corresponde a una ejecución anterior del modo web.
