# Operación

Usar [Seenode](seenode.md) para el proceso, variables y arranque, [Telegram](telegram.md) para los menús y [recuperación](recuperacion.md) para las copias.

Revisar trabajos `FAILED`, `DELIVERY_UNKNOWN`, bots con `CONNECTION_ERROR`, facturas `NEEDS_RATE` y confirmaciones `REVIEW_REQUIRED`. La consola muestra códigos seguros, sin tokens o cuerpos privados. Un bot revocado o con otro lector activo necesita corregir su token/proceso y volver a conectarse.

El mantenimiento revisa vencimientos y facturación por lotes. Los resúmenes de negocio solo se emiten si están habilitados; toman el último día, semana o mes completo de su zona horaria. Las tareas se deduplican por periodo. No se envía una avalancha de resúmenes de todos los periodos omitidos tras una parada prolongada.

Reportes: hasta 50.000 filas u 8 MB, acceso cifrado por siete días. Mensajes procesados: limpieza de cargas sensibles al completar; actualizaciones finalizadas se depuran tras siete días. Cargas fallidas de updates/proveedores: máximo 14 días. Los libros financieros y auditoría se conservan; no se borran por impago.

Las difusiones capturan la audiencia al confirmar el comienzo, usan lotes de 100 y respetan límites por bot, tenant y usuario. Un bloqueo del destinatario detiene futuros envíos de campaña a esa persona. No hay métrica de lecturas. Las campañas antiguas que estaban en curso se dejan pausadas en la migración para revisión antes de reanudarlas.
