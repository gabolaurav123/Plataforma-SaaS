# Pruebas de la actualización comercial · 6 de septiembre de 2026

**135 pruebas aprobadas**, 228,99 segundos, Python 3.14.3. Cobertura de sentencias: **71.08%**. La API de Telegram y los procesadores de pagos se simulan; no se hicieron cobros reales.

| Comprobación | Resultado |
|---|---|
| Suite completa de backend | 135 aprobadas; 0 fallos |
| Ruff | Sin errores |
| Migración SQLite con datos de 0004 a 0005 y Alembic check | Datos conservados; sin diferencias de esquema; 0 errores de claves foráneas |
| PostgreSQL PGlite 17.5, RLS y límites de privilegios | 13 comprobaciones aprobadas |
| PostgreSQL, migración con registros anteriores | 7 comprobaciones aprobadas |
| Copia cifrada real de la nueva base Neon | 51 tablas y 113 registros restaurados; igualdad de todas las filas; actualización aislada a 0005 |
| Frontend opcional conservado | Check, build y build:seenode aprobados; auditoría npm sin vulnerabilidades |
| Navegación de negocio | Destinos de los 20 botones principales probados en español, inglés y portugués |
| Rendimiento | Comparación local y reutilización HTTP documentadas; sin prueba de carga real en Seenode |

## Recorridos cubiertos

Alta, prueba explícita de tres días y uso único por propietario; validación de token sin conectar antes de confirmar; cifrado y reemplazo; separación entre negocios y entre bots del mismo espacio; roles y revocación durante asistentes pendientes.

Planes y precios, pagos Stars, transferencias con comprobantes, aprobación repetida, reembolsos parciales, renovación, expiración, accesos personales, invitaciones gratuitas sin pagos artificiales y límites de usos. Stripe y PayPal verifican firmas y estado mediante HTTP simulado, con eventos repetidos e importes incorrectos.

Facturación a 30 días, USD 30 más el 4% de USD 1.000 igual a USD 70; ventas, devoluciones y recursos reales en el resumen; tasas históricas; conversión pendiente sin saldo inventado; cambio de plan al siguiente ciclo; liquidaciones parciales, ajustes y suspensión administrativa que no se levanta automáticamente por pagar.

Difusiones con foto y botones: editor, vista previa, confirmación, exclusión de opt-out y otro bot, cola, envío confirmado y rechazo de confirmación repetida. Plantillas editadas/restauradas por idioma; bienvenida predeterminada compatible con publicación. Instrucciones de banco y cripto persistentes y protegidas por permisos. Aviso VIP sin repetición, cancelación notificada y resúmenes configurables.

Reportes con capturas y devoluciones en sus periodos, monedas separadas, CSV aislado y caduco, MRR limitado a renovaciones automáticas compatibles, churn histórico tras cancelación y reactivación e históricos incompletos mostrados como N/D. Fechas locales y cambio de horario estacional.

Cola interactiva adelantada a 300 trabajos de fondo, persistencia transaccional de offsets, tareas idempotentes, manejo de 429 y entregas desconocidas, conflictos de polling, errores seguros y recepción vacía sin consultas SQL.

## Alcance de la evidencia

La cobertura no es del 100% y estas pruebas no demuestran que todo escenario de red, proveedor o carga haya sido validado. Se observaron dos avisos de deprecación de Starlette/AnyIO; no son fallos de la suite. GitHub ejecuta además los checks en Python 3.13 al publicar cada revisión.

La restauración usó datos reales de la base nueva en un PostgreSQL aislado; no cambió Neon. El despliegue de esta revisión requiere verificar la migración 0005, los permisos reales y el Worker activo. La revisión activa y el estado de GitHub deben consultarse en el informe de entrega del despliegue.

Los pagos live y el flujo de venta con un bot/canal real requieren credenciales y una operación del propietario. Stripe/PayPal permanecen desactivados en el Worker sin entrada HTTPS. Las instrucciones de transferencia/cripto de la plataforma aún deben completarse desde Telegram.

Resultados: [test-summary.json](test-summary.json), [salida de pytest](test-output.txt), [JUnit](test-results.xml), [mediciones](rendimiento.md).
