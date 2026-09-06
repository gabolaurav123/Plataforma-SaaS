// Read decrypted backup from stdin; never write or log application data.
import { PGlite } from '@electric-sql/pglite';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

let stage='read';
try {
  let input='';
  for await (const chunk of process.stdin) input+=chunk.toString('utf8');
  const backup=JSON.parse(input);
  assert.equal(backup.format,1);
  const db=new PGlite();
  stage='schema';
  await db.exec(backup.schema);
  const columns=(await db.query(backup.columns_sql)).rows;
  const expected=Object.values(backup.tables).flatMap(table=>table.columns);
  assert.deepEqual(columns,expected);
  const quote=value=> '"'+value.replaceAll('"','""')+'"';
  stage='restore';
  await db.exec('BEGIN; DELETE FROM alembic_version;');
  for (const name of backup.order) {
    const table=backup.tables[name];
    for (const row of table.rows) {
      const fields=table.columns.map(column=>column.column_name);
      const values=table.columns.map(column=>column.type==='json' || column.type==='jsonb' ? JSON.stringify(row[column.column_name]) : row[column.column_name]);
      await db.query(`INSERT INTO ${quote(name)}(${fields.map(quote).join(',')}) VALUES(${values.map((_,i)=>'$'+(i+1)).join(',')})`,values);
    }
  }
  await db.exec('COMMIT;');
  stage='compare';
  const canonical=value=>JSON.stringify(value, Object.keys(value).sort());
  for (const [name,table] of Object.entries(backup.tables)) {
    const fields=table.columns.map(column=>quote(column.column_name)+(column.type==='bigint'?'::text AS '+quote(column.column_name):''));
    const rows=(await db.query(`SELECT ${fields.join(',')} FROM ${quote(name)}`)).rows;
    const sort=rows=>rows.sort((a,b)=>canonical(a).localeCompare(canonical(b)));
    assert.deepEqual(sort(rows),sort(table.rows));
  }
  if (backup.version==='0004') {
    stage='upgrade';
    const schema=await readFile(new URL('../docs/schema-postgres.sql',import.meta.url),'utf8');
    await db.exec('BEGIN;'+schema.split('-- Running upgrade 0004 -> 0005')[1]);
    assert.equal((await db.query('SELECT version_num FROM alembic_version')).rows[0].version_num,'0005');
    for (const [name,table] of Object.entries(backup.tables)) {
      assert.equal((await db.query(`SELECT count(*)::int AS total FROM ${quote(name)}`)).rows[0].total,table.rows.length);
    }
  }
  await db.close();
  console.log(JSON.stringify({restore_verified:true,all_original_rows_equal:true,tables:Object.keys(backup.tables).length,isolated_upgrade_verified:backup.version==='0004'}));
} catch(error) {
  console.log(JSON.stringify({restore_failed:true,stage,code:error.code || error.name}));
  process.exitCode=1;
}
