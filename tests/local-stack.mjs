// Isolated test-only PostgreSQL + PostgREST. No live Supabase project is used.
import { execFile, spawn } from 'node:child_process';
import { promisify } from 'node:util';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { randomBytes, createHmac, timingSafeEqual } from 'node:crypto';
import { pathToFileURL } from 'node:url';

const exec = promisify(execFile);
export const STAFF = { id:'11111111-1111-4111-8111-111111111111',email:'staff@example.test',password:'test-only-staff-password' };
export const NONSTAFF = { id:'22222222-2222-4222-8222-222222222222',email:'visitor@example.test',password:'test-only-visitor-password' };
const pause = ms => new Promise(resolve=>setTimeout(resolve,ms));

export async function startStack() {
  const suffix=randomBytes(5).toString('hex');
  const network=`seatspot-test-${suffix}`;
  const db=`seatspot-db-${suffix}`,rest=`seatspot-rest-${suffix}`;
  const secret=randomBytes(32).toString('hex');
  let fixture,dev;
  const docker=(...args)=>exec('docker',args,{maxBuffer:4*1024*1024});
  const sql=async query=>(await docker('exec',db,'psql','-U','postgres','-v','ON_ERROR_STOP=1','-At','-c',query)).stdout.trim();
  const token=(role,sub=STAFF.id,expires=3600)=>{
    const encode=value=>Buffer.from(JSON.stringify(value)).toString('base64url');
    const value=`${encode({alg:'HS256',typ:'JWT'})}.${encode({role,sub,exp:Math.floor(Date.now()/1000)+expires})}`;
    return `${value}.${createHmac('sha256',secret).update(value).digest('base64url')}`;
  };
  const serviceToken=token('service_role'),anonToken=token('anon');
  const reset=()=>sql(`truncate public.cookie_orders, public.cookie_sessions;
    update public.cookie_inventory set quantity_remaining=5, active=true;
    insert into public.staff_members(user_id) values('${STAFF.id}') on conflict do nothing;`);
  async function stop(){
    if(dev&&dev.exitCode===null){const exited=new Promise(resolve=>dev.once('exit',resolve));dev.kill('SIGTERM');await exited;}
    if(fixture) await new Promise(resolve=>fixture.close(resolve));
    await docker('stop',rest).catch(()=>{});
    await docker('stop',db).catch(()=>{});
    await docker('network','rm',network).catch(()=>{});
  }
  try{
    await docker('network','create',network);
    await docker('run','--rm','-d','--name',db,'--network',network,'--network-alias','db',
      '-e','POSTGRES_PASSWORD=seatspot-local-test-only','postgres:17-alpine');
    for(let attempt=0;;attempt++){
      try{await docker('exec',db,'pg_isready','-h','127.0.0.1','-U','postgres');await sql('select 1');break}catch(error){if(attempt>80)throw error;await pause(150)}
    }
    await sql(`create role anon nologin;
      create role authenticated nologin;
      create role service_role nologin bypassrls;
      create role authenticator login password 'seatspot-local-test-only' noinherit;
      grant anon,authenticated,service_role to authenticator;
      create schema auth;
      create table auth.users(id uuid primary key,email text);
      insert into auth.users values('${STAFF.id}','${STAFF.email}'),('${NONSTAFF.id}','${NONSTAFF.email}');`);
    await sql(await readFile(new URL('../supabase/setup.sql',import.meta.url),'utf8'));
    await reset();
    await docker('run','--rm','-d','--name',rest,'--network',network,'-p','127.0.0.1::3000',
      '-e','PGRST_DB_URI=postgres://authenticator:seatspot-local-test-only@db:5432/postgres',
      '-e','PGRST_DB_SCHEMAS=public','-e','PGRST_DB_ANON_ROLE=anon',
      '-e',`PGRST_JWT_SECRET=${secret}`,'postgrest/postgrest:v13.0.7');
    const port=(await docker('port',rest,'3000/tcp')).stdout.trim().split(':').at(-1);
    const restBase=`http://127.0.0.1:${port}`;
    for(let attempt=0;;attempt++){
      try{const response=await fetch(restBase);if(!response.ok)throw new Error('PostgREST starting');break}
      catch(error){if(attempt>80)throw error;await pause(150)}
    }
    fixture=createServer(async(req,res)=>{
      res.setHeader('Content-Type','application/json');
      try{
        const url=new URL(req.url,'http://localhost');
        const chunks=[];for await(const chunk of req)chunks.push(chunk);
        const raw=Buffer.concat(chunks).toString();
        if(url.pathname==='/__test__/reset'){
          await reset();res.end(JSON.stringify({ok:true}));return;
        }
        if(url.pathname==='/__test__/stock'){
          const b=JSON.parse(raw);
          if(!['choc','matcha','red'].includes(b.cookie_id)||!Number.isInteger(b.quantity)||b.quantity<0)throw new Error('Bad fixture');
          await sql(`update public.cookie_inventory set quantity_remaining=${b.quantity},active=${b.active!==false} where id='${b.cookie_id}'`);
          res.end(JSON.stringify({ok:true}));return;
        }
        if(url.pathname==='/__test__/status'){
          const b=JSON.parse(raw);
          if(!['New','Preparing','Ready'].includes(b.status))throw new Error('Bad fixture');
          await sql(`update public.cookie_orders set status='${b.status}'`);
          res.end(JSON.stringify({ok:true}));return;
        }
        if(url.pathname.startsWith('/rest/v1/')){
          const response=await fetch(restBase+url.pathname.slice('/rest/v1'.length)+url.search,{
            method:req.method,headers:{Authorization:req.headers.authorization||`Bearer ${anonToken}`,'Content-Type':'application/json',Prefer:req.headers.prefer||''},
            ...(raw?{body:raw}:{})
          });
          res.statusCode=response.status;res.end(await response.text());return;
        }
        if(url.pathname==='/auth/v1/token'){
          const body=JSON.parse(raw);const user=[STAFF,NONSTAFF].find(user=>user.email===body.email&&user.password===body.password);
          if(!user){res.statusCode=400;res.end(JSON.stringify({error:'invalid_grant'}));return;}
          res.end(JSON.stringify({access_token:token('authenticated',user.id),expires_in:3600,user:{id:user.id,email:user.email}}));return;
        }
        if(url.pathname==='/auth/v1/user'){
          const jwt=(req.headers.authorization||'').replace(/^Bearer /,'');
          const [header,payload,signature]=jwt.split('.');
          const expected=createHmac('sha256',secret).update(`${header}.${payload}`).digest();
          const actual=Buffer.from(signature||'','base64url');
          const claims=JSON.parse(Buffer.from(payload||'','base64url'));
          const user=[STAFF,NONSTAFF].find(user=>user.id===claims.sub);
          if(actual.length!==expected.length||!timingSafeEqual(actual,expected)||claims.exp<=Date.now()/1000||!user){res.statusCode=401;res.end('{}');return;}
          res.end(JSON.stringify({id:user.id,email:user.email}));return;
        }
        res.statusCode=404;res.end('{}');
      }catch{res.statusCode=400;res.end('{}')}
    });
    await new Promise(resolve=>fixture.listen(0,'127.0.0.1',resolve));
    const supabaseBase=`http://127.0.0.1:${fixture.address().port}`;
    dev=spawn(process.execPath,['scripts/dev-server.mjs'],{
      cwd:new URL('..',import.meta.url),env:{...process.env,SUPABASE_URL:supabaseBase,SUPABASE_SERVICE_ROLE_KEY:serviceToken,PORT:'0',HOST:'127.0.0.1'},stdio:['ignore','pipe','pipe']
    });
    const appPort=await new Promise((resolve,reject)=>{
      let output='';dev.stdout.on('data',chunk=>{output+=chunk;const match=output.match(/listening on port (\d+)/);if(match)resolve(match[1])});
      dev.once('exit',code=>reject(new Error(`Test app exited ${code}`)));
    });
    return {base:`http://127.0.0.1:${appPort}`,supabaseBase,restBase,serviceToken,anonToken,token,sql,reset,stop};
  }catch(error){await stop();throw error}
}

if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
  const stack=await startStack();
  console.log(JSON.stringify({base:stack.base,fixture:stack.supabaseBase}));
  for(const signal of ['SIGINT','SIGTERM'])process.once(signal,async()=>{await stack.stop();process.exit(0)});
}
