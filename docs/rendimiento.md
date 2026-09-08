# Rendimiento: mediciones y límites

## Versión 0.3.0 · recorrido completo

En el historial real del maestro anterior se observaron 48 respuestas: mediana de 7 segundos desde registro del mensaje hasta completar el primer envío, p95 de 9 segundos, con resolución de un segundo.

La nueva versión reduce `/start` y `/admin` de 36 a 17 consultas SQL por recorrido. Con PostgreSQL aislado y 100 ms añadidos por consulta, seis muestras por versión dieron medianas de 3.678 y 1.767 ms. Telegram se simuló; no incluye un retraso artificial por commit/ping y **no representa el tiempo real en Seenode**. [Datos](performance-0006.json), [programa de comparación](../qa/benchmark_pipeline.py).

La recepción guarda offset, mensaje cifrado y trabajo mediante una única operación transaccional. La cola usa una selección atómica que comprueba primero el orden del chat, y evita adquirir trabajos bloqueados. Se mantienen las entregas inciertas sin reenvío automático. Los logs `telegram_response` permiten medir recepción → confirmación de envío en producción.

## Comparación histórica 0.2.0 · renderizado local

Esta medición anterior mide solo el menú y no permite estimar la respuesta completa que percibe el usuario.

Comparación local del código `2c37ad1` y la actualización comercial `0005`, Windows, Python 3.14.3 y SQLite. Dos negocios, dos bots y 10.000 contactos sintéticos adicionales. Se descarta una ejecución inicial y se miden 30 ejecuciones por menú. Las llamadas HTTP usan `httpx.MockTransport`.

| Recorrido | Mediana anterior | Mediana actual | p95 anterior / actual | Consultas SQL anterior / actual |
|---|---:|---:|---:|---:|
| Inicio del maestro | 11,49 ms | 11,90 ms | 43,34 / 15,83 ms | 6 / 7 |
| Administración de plataforma | 15,21 ms | 12,17 ms | 17,33 / 18,05 ms | 11 / 8 |

En 100 llamadas HTTP simuladas se pasó de crear **100 instancias de cliente HTTP a reutilizar una**. Sus tiempos totales fueron 24,80 y 21,05 ms. Esto comprueba la reutilización del cliente; no mide conexiones TCP reales, TLS, la latencia de Telegram ni Seenode.

Los tiempos pequeños y el tamaño de la muestra tienen variabilidad. El inicio mantiene una mediana similar; el menú administrativo realiza menos consultas porque prepara los agregados en segundo plano. Estos resultados no demuestran que todos los recorridos sean más rápidos ni que una instancia Basic soporte miles de bots.

## Cambios aplicados

- Clientes HTTP persistentes por token y versión; cierre y renovación al cambiar credenciales. Pool SQL compartido, con conexiones de API y sistema separadas.
- Colas interactivas y de fondo independientes: dos consumidores por tipo. Reportes, resúmenes, comprobantes, pagos externos, publicaciones y campañas se ejecutan fuera de la navegación.
- Trabajos persistentes en PostgreSQL, unicidad y orden de respuesta por conversación. Selección de trabajos con bloqueo y equidad entre negocios; recuperación de leases tras reinicios.
- Listados paginados e índices para pagos, reembolsos, suscripciones, historial, contactos y cola. Agregaciones por SQL, sin cargar todas las ventas para un resumen.
- Audiencias materializadas por SQL y procesamiento de campañas en lotes de 100. Los reportes tienen un máximo de 50.000 filas y 8 MB.
- Esperas vacías de Telegram sin consultas a Neon; avisos internos despiertan a los consumidores. El mantenimiento predeterminado es de 900 segundos.

## Capacidad y siguiente medición

El despliegue inicial usa una sola réplica y `POLLING_MAX_BOTS=20`. Este límite limita el riesgo operativo; no garantiza 20 bots con tráfico intenso. No se ha efectuado una prueba sostenida en Seenode ni con la API real de Telegram para esta actualización.

Antes de ampliar clientes, medir p50/p95 desde recepción hasta envío, CPU, memoria, espera de cola, ocupación del pool, errores 429 y latencia de pre-checkout con tráfico representativo. Si se requiere escalar, pasar la recepción a webhooks y distribuir consumidores por bot/negocio, manteniendo orden e idempotencia. No ejecutar dos lectores de polling con el mismo token.

Las salidas originales de la comparación están en [performance-summary.json](performance-summary.json).
