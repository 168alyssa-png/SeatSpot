// Validate the migration before asking a user to run it against live stock.
// Full application tests run after the user confirms their Supabase migration.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {startStack} from './local-stack.mjs';

test('four-flavor migration preserves legacy Original stock, orders, names, and session limits',async()=>{
  const stack=await startStack();
  try{
    // Recreate the deployed THREE-flavor schema, including its earlier stored labels.
    await stack.sql(`delete from public.cookie_inventory where id='original';
      alter table public.cookie_inventory drop constraint cookie_inventory_id_check;
      alter table public.cookie_inventory add constraint cookie_inventory_id_check check(id in ('choc','matcha','red'));
      alter table public.cookie_orders drop constraint cookie_orders_cookie_id_fkey;
      alter table public.cookie_orders add constraint cookie_orders_cookie_id_fkey foreign key(cookie_id) references public.cookie_inventory(id);
      update public.cookie_inventory set quantity_remaining=17,active=false,flavor='Original' where id='matcha';
      insert into public.cookie_sessions(session_hash,customer_name) values(repeat('a',64),'Alyssa');
      insert into public.cookie_orders(session_hash,cookie_id,cookie_flavor,table_id,status,customer_name)
      values(repeat('a',64),'matcha','Matcha','B3','Preparing','Alyssa');`);
    const original=JSON.parse(await stack.sql("select row_to_json(i) from public.cookie_inventory i where id='matcha'"));
    const order=JSON.parse(await stack.sql('select row_to_json(o) from public.cookie_orders o'));
    const sessions=await stack.sql('select json_agg(s) from public.cookie_sessions s');
    const stockTotal=await stack.sql('select sum(quantity_remaining) from public.cookie_inventory');
    await assert.rejects(stack.sql(await readFile(new URL('../supabase/setup.sql',import.meta.url),'utf8')),/Run supabase\/add-four-cookie-flavors.sql/);
    const migration=await readFile(new URL('../supabase/add-four-cookie-flavors.sql',import.meta.url),'utf8');
    await stack.sql(migration);
    const moved=JSON.parse(await stack.sql("select row_to_json(i) from public.cookie_inventory i where id='original'"));
    assert.equal(moved.quantity_remaining,original.quantity_remaining);assert.equal(moved.active,original.active);
    assert.equal(moved.flavor,'Original');
    const renamed=JSON.parse(await stack.sql('select row_to_json(o) from public.cookie_orders o'));
    assert.deepEqual({...renamed,cookie_id:order.cookie_id,cookie_flavor:order.cookie_flavor,updated_at:order.updated_at},order);
    assert.equal(renamed.cookie_id,'original');assert.equal(renamed.cookie_flavor,'Original');
    assert.equal(await stack.sql('select json_agg(s) from public.cookie_sessions s'),sessions);
    assert.equal(await stack.sql('select sum(quantity_remaining) from public.cookie_inventory'),stockTotal);
    assert.equal(await stack.sql("select quantity_remaining from public.cookie_inventory where id='matcha'"),'0');
    // Rerunning after staff has stocked NEW Matcha cannot move or reset that stock.
    await stack.sql("update public.cookie_inventory set quantity_remaining=9,active=false where id='matcha'");
    const before=await stack.sql('select json_agg(i order by id) from public.cookie_inventory i');
    await stack.sql(migration);
    assert.equal(await stack.sql('select json_agg(i order by id) from public.cookie_inventory i'),before);
    // Existing orders still consume the SAME anonymous session allowance.
    const retry=JSON.parse(await stack.sql("select public.place_named_cookie_order(repeat('a',64),'matcha',null)"));
    assert.equal(retry.already_ordered,true);assert.equal(retry.order.id,order.id);
    assert.equal(retry.order.cookie_id,'original');assert.equal(retry.order.customer_name,'Alyssa');
    assert.equal(await stack.sql("select quantity_remaining from public.cookie_inventory where id='matcha'"),'9');
    // New installations/reruns preserve the migrated data too.
    await stack.sql(await readFile(new URL('../supabase/setup.sql',import.meta.url),'utf8'));
    assert.equal(await stack.sql("select quantity_remaining from public.cookie_inventory where id='original'"),'17');
    assert.equal(await stack.sql("select quantity_remaining from public.cookie_inventory where id='matcha'"),'9');
  }finally{await stack.stop()}
});
