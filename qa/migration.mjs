import { PGlite } from '@electric-sql/pglite';
import { readFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import assert from 'node:assert/strict';

process.on('uncaughtException', error => {
  console.error(JSON.stringify({ message: error.message, position: error.position, detail: error.detail }));
  process.exit(1);
});
const schema = await readFile(new URL('../docs/schema-postgres.sql', import.meta.url), 'utf8');
const marker = '-- Running upgrade 0004 -> 0005';
assert.equal(schema.split(marker).length, 2);
const [old, upgrade] = schema.split(marker);
const db = new PGlite();
await db.exec(old + 'COMMIT;');
const timestamp = Math.floor(Date.now() / 1000);

async function add(table, overrides) {
  const columns = (await db.query(`SELECT column_name, udt_name, is_nullable, column_default FROM information_schema.columns WHERE table_schema='public' AND table_name=$1 ORDER BY ordinal_position`, [table])).rows;
  const values = {};
  for (const col of columns) {
    const key = col.column_name;
    if (key in overrides) values[key] = overrides[key];
    else if (key === 'id') values[key] = randomUUID();
    else if (['created_at', 'updated_at'].includes(key)) values[key] = timestamp;
    else if (col.is_nullable === 'NO' && col.column_default === null) values[key] = ['json', 'jsonb'].includes(col.udt_name) ? {} : col.udt_name === 'bool' ? false : ['int2', 'int4', 'int8'].includes(col.udt_name) ? 0 : '';
  }
  const keys = Object.keys(values);
  const args = keys.map(key => {
    const type = columns.find(x => x.column_name === key).udt_name;
    return ['json', 'jsonb'].includes(type) ? JSON.stringify(values[key]) : values[key];
  });
  await db.query(`INSERT INTO "${table}" (${keys.map(x => '"' + x + '"').join(',')}) VALUES (${keys.map((_, i) => '$' + (i + 1)).join(',')})`, args);
  return values.id;
}

const user = await add('platform_users', { telegram_user_id: 101, first_name: 'Preserved owner', locale: 'es' });
const tenant = await add('tenants', { owner_user_id: user, name: 'Preserved workspace', status: 'TRIAL' });
await add('tenant_members', { tenant_id: tenant, user_id: user, role: 'OWNER', active: true });
const saas = await add('saas_plans', { name: 'PRO', features: { stars: true }, limits: { bots: 3 }, prices: {}, active: true });
const subscription = await add('saas_subscriptions', { tenant_id: tenant, plan_id: saas, status: 'TRIAL', trial_ends_at: timestamp + 7 * 86400, current_period_end: timestamp + 7 * 86400 });
const bot = await add('managed_bots', { tenant_id: tenant, telegram_bot_id: 700001, owner_telegram_user_id: 101, public_id: randomUUID(), username: 'preserved_bot', name: 'Preserved bot', status: 'READY', published: true, config_version: 1 });
await add('bot_settings', { tenant_id: tenant, bot_id: bot, commands: [], policies: { terms: 'Keep these terms' } });
const channel = await add('channels', { tenant_id: tenant, bot_id: bot, telegram_chat_id: -10012345, title: 'Existing channel', status: 'CONNECTED', access_mode: 'PLATFORM' });
const plan = await add('plans', { tenant_id: tenant, bot_id: bot, channel_id: channel, name: 'Existing plan', duration_days: 30, active: true, benefits: [], product_kind: 'DIGITAL' });
const contact = await add('contacts', { tenant_id: tenant, bot_id: bot, telegram_user_id: 900001, first_name: 'Existing customer', stage: 'ACTIVE', last_seen_at: timestamp });
const payment = await add('payments', { tenant_id: tenant, bot_id: bot, contact_id: contact, plan_id: plan, provider: 'TELEGRAM_STARS', currency: 'XTR', amount_minor: 500, duration_days: 30, status: 'APPROVED', idempotency_key: randomUUID(), invoice_payload: randomUUID() });
await add('payment_charges', { tenant_id: tenant, payment_id: payment, bot_id: bot, provider: 'TELEGRAM_STARS', charge_id: 'preserved-charge', currency: 'XTR', amount_minor: 500, period_end: timestamp + 30 * 86400 });
const membership = await add('subscriptions', { tenant_id: tenant, bot_id: bot, contact_id: contact, plan_id: plan, payment_id: payment, starts_at: timestamp, expires_at: timestamp + 30 * 86400, status: 'ACTIVE' });
const provider = await add('payment_provider_configs', { tenant_id: tenant, provider: 'BANK_TRANSFER', enabled: true, public_config: { currency: 'USD' }, secrets_ciphertext: { encrypted_fixture: 'preserve byte-for-byte' } });
await add('console_states', { bot_key: 'master', telegram_user_id: 101, data: { flow: 'existing-dialog' }, expires_at: timestamp + 86400 });
const backup = await db.dumpDataDir('gzip');
await db.exec('BEGIN;\n' + upgrade);

const checks = [];
async function check(name, fn) { await fn(); checks.push(name); }
await check('PostgreSQL upgrades populated 0004 to 0005', async () => {
  assert.equal((await db.query('SELECT version_num FROM alembic_version')).rows[0].version_num, '0005');
});
await check('Paid access and purchased channels remain unchanged', async () => {
  const row = (await db.query('SELECT * FROM subscriptions WHERE id=$1', [membership])).rows[0];
  assert.equal(Number(row.expires_at), timestamp + 30 * 86400);
  assert.deepEqual(row.channel_snapshot, [channel]);
  assert.deepEqual((await db.query('SELECT channel_snapshot FROM payments WHERE id=$1', [payment])).rows[0].channel_snapshot, [channel]);
});
await check('Existing trial end is preserved and reuse is prevented', async () => {
  assert.equal(Number((await db.query('SELECT trial_ends_at FROM saas_subscriptions WHERE id=$1', [subscription])).rows[0].trial_ends_at), timestamp + 7 * 86400);
  assert.equal(Number((await db.query('SELECT trial_used_at FROM platform_users WHERE id=$1', [user])).rows[0].trial_used_at), timestamp);
});
await check('Encrypted bank settings are copied with their original encryption context', async () => {
  const row = (await db.query('SELECT * FROM bot_payment_methods WHERE bot_id=$1', [bot])).rows[0];
  assert.deepEqual(row.secrets_ciphertext, { encrypted_fixture: 'preserve byte-for-byte' });
  assert.equal(row.public_config._legacy_provider_id, provider);
});
await check('Legacy sales receive zero retroactive commission and history revision one', async () => {
  assert.equal((await db.query('SELECT commission_bps FROM commission_entries')).rows[0].commission_bps, 0);
  const row = (await db.query('SELECT revision, after FROM subscription_history')).rows[0];
  assert.equal(Number(row.revision), 1);
  assert.deepEqual(row.after.channels, [channel]);
  assert.equal((await db.query('SELECT count(*)::int AS count FROM bot_admins')).rows[0].count, 1);
});
await check('New plan terms and original dialogs are preserved', async () => {
  const row = (await db.query('SELECT fixed_usd_minor,commission_bps,features FROM saas_plans WHERE id=$1', [saas])).rows[0];
  assert.equal(Number(row.fixed_usd_minor), 3000);
  assert.equal(row.commission_bps, 400);
  assert.equal(row.features.stars, true);
  assert.equal(row.features.external_payments, true);
  assert.deepEqual((await db.query('SELECT data FROM console_states')).rows[0].data, { flow: 'existing-dialog' });
});
await db.close();
const restored = new PGlite({ loadDataDir: backup });
await check('Pre-upgrade backup restores the old schema and real fixture records', async () => {
  assert.equal((await restored.query('SELECT version_num FROM alembic_version')).rows[0].version_num, '0004');
  assert.equal((await restored.query('SELECT charge_id FROM payment_charges')).rows[0].charge_id, 'preserved-charge');
  assert.deepEqual((await restored.query('SELECT secrets_ciphertext FROM payment_provider_configs')).rows[0].secrets_ciphertext, { encrypted_fixture: 'preserve byte-for-byte' });
});
await restored.close();
console.log(JSON.stringify({ passed: checks.length, checks }, null, 2));
