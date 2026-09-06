# Variables de configuración

La configuración operativa del único Worker está documentada en [Seenode](seenode.md#variables) y en [worker.env.example](../deploy/seenode/worker.env.example).

Las instrucciones de cobro, conversiones, cuotas SaaS, idiomas, zona horaria, textos, permisos y credenciales de los proveedores de cada negocio se administran desde Telegram. No se comparten credenciales de Stripe o PayPal entre bots.

Los secretos globales son los tres accesos Neon, el token del maestro y el keyring. No incluirlos en Git, salidas de pruebas ni archivos públicos. Las variables opcionales de HTTP se describen en [pagos](pagos.md#requisitos-de-stripe-y-paypal).

El frontend legado usa variables propias como `PLATFORM_API_URL`; no son necesarias para el despliegue Telegram actual.
