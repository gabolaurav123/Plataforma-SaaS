# Pruebas de Telegram · versión 0.3.1

La suite contiene 160 casos. GitHub ejecuta el backend en Python 3.13 con PostgreSQL 18 real, además del esquema PostgreSQL y del frontend opcional conservado. El resultado de cada revisión está en [Platform checks](https://github.com/gabolaurav123/Plataforma-SaaS/actions/workflows/ci.yml); el informe de entrega identifica la revisión comprobada y desplegada.

La revisión 0.3.1 comprueba además que el menú y su reserva de envío están confirmados en una transacción independiente antes de llamar a Telegram, que una caída entre el commit y el envío no causa un reenvío automático, que una respuesta anulada por un formulario no se entrega y que los trabajos interactivos no despiertan la cola de fondo.

## Evidencia local de esta actualización

| Comprobación | Resultado |
|---|---|
| Ruff | Sin errores |
| Recorridos Telegram nuevos, anteriores y reportes | 48 pruebas aprobadas después de corregir un reloj variable en una prueba de reembolsos |
| Suite completa previa a esa corrección de prueba | 150 aprobadas, un fallo de fecha en esa prueba, cinco casos PostgreSQL omitidos por no tener el servidor real local |
| Cola sobre PostgreSQL PGlite Socket | Tres pruebas aprobadas; concurrencia real y fallo con rollback se ejecutan en PostgreSQL 18 de CI |
| SQLite: upgrade completo y Alembic check | Sin diferencias de esquema |
| PostgreSQL PGlite 17.5: RLS y privilegios | 13 comprobaciones aprobadas |
| PostgreSQL: actualización con datos de 0004 a 0006 | Ocho comprobaciones aprobadas |
| Respaldo real previo a 0006 | 66 tablas y 431 filas restauradas, igualdad de todas las filas y actualización aislada a 0006 |
| Rendimiento del recorrido completo | 36 → 17 consultas SQL; comparación aislada con Telegram simulado |

## Recorridos cubiertos

Mensajes y archivos de clientes al propietario y al equipo con permiso Soporte; respuesta nativa de Telegram al cliente correcto; preservación de formularios abiertos; separación de administradores, negocios y bots; permisos revocados antes de responder o antes de entregar. `/id` en maestro y bots de negocio, registro de una persona nueva sin abrir primero el maestro y sin crear un contacto comprador.

Billeteras con activo, red, dirección pública, memo y QR; asistente en español, inglés y portugués; selección de red por el comprador; instrucciones conservadas por pedido; importes de cripto sin pérdida de precisión; comprobante manual, aprobación idempotente y reembolso registrado sin conexión al exchange.

Las pruebas previas conservan altas y prueba única de tres días, planes, invitaciones por plan, accesos, Stars, transferencias, renovaciones, facturación SaaS, comisiones, devoluciones parciales, reportes, campañas, permisos y aislamiento. El esquema poblado comprueba que los vencimientos, pagos y mensajes anteriores se conservan.

PostgreSQL 18 comprueba recepción y offset atómicos, duplicados, rollback ante fallo al insertar el trabajo, orden por chat, reparto entre negocios, dos consumidores concurrentes y entregas inciertas sin reenvío automático.

## Límites y resultados anteriores

Telegram y los proveedores de pagos se simulan en las pruebas automatizadas; no se hicieron cobros reales. La comparación con retraso SQL artificial no demuestra el tiempo real del Worker. Los logs de producción permiten medir desde recepción hasta confirmación de envío, sin registrar contenido ni IDs de personas. [Mediciones y método](rendimiento.md).

Los archivos [test-summary.json](test-summary.json), [test-output.txt](test-output.txt) y [test-results.xml](test-results.xml) son evidencia histórica de la versión 0.2.0, con 135 pruebas. No representan la versión 0.3.0. La copia cifrada se restauró en PostgreSQL aislado sin modificar Neon. El frontend se verifica en CI pero no se despliega como un servicio adicional.
