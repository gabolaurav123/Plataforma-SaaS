import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const cli = fileURLToPath(new URL('../node_modules/vinext/dist/cli.js', import.meta.url));
const result = spawnSync(process.execPath, [cli, 'build'], {
  cwd: fileURLToPath(new URL('..', import.meta.url)),
  env: { ...process.env, SEENODE_BUILD: 'true' },
  stdio: 'inherit',
});
if (result.error) console.error('No se pudo iniciar la compilación:', result.error.message);
process.exit(result.status ?? 1);
