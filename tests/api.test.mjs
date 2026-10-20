import { test, before, after, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { createHash } from 'node:crypto';
import { startStack, STAFF, NONSTAFF } from './local-stack.mjs';
import { createHandler } from '../server/handler.mjs';

let stack;
before(async()=>{stack=await startStack()});
after(async()=>{if(stack)await stack.stop()});
beforeEach(async()=>{await stack.reset()});

function client(){
  const jar=new Map();
  return {
    jar,
    async request(action='state',body,extra={}){
      const headers={Cookie:[...jar].map(([k,v])=>`${k}=${v}`).join('; '),...extra.headers};
      if(body!==undefined){headers.Origin=extra.origin??stack.base;headers['Content-Type']='application/json';}
      const response=await fetch(`${stack.base}/api/seatspot?action=${action}`,{
        method:body===undefined?'GET':'POST',headers,
        ...(body===undefined?{}:{body:JSON.stringify(body)})
      });
      for(const cookie of response.headers.getSetCookie()){
        const [name,value]=cookie.split(';')[0].split('=');jar.set(name,value);
      }
      const data=await response.json();
      assert(!JSON.stringify(data).includes(stack.serviceToken),'Server credential must never be returned');
      return {status:response.status,data,headers:response.headers};
    }
  };
}
async function customer(){const c=client();assert.equal((await c.request()).status,200);assert.equal((await c.request('welcome',{customer_name:'Test visitor'})).status,200);return c}
async function staff(){const c=client();assert.equal((await c.request('staff-login',STAFF)).status,200);return c}
const stock=async id=>Number(await stack.sql(`select quantity_remaining from public.cookie_inventory where id='${id}'`));

test('missing configuration fails closed without exposing environment names or values',async()=>{
  const server=createServer(createHandler({env:{}}));
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try{
    const response=await fetch(`http://127.0.0.1:${server.address().port}/api/seatspot`);
    assert.equal(response.status,503);assert.equal((await response.json()).error.code,'SETUP_REQUIRED');
  }finally{await new Promise(resolve=>server.close(resolve))}
});

test('stock is read-only and a customer gets an opaque HttpOnly session',async()=>{
  const c=client();const result=await c.request();
  assert.equal(result.status,200);assert.equal(result.data.inventory.length,3);
  assert(result.data.inventory.every(item=>item.quantity_remaining===5));
  assert.equal(result.data.order,null);
  const cookie=result.headers.getSetCookie()[0];
  assert.match(cookie,/HttpOnly/);assert.match(cookie,/SameSite=Lax/);
  assert.match(c.jar.get('seatspot_session'),/^[A-Za-z0-9_-]{43}$/);
  assert(!JSON.stringify(result.data).includes('session_hash'));
});

test('an order has one flavor, quantity 1, optional table, timestamp, and New status',async()=>{
  const c=await customer();const result=await c.request('order',{cookie_id:'choc',quantity:1,table_id:'B3'});
  assert.equal(result.status,200);assert.equal(result.data.order.cookie_flavor,'Chocolate');
  assert.equal(result.data.order.quantity,1);assert.equal(result.data.order.table_id,'B3');
  assert.equal(result.data.order.status,'New');assert(!Number.isNaN(Date.parse(result.data.order.created_at)));
  assert.equal(await stock('choc'),4);assert.equal(Number(await stack.sql('select count(*) from public.cookie_orders')),1);
  assert(!('session_hash' in result.data.order));
});

test('a customer without table check-in can order; reload restores the same order',async()=>{
  const c=await customer();const placed=await c.request('order',{cookie_id:'matcha'});
  assert.equal(placed.data.order.table_id,null);
  const restored=await c.request();assert.equal(restored.data.order.id,placed.data.order.id);
  assert.equal(c.jar.size,1);
});

test('retries and different flavor attempts return the original order without another decrement',async()=>{
  const c=await customer();const first=await c.request('order',{cookie_id:'choc',table_id:'A12'});
  for(const cookie_id of ['choc','red','matcha']){
    const retry=await c.request('order',{cookie_id,table_id:'C1'});
    assert.equal(retry.status,200);assert.equal(retry.data.already_ordered,true);
    assert.equal(retry.data.order.id,first.data.order.id);assert.equal(retry.data.order.table_id,'A12');
  }
  assert.equal(await stock('choc'),4);assert.equal(await stock('red'),5);assert.equal(await stock('matcha'),5);
});

test('20 simultaneous customers competing for the last cookie cannot oversell',async()=>{
  await stack.sql("update public.cookie_inventory set quantity_remaining=1 where id='choc'");
  const customers=await Promise.all(Array.from({length:20},()=>customer()));
  const results=await Promise.all(customers.map(c=>c.request('order',{cookie_id:'choc'})));
  assert.equal(results.filter(r=>r.status===200).length,1);
  assert.equal(results.filter(r=>r.status===409&&r.data.error.code==='SOLD_OUT').length,19);
  assert.equal(await stock('choc'),0);assert.equal(Number(await stack.sql('select count(*) from public.cookie_orders')),1);
});

test('simultaneous different-flavor requests from one session create exactly one order',async()=>{
  const c=await customer();
  const results=await Promise.all(Array.from({length:24},(_,i)=>c.request('order',{cookie_id:['choc','matcha','red'][i%3]})));
  assert(results.every(r=>r.status===200));
  assert.equal(new Set(results.map(r=>r.data.order.id)).size,1);
  assert.equal(Number(await stack.sql('select sum(quantity_remaining) from public.cookie_inventory')),14);
  assert.equal(Number(await stack.sql('select count(*) from public.cookie_orders')),1);
});

test('zero stock and paused flavors cannot be ordered',async()=>{
  const c=await customer();
  await stack.sql("update public.cookie_inventory set quantity_remaining=0 where id='red'; update public.cookie_inventory set active=false where id='matcha'");
  for(const cookie_id of ['red','matcha'])assert.equal((await c.request('order',{cookie_id})).data.error.code,'SOLD_OUT');
  assert.equal(Number(await stack.sql('select count(*) from public.cookie_orders')),0);
});

test('customers cannot change stock or order status, and forged session fields are ignored',async()=>{
  const a=await customer(),b=await customer();
  const original=await a.request('order',{cookie_id:'red'});
  assert.equal((await b.request('inventory',{cookie_id:'red',quantity:999})).status,401);
  assert.equal((await b.request('order-status',{order_id:original.data.order.id,status:'Ready'})).status,401);
  const otherHash=createHash('sha256').update(a.jar.get('seatspot_session')).digest('hex');
  assert.equal((await b.request(`state&session_hash=${otherHash}`)).data.order,null);
  const placed=await b.request('order',{cookie_id:'choc',session_hash:otherHash});
  assert.notEqual(placed.data.order.id,original.data.order.id);
});

test('anonymous and authenticated direct database/RPC requests are denied',async()=>{
  for(const token of [stack.anonToken,stack.token('authenticated',NONSTAFF.id)]){
    for(const [path,method,body] of [
      ['cookie_inventory','GET'],['cookie_orders','GET'],['cookie_sessions','GET'],['staff_members','GET'],
      ['cookie_inventory?id=eq.choc','PATCH',{quantity_remaining:999}],
      ['cookie_orders','POST',{cookie_id:'choc',quantity:1}],
      ['rpc/set_customer_name','POST',{p_session_hash:'0'.repeat(64),p_customer_name:'Visitor'}],
      ['rpc/place_named_cookie_order','POST',{p_session_hash:'0'.repeat(64),p_cookie_id:'choc'}],
      ['rpc/place_cookie_order','POST',{p_session_hash:'0'.repeat(64),p_cookie_id:'choc'}],
      ['rpc/set_cookie_inventory','POST',{p_staff_id:STAFF.id,p_cookie_id:'choc',p_quantity:999}],
      ['rpc/set_cookie_order_status','POST',{p_staff_id:STAFF.id,p_order_id:STAFF.id,p_status:'Ready'}]
    ]){
      const response=await fetch(`${stack.restBase}/${path}`,{method,headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});
      assert([401,403].includes(response.status),`${method} ${path} unexpectedly allowed: ${response.status}`);
    }
  }
  assert.equal(await stock('choc'),5);
});

test('staff login requires both valid Supabase authentication and allowlist membership',async()=>{
  const c=client();
  assert.equal((await c.request('staff-login',{...STAFF,password:'wrong'})).status,401);
  assert.equal((await c.request('staff-login',NONSTAFF)).status,403);
  assert(!c.jar.has('seatspot_staff'));
  assert.equal((await c.request('staff-login',STAFF)).status,200);
  assert.equal((await c.request('staff-state')).data.staff.email,STAFF.email);
  await c.request('staff-logout',{});assert.equal((await c.request('staff-state')).status,401);
});

test('staff stock edits and atomic adjustments are visible to all customer sessions',async()=>{
  const admin=await staff(),a=await customer(),b=await customer();
  assert.equal((await admin.request('inventory',{cookie_id:'choc',quantity:10,active:true})).status,200);
  await Promise.all([admin.request('inventory',{cookie_id:'choc',adjustment:5}),admin.request('inventory',{cookie_id:'choc',adjustment:5})]);
  assert.equal(await stock('choc'),20);
  for(const c of [a,b])assert.equal((await c.request()).data.inventory.find(i=>i.id==='choc').quantity_remaining,20);
  await admin.request('inventory',{cookie_id:'choc',active:false});
  assert.equal((await a.request('order',{cookie_id:'choc'})).status,409);
});

test('negative inventory and invalid inputs are rejected without mutation',async()=>{
  const admin=await staff(),c=await customer();
  assert.equal((await admin.request('inventory',{cookie_id:'choc',adjustment:-6})).status,409);
  assert.equal(await stock('choc'),5);
  for(const body of [{cookie_id:'choc',quantity:2},{cookie_id:'choc',table_id:'B99'},{cookie_id:'__proto__'},{cookie_id:'choc',quantity:-1}])assert.equal((await c.request('order',body)).status,400);
  assert.equal((await admin.request('inventory',{cookie_id:'choc',quantity:3,adjustment:1})).status,400);
  assert.equal((await admin.request('inventory',{cookie_id:'choc',quantity:3.5})).status,400);
});

test('staff can move orders between all three statuses; customer sees actual status',async()=>{
  const admin=await staff(),c=await customer();const placed=await c.request('order',{cookie_id:'matcha',table_id:'C11'});
  for(const status of ['Preparing','Ready','New']){
    assert.equal((await admin.request('order-status',{order_id:placed.data.order.id,status})).status,200);
    assert.equal((await c.request()).data.order.status,status);
  }
  const list=(await admin.request('staff-state')).data.orders;
  assert.equal(list[0].table_id,'C11');assert.equal(list[0].cookie_flavor,'Original');assert(!('session_hash' in list[0]));
  assert.equal((await admin.request('order-status',{order_id:placed.data.order.id,status:'Deleted'})).status,400);
});

test('removed staff immediately loses dashboard and mutation access',async()=>{
  const admin=await staff();await stack.sql(`delete from public.staff_members where user_id='${STAFF.id}'`);
  assert.equal((await admin.request('staff-state')).status,403);
  assert.equal((await admin.request('inventory',{cookie_id:'choc',quantity:100})).status,403);
  assert.equal(await stock('choc'),5);
});

test('cross-origin writes and malformed requests are blocked',async()=>{
  const admin=await staff();
  assert.equal((await admin.request('inventory',{cookie_id:'choc',quantity:99},{origin:'https://unrelated.example'})).status,403);
  const response=await fetch(`${stack.base}/api/seatspot?action=order`,{method:'POST',headers:{Origin:stack.base,'Content-Type':'text/plain'},body:'{}'});
  assert.equal(response.status,415);assert.equal(await stock('choc'),5);
  const noOrigin=await fetch(`${stack.base}/api/seatspot?action=order`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  assert.equal(noOrigin.status,403);
});

test('expired or absent sessions cannot order until inventory establishes a valid session',async()=>{
  assert.equal((await client().request('order',{cookie_id:'choc'})).data.error.code,'SESSION_REQUIRED');
  const c=await customer();const token=c.jar.get('seatspot_session');
  await stack.sql("update public.cookie_sessions set expires_at=now()-interval '1 second'");
  assert.equal((await c.request('order',{cookie_id:'choc'})).status,409);
  assert.equal((await c.request()).status,200);assert.notEqual(c.jar.get('seatspot_session'),token);
});

test('a failed order insert rolls back the stock decrement',async()=>{
  const c=await customer();
  await stack.sql("alter table public.cookie_orders add constraint test_reject_insert check (cookie_flavor <> 'Chocolate') not valid");
  try{assert.equal((await c.request('order',{cookie_id:'choc'})).status,409);assert.equal(await stock('choc'),5)}
  finally{await stack.sql('alter table public.cookie_orders drop constraint test_reject_insert')}
  assert.equal(Number(await stack.sql('select count(*) from public.cookie_orders')),0);
});

test('rerunning setup preserves stock, orders, and staff; static output excludes secrets/API source',async()=>{
  const c=await customer();await c.request('order',{cookie_id:'choc'});
  await stack.sql(await readFile(new URL('../supabase/setup.sql',import.meta.url),'utf8'));
  assert.equal(await stock('choc'),4);assert.equal(Number(await stack.sql('select count(*) from public.cookie_orders')),1);
  for(const name of ['/.env.local','/server/handler.mjs','/supabase/setup.sql','/.git/config'])assert.equal((await fetch(stack.base+name)).status,404);
  for(const name of ['/','/admin','/assets/customer-orders.js','/assets/admin.js']){
    const response=await fetch(stack.base+name);assert.equal(response.status,200);assert(!(await response.text()).includes(stack.serviceToken));
  }
});

test('existing inventory and orders display renamed flavors before a database migration',async()=>{
  // Deliberate legacy fixtures: deployed databases may still store the old names.
  const names={choc:'Chocolate',matcha:'Original',red:'Red Velvet'};
  await stack.sql("update public.cookie_inventory set flavor=case id when 'choc' then 'Chocolate Chip' when 'matcha' then 'Matcha' else 'Red Velvet' end");
  try{
    const admin=await staff();
    for(const [id,name] of Object.entries(names)){
      const c=await customer();
      const placed=await c.request('order',{cookie_id:id,table_id:'B3'});
      assert.equal(placed.data.order.cookie_flavor,name);
      assert.equal((await c.request()).data.order.cookie_flavor,name);
      assert.equal(placed.data.inventory.find(item=>item.id===id).flavor,name);
    }
    const snapshot=(await admin.request('staff-state')).data;
    for(const item of snapshot.inventory)assert.equal(item.flavor,names[item.id]);
    for(const order of snapshot.orders)assert.equal(order.cookie_flavor,names[order.cookie_id]);
    const adjusted=await admin.request('inventory',{cookie_id:'matcha',adjustment:1});
    assert.equal(adjusted.data.inventory.flavor,'Original');
  }finally{
    await stack.sql(await readFile(new URL('../supabase/rename-cookie-flavors.sql',import.meta.url),'utf8'));
  }
});

test('name migration is repeatable and preserves stock, order data, and session allowance',async()=>{
  const c=await customer();const placed=(await c.request('order',{cookie_id:'matcha',table_id:'B3'})).data.order;
  await stack.sql("update public.cookie_inventory set flavor='Legacy inventory' where id='matcha'; update public.cookie_orders set cookie_flavor='Legacy order',status='Preparing'");
  const snapshot=async()=>JSON.parse(await stack.sql("select json_build_object('inventory',(select json_agg(to_jsonb(i)-'flavor'-'updated_at' order by id) from public.cookie_inventory i),'orders',(select json_agg(to_jsonb(o)-'cookie_flavor'-'updated_at' order by id) from public.cookie_orders o),'sessions',(select json_agg(s order by session_hash) from public.cookie_sessions s))"));
  const before=await snapshot();
  const migration=await readFile(new URL('../supabase/rename-cookie-flavors.sql',import.meta.url),'utf8');
  await stack.sql(migration);await stack.sql(migration);
  assert.deepEqual(await snapshot(),before);
  assert.equal(await stack.sql("select flavor from public.cookie_inventory where id='matcha'"),'Original');
  assert.equal(await stack.sql('select cookie_flavor from public.cookie_orders'),'Original');
  const retry=(await c.request('order',{cookie_id:'choc'})).data;
  assert.equal(retry.order.id,placed.id);assert.equal(retry.order.status,'Preparing');assert.equal(retry.already_ordered,true);
  assert.equal(await stock('matcha'),4);assert.equal(await stock('choc'),5);
});

test('a name is required before ordering and is saved on the existing anonymous session',async()=>{
  const c=client();const initial=await c.request();const token=c.jar.get('seatspot_session');
  assert.equal(initial.data.customer_name,null);
  assert.equal((await c.request('order',{cookie_id:'choc',customer_name:'Forged'})).data.error.code,'NAME_REQUIRED');
  assert.equal(await stock('choc'),5);
  const saved=await c.request('welcome',{customer_name:'  Alyssa  '});
  assert.equal(saved.data.customer_name,'Alyssa');assert.equal(c.jar.get('seatspot_session'),token);
  assert.equal((await c.request()).data.customer_name,'Alyssa');
  assert.equal((await c.request('welcome',{customer_name:'Different name'})).data.customer_name,'Alyssa');
  const result=await c.request('order',{cookie_id:'choc',table_id:'B3',customer_name:'Forged'});
  assert.equal(result.data.order.customer_name,'Alyssa');assert.equal(result.data.customer_name,'Alyssa');
  assert.equal(result.data.order.table_id,'B3');assert.equal(result.data.order.quantity,1);
  assert.equal(result.data.order.status,'New');assert(result.data.order.created_at);
  assert.equal(await stack.sql('select customer_name from public.cookie_orders'),'Alyssa');
  assert.equal((await c.request('order',{cookie_id:'red'})).data.order.id,result.data.order.id);
  const list=(await (await staff()).request('staff-state')).data.orders;
  assert.equal(list[0].customer_name,'Alyssa');assert.equal(await stock('red'),5);
});

test('name validation rejects blank, long, malformed and control-character names',async()=>{
  const c=client();await c.request();
  for(const customer_name of ['', '   ', 'a'.repeat(31), 'A\nB', 'A\0B', 42, null, {}]){
    const result=await c.request('welcome',{customer_name});
    assert.equal(result.status,400);assert.equal(result.data.error.code,'INVALID_NAME');
  }
  const result=await c.request('welcome',{customer_name:'ก'.repeat(30)});
  assert.equal(result.status,200);assert.equal(result.data.customer_name.length,30);
  assert.equal(Number(await stack.sql('select count(*) from public.cookie_orders')),0);
});

test('session expiry clears the name without exposing names from another session',async()=>{
  const a=await customer(),b=client();await b.request();
  assert.equal((await b.request()).data.customer_name,null);
  await stack.sql("update public.cookie_sessions set expires_at=now()-interval '1 second'");
  assert.equal((await a.request('welcome',{customer_name:'Alyssa'})).status,409);
  const fresh=await a.request();assert.equal(fresh.data.customer_name,null);assert.equal(fresh.data.order,null);
});

test('customer-name migration upgrades existing data without resets and remains compatible with old ordering',async()=>{
  const c=await customer();const ordered=(await c.request('order',{cookie_id:'red',table_id:'B12'})).data.order;
  await stack.sql('drop function public.place_named_cookie_order(text,text,text); drop function public.set_customer_name(text,text); alter table public.cookie_sessions drop column customer_name; alter table public.cookie_orders drop column customer_name');
  const snapshot=async()=>JSON.parse(await stack.sql("select json_build_object('inventory',(select json_agg(i order by id) from public.cookie_inventory i),'orders',(select json_agg(to_jsonb(o)-'customer_name' order by id) from public.cookie_orders o),'sessions',(select json_agg(to_jsonb(s)-'customer_name' order by session_hash) from public.cookie_sessions s))"));
  const before=await snapshot();
  const migration=await readFile(new URL('../supabase/add-customer-names.sql',import.meta.url),'utf8');
  await stack.sql(migration);await stack.sql(migration);
  assert.deepEqual(await snapshot(),before);
  assert.equal((await c.request()).data.order.customer_name,null);
  await c.request('welcome',{customer_name:'Alyssa'});
  const retry=(await c.request('order',{cookie_id:'choc'})).data;
  assert.equal(retry.order.id,ordered.id);assert.equal(retry.already_ordered,true);
  assert.equal(retry.order.customer_name,null);assert.equal(await stock('choc'),5);assert.equal(await stock('red'),4);
  // The old deployed API can continue using its existing RPC during rollout.
  const old=client();await old.request();const hash=createHash('sha256').update(old.jar.get('seatspot_session')).digest('hex');
  const response=await fetch(stack.restBase+'/rpc/place_cookie_order',{method:'POST',headers:{Authorization:`Bearer ${stack.serviceToken}`,'Content-Type':'application/json'},body:JSON.stringify({p_session_hash:hash,p_cookie_id:'choc'})});
  assert.equal(response.status,200);
});
