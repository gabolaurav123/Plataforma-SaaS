# Plataforma SaaS · Administración desde Telegram

Un bot maestro para las cuentas y la facturación de la plataforma. Cada cliente conecta su propio bot mediante BotFather y administra su negocio **desde ese bot**. El despliegue utiliza un Worker de Seenode y la base Neon existente.

**[Novedades y uso](docs/mejoras-0006.md)** · **[Despliegue](docs/seenode.md)** · **[Uso desde Telegram](docs/telegram.md)** · **[Facturación](docs/facturacion.md)** · **[Arquitectura](docs/arquitectura.md)** · **[Pruebas](docs/pruebas.md)**

## Funciones

- Prueba de tres días, activada expresamente una vez por propietario; conexiones de bots con validación, confirmación, cifrado, sustitución y desconexión.
- Panel del negocio con planes, precios, canales, suscripciones, CRM, comprobantes, invitaciones gratuitas, campañas, mensajes, equipo y reportes CSV.
- Idiomas español, inglés y portugués; preferencia del administrador independiente de la del comprador.
- Mensajes privados de clientes con aviso al equipo y respuesta nativa de Telegram; `/id` en cada bot.
- Billeteras públicas por activo y red (USDT, USDC, BTC, BNB, ETH, SOL, TON y XRP), con comprobante y aprobación manual.
- Telegram Stars; transferencias con revisión humana para operaciones admitidas; integración de Stripe y PayPal con creación de pagos y verificación del proveedor.
- Facturación SaaS en USD: cuota fija más comisión histórica, ciclos de 30 días, cambios de plan al próximo ciclo, ajustes, pagos parciales y control de vencimientos.
- Resumen de recursos utilizados, ventas por moneda, comisiones y saldo a pagar, accesible desde Telegram y adjunto al aviso de factura.
- Superadministración de negocios, bots, usuarios, cuentas, cobros, actividad y errores. Una suspensión administrativa requiere intervención del propietario de la plataforma.

## Planes iniciales de la plataforma

| Plan | Cuota por 30 días | Comisión |
|---|---:|---:|
| STARTER | USD 0 | 8% |
| PRO | USD 30 | 4% |
| AGENCY | USD 80 | 1% |

Las tasas de cada venta se conservan. La prueba no genera cuotas ni comisiones SaaS. Los pagos del comprador al negocio están separados de los pagos del negocio a la plataforma.

## Seenode

Repositorio `gabolaurav123/Plataforma-SaaS`, rama `main`, raíz `.`, Python 3.13, **una instancia Worker Basic**. Sin web, Mini App, Redis ni puerto público en el despliegue actual.

Build:

```sh
pip install -r requirements.lock && pip install --no-deps -e .
```

Inicio:

```sh
alembic upgrade head && python scripts/grant_api.py && python scripts/seed.py && python -m platform_app.polling
```

La migración actual es `0006`; conserva los registros anteriores y aplica las nuevas estructuras. Usar [las variables del Worker](deploy/seenode/worker.env.example), completar secretos en Seenode y conservar las claves de cifrado.

Stripe y PayPal requieren credenciales de cada negocio y una entrada HTTPS para sus confirmaciones. El código permite incorporar esa entrada en el mismo proceso, pero el Worker actual la mantiene desactivada. [Configuración de proveedores](docs/pagos.md).

Se utiliza la instancia Basic existente y el plan de Neon del operador. El panel y la [tarifa pública actual de Seenode](https://seenode.com/pricing) muestran US$4/mes para Basic; esta actualización conserva esa instancia y no añade servicios ni réplicas. El límite inicial es 20 bots conectados. Es una barrera operativa, no una garantía de capacidad a tráfico alto. [Mediciones y límites](docs/rendimiento.md).

El antiguo servicio y repositorio `telegram-saas-bot` no forman parte de este despliegue. La interfaz de `apps/web/` queda como código opcional para una fase posterior.
