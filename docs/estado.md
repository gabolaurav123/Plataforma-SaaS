# Estado de la entrega comercial

El código utiliza la migración `0005`, conexión de bots por token, administración en el bot del negocio y facturación SaaS USD con liquidaciones manuales.

Consultar [pruebas](pruebas.md) para evidencia local y [Seenode](seenode.md) para la configuración de producción. El estado de un despliegue real se verifica por su revisión y registros; la existencia de código de un proveedor no implica que sus credenciales o pagos live hayan sido comprobados.

Continúa previsto un único Worker Basic. Stripe/PayPal requieren credenciales y HTTPS; las instrucciones de banco/cripto y tasas de conversión de la plataforma se completan desde el superadministrador.
