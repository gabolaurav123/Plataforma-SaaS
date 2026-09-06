# Controles y verificación de seguridad

Checklist solicitado para la entrega. Marca de implementación no equivale a auditoría externa o prueba en infraestructura real.

## Implementado

- [x] Proyecto independiente, sin credenciales ni imports del bot anterior.
- [x] `initData` validado en servidor con el token del bot correspondiente; edad, firma, campos duplicados y fechas futuras rechazados.
- [x] Sesiones opacas, hash en DB, duración limitada y bearer solo en memoria del frontend.
- [x] Membresía y permisos comprobados de nuevo en cada petición; no se confía en tenant ni rol enviado por el navegador.
- [x] Filtros ORM obligatorios, validación de escrituras, claves foráneas compuestas y RLS forzado PostgreSQL.
- [x] Credenciales API y sistema separadas; control de privilegios/RLS al arrancar producción.
- [x] Tokens y secretos de proveedores/comprobantes cifrados con AES-GCM y contexto autenticado.
- [x] Token fuera del webhook URL, secret header por bot y actualización idempotente.
- [x] Cambios de propietario despublican/quarantinan sin transferir datos del tenant anterior.
- [x] Pagos ligados a bot, usuario, plan, moneda e importe; cargos únicos y control de eventos repetidos/atrasados.
- [x] Checkout digital del cliente restringido a Stars; procesadores externos deshabilitados.
- [x] Archivos con límite de bytes y píxeles, formato real, normalización, eliminación de metadatos y almacenamiento cifrado.
- [x] Exportaciones limitadas por página y protección frente a fórmulas de hojas de cálculo.
- [x] Secretos/payloads excluidos de serialización y logs; errores de validación sin eco de inputs sensibles.
- [x] Límites salientes globales/tenant/bot/usuario y manejo de 429; opt-out para campañas.
- [x] Auditoría de acciones importantes; el rol API no puede actualizar/borrar esa tabla.
- [x] Pruebas de accesos cruzados, firmas, ciphertext copiado, replay de pagos y webhooks.

## Requerido antes de producción

- [ ] Credenciales nuevas y vault del operador, TLS, audiencia de Mini Apps adecuada y acceso administrativo restringido.
- [ ] Validar RLS y permisos usando **los roles reales del despliegue**, además de las pruebas embebidas.
- [ ] Revisar el alcance de la conexión de sistema privilegiada, sus accesos de red y registros de administración.
- [ ] Ensayar PostgreSQL/Redis con varios workers y carga representativa; medir latencia de pre-checkout.
- [ ] Ensayar backup/restore de DB, comprobantes y keyring; cifrar el destino del dump.
- [ ] Definir borrado/anonimización, retención y atención a solicitudes de datos; no están automatizados.
- [ ] Configurar alertas del servicio, del worker y de backups; revisar trabajos `DELIVERY_UNKNOWN`.
- [ ] Probar Bot Management Mode, Stars, reembolsos y permisos de canales con bots/canales nuevos.
- [ ] Revisar políticas reales, actividad comercial y alcance de métodos externos antes de habilitarlos.
- [ ] Revisar seguridad de dependencias y aplicar actualizaciones antes del despliegue.

RLS protege el acceso ordinario de la API, no una cuenta de sistema con privilegios. Los hashes de comprobantes detectan coincidencias y similitud; no prueban autenticidad bancaria ni fraude. No hay reconocimiento OCR ni aprobación bancaria automática.
