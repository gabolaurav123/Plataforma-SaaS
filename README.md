# Creator Engine · Todo desde Telegram

La versión actual funciona con **un único Worker de Seenode + PostgreSQL en Neon**. Creadores, clientes y administrador operan mediante botones y mensajes de Telegram. No necesita web, Mini App, Redis, dominio ni puerto público.

**[Configuración exacta de Seenode](docs/seenode.md)** · **[Uso de los menús](docs/telegram.md)**

Es un proyecto independiente. El servicio y repositorio `telegram-saas-bot` quedan fuera de este despliegue.

## Qué puedes hacer desde Telegram

- Crear negocios y bots mediante el mecanismo oficial de Managed Bots, sin pedir tokens a los creadores.
- Configurar nombre, foto, descripciones, bienvenida, soporte, textos y políticas; conectar canales y publicar después de las comprobaciones.
- Crear planes, cambiar precios en Stars, elegir duración y renovación; consultar pagos, clientes y membresías.
- Recibir soporte, responder conversaciones, añadir notas y gestionar roles del equipo.
- Preparar campañas con confirmación de envío y recordatorios de vencimiento; consultar estadísticas y registros.
- Como administrador de plataforma, ver todos los negocios, usuarios, bots, cobros SaaS, trabajos y auditoría; configurar precios SaaS, suspender negocios y conceder días de acceso sin cobro.
- Como cliente, comprar en Stars, consultar acceso y vencimiento, gestionar renovación, ver políticas y contactar soporte.

La cola, los asistentes y los identificadores de updates se guardan en PostgreSQL. Los tokens de bots y comprobantes se cifran. Cada botón está vinculado al usuario y al bot; los permisos se vuelven a comprobar al usarlo.

## Arranque

Python 3.13. En Seenode selecciona Worker, repositorio `gabolaurav123/Plataforma-SaaS`, rama `main`, directorio `.` y una sola réplica Basic.

Build:

```sh
pip install -r requirements.lock && pip install --no-deps -e .
```

Inicio:

```sh
alembic upgrade head && python scripts/grant_api.py && python scripts/seed.py && python -m platform_app.polling
```

Copia las variables de [worker.env.example](deploy/seenode/worker.env.example) en Seenode y completa los valores privados allí. No subas secretos a GitHub. La guía explica cada variable y la configuración de BotFather.

## Coste y límites iniciales

Una instancia Basic parte de US$3/mes. Neon utiliza su plan existente; el total depende de sus cuotas y del consumo. El lector de Telegram no consulta la base cuando no recibe mensajes. El mantenimiento se ejecuta cada 15 minutos por defecto; la retirada de acceso vencido puede retrasarse hasta ese intervalo. Una solicitud nueva siempre comprueba la fecha real de vencimiento.

Esta configuración requiere una sola réplica y tiene un límite inicial configurable de 20 bots hijos, sin prometer capacidad para tráfico alto. Para actualizar, detener la instancia anterior antes de iniciar la siguiente y evitar dos lectores del mismo token. Las pruebas de Telegram usan un proveedor simulado; completar la prueba real con el nuevo Master antes de aceptar pagos de clientes.

## Código y pruebas

`backend/platform_app/polling.py` ejecuta el proceso único. `services/console.py` contiene los menús de creadores y propietario; `services/console_customer.py`, los de clientes. `migrations/` conserva la evolución del esquema. Ejecutar `pytest` y `ruff check backend tests` después de instalar `requirements.lock`.

La interfaz web existente se conserva para una fase posterior en `apps/web/`. No se construye ni se despliega para este modo. La [arquitectura web opcional](docs/web-opcional.md), sus plantillas y Docker Compose corresponden a ese modo futuro, no al despliegue económico actual.
