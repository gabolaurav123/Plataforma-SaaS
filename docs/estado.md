# Estado real de la entrega

> Actualización: la fase activa funciona con un único Worker, sin web, Mini App ni Redis. Ver [Seenode](seenode.md) y [menús de Telegram](telegram.md). El detalle del modo web que sigue se conserva como referencia para una fase posterior.


**Implementado** significa código ejecutable con pruebas locales donde se indica. No significa validación operativa con credenciales reales. Los métodos Telegram se probaron con transporte simulado.

| Fase solicitada | Implementación disponible | Pendiente o alcance parcial |
|---|---|---|
| 1. Foundation, auth, tenants | API central, sesiones HMAC, membresías, roles, migraciones, claves compuestas, RLS | Despliegue PostgreSQL/Redis real y revisión de acceso por operador |
| 2. Master y Master Mini App | Home, wizard guardado, selector de espacios, navegación, administración de plataforma y precios SaaS | Prueba de interfaz en clientes Telegram reales; pulido de estados y formularios de todas las variantes |
| 3. Managed Bots | Solicitud oficial, eventos de creación/actualización, tokens cifrados, provisioning, rotación y acceso administrado por API | Validación real Bot Management Mode y transferencia de propietario con procedimiento humano |
| 4. Child bot | Start, planes, ayuda, soporte, opt-out, menú Mini App, textos configurables, perfil y foto | No todos los mensajes del motor usan todavía el catálogo editable; traducciones completas pendientes |
| 5. Canales | Conectar/verificar, prueba, invitación temporal ligada al usuario, ingreso, revocación y separación del modo nativo | Reconciliación exhaustiva de todos los miembros, prueba real de eventos nativos y prevención transaccional adicional de canal compartido entre bots |
| 6. Comercio | Planes, Stars, recurrencia, cargos idempotentes, revisión de comprobantes externos, suscripciones, cancelación y reembolso | Procesador externo/tarjetas deshabilitado; conciliación periódica Stars integral, QR bancario y OCR no implementados |
| 7. CRM e inbox | Contactos y etapas, mensajes entrantes/salientes, notas, etiquetas por API, roles, exportación paginada | UX avanzada de asignación, búsqueda global, adjuntos multimedia y edición masiva; el equipo se añade por ID de un usuario ya registrado |
| 8. Crecimiento | Segmentos por etapa/origen, campañas por lotes, programación/pausa, opt-out, reglas con demora, deduplicación | Constructor visual de reglas complejas, múltiples acciones por regla, condiciones temporales avanzadas y reportes de entregabilidad |
| 9. Analytics, cupones, referidos | Totales por moneda/plan/proveedor, conversión, renovaciones, vencidos, ARPU/LTV simples, descuentos y atribución | Cohortes, churn y MRR rigurosos, series temporales y retención, cálculo/pago de recompensas y reglas avanzadas de referidos |
| 10. SaaS | Trial, checkout del Master, planes y precios configurables, suspensión, bots/equipo/contactos/campañas/automatizaciones con límites y feature flags | Reembolsos y cancelación de la facturación SaaS completos, enforcement de cada límite de retención/exportación, addon IA/OCR y marca personalizada avanzada |
| 11. Seguridad y QA | Pruebas de auth/aislamiento/pagos/canales/colas, RLS PostgreSQL embebido, build, lint, SQL, scripts de backups, logs y salud | Prueba concurrente distribuida real, pruebas de navegador y móviles, Docker en esta máquina, restauración `pg_dump` real, alertas externas y recuperación de desastre |

## Detalles que requieren atención antes de producción

- Los endpoints de lectura de algunas listas ofrecen un catálogo genérico paginado. Varias acciones avanzadas están en la API, aunque no tengan todavía una pantalla especializada.
- El formulario de edición de un bot y los planes cubren el flujo inicial. El wizard con varios bots debe probarse especialmente al reanudar una creación pendiente para evitar una selección confusa.
- Los textos tienen variables controladas y vista previa. Algunos mensajes de acceso, prueba y operación siguen siendo textos de servicio fijos.
- El catálogo público dispone de caché versionada; no se almacenan sesiones, tokens ni datos de clientes en ella. Configuraciones/roles sensibles se consultan sin esa caché.
- El monitor recorre bots por páginas y distribuye chequeos cada 15 minutos; no sustituye una alerta externa de caída del propio worker.
- La cola diferencia un envío fallido de una entrega incierta. Telegram no ofrece una clave de idempotencia para `sendMessage`: un envío incierto queda para revisión, en lugar de afirmar entrega exactamente una vez.
- Las comprobaciones de aislamiento reducen errores de acceso. No se promete aislamiento absoluto ante una cuenta de sistema comprometida ni una ausencia garantizada de vulnerabilidades.
- Los backups de base de datos necesitan almacenamiento cifrado del operador. Los comprobantes ya se almacenan cifrados. Un backup de datos sin keyring recuperable no basta para restaurar el servicio.
- La política de retención y el proceso completo de borrado/anonimización de datos no están implementados. Deben definirse antes de incorporar datos reales.
- Las plantillas legales y la aprobación de actividades no se inventaron. El creador debe definir políticas reales; el operador debe revisar su servicio y los métodos externos antes de habilitarlos.

## Contratos preparados, sin integración activa

`ExternalHostedProvider`, `KeyWrapper` para KMS, `LegacyImporter`, tablas de eventos externos y flags de IA/OCR son puntos de extensión. No se presentan como servicios conectados. IA/OCR no pueden activarse desde el endpoint de flags en esta versión.

El bot actual queda fuera de este proyecto. Cualquier futura importación necesitará inventario, mapeo, sandbox de prueba y autorización específica.
