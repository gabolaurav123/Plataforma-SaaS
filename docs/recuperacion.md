# Respaldo y recuperación

Antes de una actualización conservar la base y una copia independiente de `ENCRYPTION_KEYS`. La base contiene los tokens y archivos cifrados; sin las claves originales no se recuperan.

## Copia portátil verificada

`scripts/backup_portable.py` es una alternativa cuando no está disponible `pg_dump`. Sirve para bases cuyo esquema está gestionado por las migraciones del repositorio. Incluye tablas y registros de aplicación, no roles externos del servidor ni archivos fuera de Neon. Para esquemas modificados independientemente, usar `pg_dump`.

Establecer `MIGRATION_DATABASE_URL` y `ENCRYPTION_KEYS` en un entorno privado; no escribirlos en el historial de comandos. Instalar las dependencias Python y `npm ci --prefix qa`.

```sh
python scripts/backup_portable.py --expect-host HOST_DIRECTO_NEON --expect-version 0005 --output backups/plataforma.backup.enc --verify
```

El script verifica el host, abre una transacción de solo lectura con vista consistente, cifra el respaldo y lo escribe sin sobrescribir otro archivo. `--verify` descifra el archivo guardado y restaura todas las tablas en un PostgreSQL aislado mediante PGlite, comparando cada fila. Para una copia de `0004`, verifica además la actualización a `0005`.

Se realizó este procedimiento antes de actualizar la base nueva: 51 tablas, 113 registros, revisión `0004`, igualdad de todas las filas y actualización aislada comprobadas. La copia entregada es `Neon-antes-actualizacion-0005.backup.enc`. Corresponde a ese momento, no sustituye respaldos periódicos posteriores.

## Restauración operativa

Detener el Worker antes de una recuperación real. Crear una base de destino vacía, restaurar el esquema de la revisión correcta y las filas en el orden guardado en el respaldo; restituir los roles y ejecutar el script de permisos correspondiente a esa revisión. Validar conteos, fechas de membresías, claves cifradas y aislamiento antes de cambiar las conexiones del Worker.

`qa/restore-backup.mjs` solo restaura en su PostgreSQL local aislado. No tiene acceso a Neon y no borra una base de producción. Los scripts anteriores `backup.sh`, `backup.ps1` y `restore-drill.sh` corresponden al despliegue Docker opcional y requieren sus herramientas; no ejecutarlos sobre Seenode sin adaptar el destino.

Si se necesita volver a `0004`, restaurar juntos código y base de esa revisión. No ejecutar un downgrade que elimine libros financieros nuevos. Revisar los pagos recibidos desde el respaldo para reconciliarlos y evitar perder confirmaciones posteriores.
