# Creator Engine Mini Apps

Interfaz nueva del creador y sus clientes. React 19, TypeScript, vinext/Sites y componentes shadcn. El backend Python/PostgreSQL se entrega en la carpeta principal de la plataforma.

- `/`: Master Mini App, wizard, CRM, pagos, campañas y administración.
- `/b/{publicId}`: Customer Mini App del bot correspondiente.
- `/b/demo`: ejemplo visual con datos ficticios.
- `/api/backend/*`: proxy de servidor hacia la API central configurada.

```bash
npm ci
cp .dev.vars.example .dev.vars
npm run dev -- --host 127.0.0.1 --port 3000
```

Configura `PLATFORM_API_URL` solo como origen del backend: `http://localhost:8000` local o un origen HTTPS real. No añadas tokens de Telegram al frontend. Las sesiones se obtienen con `initData` validado por el backend y permanecen en memoria.

```bash
npm run check
npm run build
npm audit --audit-level=high
```

El lint abarca rutas, pantallas y librerías propias; los componentes shadcn vendorizados no se alteran para satisfacer reglas ajenas a esta implementación.

Fuera de Telegram se presenta una vista de ejemplo claramente identificada. No se simulan guardados ni pagos reales. Una publicación privada permite revisión del propietario, pero no habilita acceso de todos los clientes ni despliega los servicios de negocio.
