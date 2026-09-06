# Informe de pruebas · 6 de septiembre de 2026

La versión final del backend obtuvo **61 pruebas aprobadas**, con **80,04 % de cobertura de sentencias** (2.330 de 2.911). Se ejecutó en Windows, Python 3.14.3. El frontend se verificó con Node 24.11.1. No se usaron tokens reales ni se enviaron mensajes o cobros reales.

| Verificación ejecutada | Resultado | Qué demuestra |
|---|---|---|
| pytest, suite completa | 61 aprobadas, 54,72 s | Seguridad, dominio, API y transporte simulado |
| Cobertura de sentencias | 80,04 % | Alcance del código ejecutado; no cobertura total de ramas ni de escenarios |
| Ruff backend/tests | Sin errores | Análisis estático de código propio |
| Migraciones SQLite | Aplicadas hasta 0002 | Inicialización reproducible local |
| alembic check | Sin diferencias | Los modelos corresponden con las migraciones |
| DDL PostgreSQL + RLS embebido | 11 comprobaciones aprobadas | Políticas reales PostgreSQL, restricciones y restauración de snapshot |
| Enrutamiento de bots | Escenarios 100, 1.000 y 10.000 aprobados | Resolución de identidad sobre registros; no capacidad de producción |
| TypeScript + lint frontend | Aprobados | Rutas, pantallas y librerías propias |
| Build frontend | Aprobado | Bundle Worker y rutas `/`, `/b/:publicId`, proxy API |
| npm audit frontend | 0 vulnerabilidades informadas | Dependencias evaluadas por el registro en esa ejecución |
| Smoke HTTP local | Panel, cliente de ejemplo y readiness con HTTP 200 | Los procesos respondieron sin error en esas rutas |

## Escenarios cubiertos

- Firma alterada, antigüedad, futuro y duplicados en initData; sesión de Master/child incorrecta.
- Aislamiento entre dos creadores por API/ORM, escrituras cruzadas y secreto de webhook de otro bot.
- Cifrado con contextos diferentes, redacción de secretos e imports sin credenciales.
- Creación oficial simulada, provisioning, capacidad Management Mode y reintentos de rotación.
- Pago duplicado, importe/usuario/bot inválidos, recurrencia atrasada, expiración y reembolsos.
- Comprobante válido, formato inválido, hash/similitud, doble aprobación y revisión de duplicados.
- Permisos de canal, invitación vinculada al usuario, modos de suscripción separados y revocación.
- Inbox idempotente, campañas por lotes, tareas, límites, roles, baja de miembros y suspensión SaaS.
- Recorrido HTTP creador → configuración → publicación → cliente → checkout → webhook de pago → membresía.
- Caché del catálogo invalidada al cambiar precios y scanner de salud que excluye bots con cambio de propietario.

## PostgreSQL embebido

`qa/rls.mjs` ejecuta el DDL generado contra PostgreSQL 17.5 embebido en PGlite, con un rol sin privilegios. Comprueba lectura sin scope, lectura del tenant propio, selección/actualización/borrado cruzados, INSERT bloqueado, FK compuesta, limpieza del scope, integridad del otro tenant y RLS forzado en todas las tablas operativas. Una restauración de snapshot binario conserva datos y políticas.

No es una prueba de PostgreSQL 18.6 en contenedores, de conexiones concurrentes ni del procedimiento `pg_dump/pg_restore` del servidor. Estos ensayos siguen pendientes.

## Avisos y límites

Quedaron dos avisos de deprecación en el cliente de pruebas Starlette/AnyIO. El build Vite avisa de una futura exigencia de atributos de importación JSON y de una ruta cuyo tipo no clasifica estáticamente; terminó correctamente.

No se ejecutaron pruebas de navegador, capturas visuales, dispositivos móviles, clientes Telegram reales, Docker, API real de Stars, alertas externas ni carga distribuida. No se midieron p95/p99, CPU/RAM de producción o mensajes por segundo sostenidos. La auditoría npm no equivale a una auditoría independiente de seguridad ni a un escaneo de los paquetes Python.

Los resultados resumidos están en [test-summary.json](test-summary.json) y la salida sanitizada de pytest en [test-output.txt](test-output.txt).

## Aceptación real antes de operar

Usar exclusivamente bots, canales y datos nuevos para estos pasos:

1. Crear Master, habilitar Management Mode y confirmar capacidad desde el panel del propietario.
2. Entrar con dos cuentas Telegram distintas; crear dos espacios y comprobar que cada una solo ve sus datos.
3. Crear Managed Bot con botón preparado y enlace oficial; repetir entrega de update sin duplicar bot/trabajo.
4. Pulsar Start en el child, editar foto/textos/menú, conectar canal, retirar/reponer permisos y comprobar diagnóstico.
5. Publicar con checklist completo; comprobar el ingreso desde la Customer Mini App.
6. Pagar con Stars, verificar que pre-checkout no active acceso, y comprobar pago, renovación, cancelación y reembolso.
7. Intentar usar una invitación con otra cuenta; comprobar rechazo. Verificar vencimiento conservando otro derecho vigente.
8. Registrar un pedido externo bancario autorizado, subir/repetir comprobante y revisar manualmente.
9. Enviar una campaña pequeña a cuentas de prueba con consentimiento, pausar/reanudar y probar opt-out/429.
10. Cambiar token, reiniciar worker durante trabajo y revisar recuperación y entregas inciertas.
11. Ejecutar carga contra un entorno PostgreSQL/Redis aislado y medir latencia, CPU, memoria, retrasos y fallos con 100/1.000/10.000 bots de prueba.
12. Restaurar backup en DB y almacenamiento nuevos, con su keyring; validar datos, descifrado, RLS y tiempo de recuperación sin conectar el ensayo a producción.
