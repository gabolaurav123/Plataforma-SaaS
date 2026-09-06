# Creator Engine · Telegram

Plataforma nueva e independiente para creadores: Master Bot, Master Mini App, Managed Bots oficiales y Customer Mini App sobre un backend central. **El bot actual de producción no se leyó, modificó, conectó ni migró.**

Esta entrega contiene una implementación ejecutable, migraciones y pruebas. Es una primera versión extensa; **todavía no es una plataforma certificada para producción ni incluye todas las funciones de la visión final**. Consulta el [estado por fase](docs/estado.md) y el [informe de pruebas](docs/pruebas.md).

La vista privada de Sites permite revisar el panel con datos ficticios fuera de Telegram. Para operar con usuarios reales hacen falta un Master Bot nuevo, HTTPS, PostgreSQL, Redis y la configuración descrita abajo. La publicación privada de la interfaz no despliega el backend ni activa bots reales.

[Abrir vista privada del panel](https://creator-engine-telegram.gabolaurav2.chatgpt.site) · [Ver el ejemplo del cliente](https://creator-engine-telegram.gabolaurav2.chatgpt.site/b/demo)

## Qué incluye

- Autenticación validada con `initData`, espacios de trabajo, varios bots por creador, roles y sesiones de duración limitada.
- Creación oficial de Managed Bots, cifrado de tokens, provisioning, webhook por identidad, personalización, salud y reparación.
- Wizard del creador, administración del propietario y Mini App del cliente con catálogo, Stars, membresías y soporte.
- Planes, pagos únicos o recurrentes, eventos de pago, reembolsos Stars, comprobantes con revisión manual y acceso al canal.
- CRM, inbox, notas, campañas segmentadas, automatizaciones, cupones, atribución y registro de referidos.
- Suscripción SaaS del creador separada de sus ventas, prueba gratuita, límites y funciones por plan.
- Migraciones, RLS, cola persistente, workers, rate limits, Docker Compose, scripts de operación y documentación.

## Estructura

```text
backend/platform_app/  API, modelos, servicios, seguridad, workers
apps/web/              Master Mini App + Customer Mini App, React/TypeScript/Sites
migrations/            Alembic: esquema inicial y aislamiento PostgreSQL
tests/                 Pruebas de dominio, API, seguridad, enrutamiento y transporte
qa/                    Pruebas PostgreSQL embebido y restauración de snapshot
scripts/               Inicialización, permisos, Master Bot y backups
infra/                 Caddy, tareas systemd y rol PostgreSQL
docs/                  Arquitectura, contratos, operación, estado y pruebas
```

## Ejecutar localmente

Requisitos: Python 3.13 o 3.14, Node 24 y npm. SQLite permite trabajar localmente; la configuración de producción exige PostgreSQL y Redis.

En una terminal abierta **en esta carpeta nueva**:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
python scripts/bootstrap.py
alembic upgrade head
python scripts/seed.py
uvicorn platform_app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

`bootstrap.py` crea claves aleatorias en el `.env` local ignorado y conserva cualquier `.env` existente. Deja vacío el token de Telegram. Nunca busca configuración de otros proyectos.

En otra terminal, desde esta misma carpeta:

```powershell
.\.venv\Scripts\Activate.ps1
python -m platform_app.worker
```

Para la interfaz:

```powershell
cd apps/web
npm ci
Copy-Item -LiteralPath .dev.vars.example -Destination .dev.vars
npm run dev -- --host 127.0.0.1 --port 3000
```

Abre [el panel local](http://localhost:3000) y [el ejemplo del cliente](http://localhost:3000/b/demo). Fuera de Telegram se muestran ejemplos identificados como ficticios y no se guardan operaciones. La [API local](http://localhost:8000/docs) publica los contratos; no permite saltarse la autenticación de Telegram.

## Pasos manuales para activar el sistema nuevo

1. Crear **otro** Master Bot en BotFather. Habilitar Bot Management Mode en la Mini App de BotFather y configurar su Main Mini App. [Instrucciones detalladas](docs/telegram.md).
2. Elegir el dominio HTTPS del backend y el dominio de las Mini Apps, y desplegar PostgreSQL/Redis/API/workers. [Despliegue](docs/operacion.md).
3. Guardar el token nuevo, tu ID de propietario, URLs y claves en el entorno privado del servidor. [Variables](docs/variables.md). No poner tokens en Sites, URLs ni archivos compartidos.
4. Ejecutar `python scripts/configure_master.py`. Verificar que `can_manage_bots` sea verdadero.
5. Entrar al Master Bot y configurar los precios de la plataforma desde **Platform Owner → Planes SaaS**. Los precios iniciales están vacíos deliberadamente.
6. Crear un bot de prueba desde el wizard, pulsar Start en ese bot, conectar un canal de prueba, completar políticas y planes, y usar Publicar para ejecutar el chequeo de preparación.
7. Completar la [prueba real de aceptación](docs/pruebas.md), configurar copias cifradas y alertas, y revisar los pendientes antes de ofrecer el servicio.

Después de esta instalación inicial, la creación y configuración de cada bot se realizan desde el wizard. La revisión humana de comprobantes bancarios permanece como parte intencional de ese método.

## Cobros

Las membresías digitales compradas dentro de Telegram usan **Telegram Stars**. La transferencia implementada registra pedidos originados fuera de Telegram; no se ofrece como alternativa al checkout digital interno. No hay procesador de tarjetas conectado. [Decisiones y fuentes oficiales](docs/telegram.md).

## Verificación

```powershell
pytest --cov=platform_app
ruff check backend tests
alembic check
npm ci --prefix qa
npm run test:rls --prefix qa
cd apps/web
npm run check
npm run build
npm audit --audit-level=high
```

El CI incluido repite estas verificaciones. `npm run lint` analiza las pantallas, rutas y librerías propias; los componentes vendorizados de shadcn conservan su implementación del scaffold.

## Documentación

- [Arquitectura A–K y diagramas](docs/arquitectura.md)
- [Investigación actual y BotFather](docs/telegram.md)
- [Variables](docs/variables.md) · [API y permisos](docs/endpoints.md)
- [Operación, despliegue, backups y recuperación](docs/operacion.md)
- [Controles de seguridad](docs/seguridad.md)
- [Estado y pendientes por fase](docs/estado.md)
- [Pruebas y límites de la validación](docs/pruebas.md)

No hay conexión con el bot anterior. `LegacyImporter` define únicamente un contrato futuro para una importación separada y autorizada.
