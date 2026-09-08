import { PGlite } from '@electric-sql/pglite';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
process.on('uncaughtException', error => {
  console.error(JSON.stringify({message:error.message, position:error.position, detail:error.detail}));
  process.exit(1);
});
const db = new PGlite();
await db.exec(await readFile(new URL('../docs/schema-postgres.sql', import.meta.url), 'utf8'));
const { rows: [{ version }] } = await db.query('select version()');
await db.exec(`
  CREATE ROLE tenant_api_test NOLOGIN NOSUPERUSER NOBYPASSRLS;
  GRANT USAGE ON SCHEMA public TO tenant_api_test;
  GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO tenant_api_test;
  REVOKE ALL ON console_states, console_buttons, poll_cursors, auth_sessions, platform_settings, inbox_deliveries FROM tenant_api_test;
  REVOKE INSERT, UPDATE, DELETE ON billing_cycles, commission_entries, platform_invoices, platform_settlements, invoice_adjustments, payment_refunds, subscription_history FROM tenant_api_test;
  REVOKE UPDATE, DELETE ON audit_logs FROM tenant_api_test;
  INSERT INTO platform_users(id,created_at,updated_at,telegram_user_id,first_name,locale) VALUES
    ('u-a',1,1,101,'A','es'),('u-b',1,1,202,'B','es');
  INSERT INTO tenants(id,created_at,updated_at,name,owner_user_id,status) VALUES
    ('t-a',1,1,'A','u-a','ACTIVE'),('t-b',1,1,'B','u-b','ACTIVE');
  INSERT INTO managed_bots(id,created_at,updated_at,tenant_id,telegram_bot_id,owner_telegram_user_id,public_id,username,name,status,published,config_version,health) VALUES
    ('b-a',1,1,'t-a',700001,101,'public-a','a_bot','A','READY',true,1,'{}'),
    ('b-b',1,1,'t-b',700002,202,'public-b','b_bot','B','READY',true,1,'{}');
  INSERT INTO contacts(id,created_at,updated_at,tenant_id,bot_id,telegram_user_id,first_name,stage,last_seen_at,opted_out) VALUES
    ('c-a',1,1,'t-a','b-a',900001,'Client A','ACTIVE',1,false),
    ('c-b',1,1,'t-b','b-b',900002,'Client B','ACTIVE',1,false);
  SET ROLE tenant_api_test;
`);
const checks = [];
async function check(name, fn) { await fn(); checks.push(name); }
await check('Scoped API cannot rewrite commercial ledgers or audit records', async () => {
  for (const table of ['billing_cycles','commission_entries','platform_invoices','platform_settlements','invoice_adjustments','payment_refunds','subscription_history','audit_logs']) {
    await assert.rejects(db.query(`delete from ${table} where false`), /permission denied/);
    await assert.rejects(db.query(`update ${table} set id=id where false`), /permission denied/);
    if (table !== 'audit_logs') await assert.rejects(db.query(`insert into ${table} default values`), /permission denied/);
  }
});
await check('API role cannot access private Telegram state or polling cursors', async () => {
  for (const table of ['console_states', 'console_buttons', 'poll_cursors', 'auth_sessions', 'platform_settings', 'inbox_deliveries']) {
    await assert.rejects(db.query(`select * from ${table}`), /permission denied/);
  }
});
await check('No scope returns no tenant rows', async () => {
  const result = await db.query('select * from contacts'); assert.equal(result.rows.length, 0);
});
await db.query(`select set_config('app.tenant_id','t-a',false)`);
await check('Tenant A only sees its own contacts without WHERE', async () => {
  const result = await db.query('select id from contacts'); assert.deepEqual(result.rows, [{id:'c-a'}]);
});
await check('Tenant A cannot select Tenant B by ID', async () => {
  assert.equal((await db.query(`select * from contacts where id='c-b'`)).rows.length, 0);
});
await check('Tenant A cannot update Tenant B', async () => {
  assert.equal((await db.query(`update contacts set first_name='ATTACK' where id='c-b' returning id`)).rows.length, 0);
});
await check('Tenant A cannot delete Tenant B', async () => {
  assert.equal((await db.query(`delete from contacts where id='c-b' returning id`)).rows.length, 0);
});
await check('RLS blocks cross-tenant INSERT', async () => {
  await assert.rejects(db.exec(`insert into contacts(id,created_at,updated_at,tenant_id,bot_id,telegram_user_id,first_name,stage,last_seen_at,opted_out) values ('attack',1,1,'t-b','b-b',999,'X','LEAD',1,false)`), /row-level security/);
});
await check('Composite FK blocks wrong bot with correct tenant', async () => {
  await assert.rejects(db.exec(`insert into contacts(id,created_at,updated_at,tenant_id,bot_id,telegram_user_id,first_name,stage,last_seen_at,opted_out) values ('bad-fk',1,1,'t-a','b-b',999,'X','LEAD',1,false)`), /foreign key/);
});
await db.query(`select set_config('app.tenant_id','',false)`);
await check('Cleared scope never retains previous tenant access', async () => {
  assert.equal((await db.query('select * from managed_bots')).rows.length, 0);
});
await db.query(`select set_config('app.tenant_id','t-b',false)`);
await check('Tenant B data remained unchanged', async () => {
  assert.deepEqual((await db.query('select first_name from contacts')).rows, [{first_name:'Client B'}]);
});
await db.exec('RESET ROLE');
await check('Every operational table has forced RLS', async () => {
  const result = await db.query(`SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relkind='r' AND EXISTS(SELECT 1 FROM pg_attribute a WHERE a.attrelid=c.oid AND a.attname='tenant_id')
    AND (NOT c.relrowsecurity OR NOT c.relforcerowsecurity)`);
  assert.deepEqual(result.rows, []);
});
const snapshot = await db.dumpDataDir('gzip');
await db.close();
const restored = new PGlite({loadDataDir:snapshot});
assert.equal((await restored.query('select count(*)::int as count from contacts')).rows[0].count,2);
assert.equal((await restored.query("select relforcerowsecurity from pg_class where relname='contacts'")).rows[0].relforcerowsecurity,true);
checks.push('Isolated binary snapshot restores data and RLS');
await restored.close();
console.log(JSON.stringify({engine:version,passed:checks.length,checks},null,2));
