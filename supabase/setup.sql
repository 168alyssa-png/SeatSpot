-- SeatSpot: run this entire file once in the Supabase SQL Editor.
-- Safe to rerun: existing stock and orders are NOT reset by the seed inserts.
begin;

create table if not exists public.cookie_inventory (
  id text primary key check (id in ('choc', 'matcha', 'red')),
  flavor text not null unique,
  quantity_remaining integer not null default 0 check (quantity_remaining between 0 and 1000000),
  active boolean not null default true,
  sold_out boolean generated always as (quantity_remaining = 0) stored,
  updated_at timestamptz not null default now()
);

-- Only a SHA-256 digest of the random HttpOnly session cookie is stored here.
create table if not exists public.cookie_sessions (
  session_hash text primary key check (session_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '24 hours')
);

create table if not exists public.cookie_orders (
  id uuid primary key default gen_random_uuid(),
  session_hash text not null unique references public.cookie_sessions(session_hash),
  cookie_id text not null references public.cookie_inventory(id),
  cookie_flavor text not null,
  quantity integer not null default 1 check (quantity = 1),
  table_id text check (table_id is null or table_id ~ '^[ABC]([1-9]|1[0-2])$'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  status text not null default 'New' check (status in ('New', 'Preparing', 'Ready'))
);
create index if not exists cookie_orders_created_idx on public.cookie_orders (created_at desc, id desc);

create table if not exists public.staff_members (
  user_id uuid primary key references auth.users(id) on delete cascade,
  created_at timestamptz not null default now()
);

insert into public.cookie_inventory (id, flavor, quantity_remaining, active) values
  ('choc', 'Chocolate Chip', 0, true),
  ('matcha', 'Matcha', 0, true),
  ('red', 'Red Velvet', 0, true)
on conflict (id) do nothing;

-- No public/client policies: all access goes through the same-origin server API.
alter table public.cookie_inventory enable row level security;
alter table public.cookie_sessions enable row level security;
alter table public.cookie_orders enable row level security;
alter table public.staff_members enable row level security;
revoke all on public.cookie_inventory, public.cookie_sessions, public.cookie_orders, public.staff_members
  from public, anon, authenticated, service_role;
grant usage on schema public to service_role;
grant select on public.cookie_inventory, public.cookie_sessions, public.cookie_orders, public.staff_members to service_role;
grant insert on public.cookie_sessions to service_role;

create or replace function public.seatspot_touch_updated_at()
returns trigger language plpgsql set search_path = '' as $$
begin
  new.updated_at := now();
  return new;
end;
$$;
drop trigger if exists seatspot_inventory_updated on public.cookie_inventory;
create trigger seatspot_inventory_updated before update on public.cookie_inventory
  for each row execute function public.seatspot_touch_updated_at();
drop trigger if exists seatspot_order_updated on public.cookie_orders;
create trigger seatspot_order_updated before update on public.cookie_orders
  for each row execute function public.seatspot_touch_updated_at();
revoke all on function public.seatspot_touch_updated_at() from public, anon, authenticated, service_role;

-- One RPC = one PostgreSQL transaction. Lock the session before the inventory
-- row so even simultaneous requests for DIFFERENT flavors can create only one order.
create or replace function public.place_cookie_order(p_session_hash text, p_cookie_id text, p_table_id text default null)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_session public.cookie_sessions%rowtype;
  v_cookie public.cookie_inventory%rowtype;
  v_order public.cookie_orders%rowtype;
begin
  select * into v_session from public.cookie_sessions
    where session_hash = p_session_hash for update;
  if not found or v_session.expires_at <= now() then
    raise exception using errcode = 'P0001', message = 'SESSION_EXPIRED';
  end if;
  select * into v_order from public.cookie_orders where session_hash = p_session_hash;
  if found then
    -- A retry after a lost HTTP response returns the original order, without
    -- another decrement. Never replace its flavor/table with the retry's data.
    return jsonb_build_object('order', to_jsonb(v_order) - 'session_hash', 'already_ordered', true);
  end if;
  if p_table_id is not null and p_table_id !~ '^[ABC]([1-9]|1[0-2])$' then
    raise exception using errcode = 'P0001', message = 'INVALID_TABLE';
  end if;
  update public.cookie_inventory
    set quantity_remaining = quantity_remaining - 1
    where id = p_cookie_id and active and quantity_remaining > 0
    returning * into v_cookie;
  if not found then
    raise exception using errcode = 'P0001', message = 'SOLD_OUT';
  end if;
  insert into public.cookie_orders (session_hash, cookie_id, cookie_flavor, table_id)
    values (p_session_hash, v_cookie.id, v_cookie.flavor, p_table_id)
    returning * into v_order;
  return jsonb_build_object('order', to_jsonb(v_order) - 'session_hash', 'already_ordered', false);
end;
$$;

create or replace function public.set_cookie_inventory(
  p_staff_id uuid, p_cookie_id text, p_quantity integer default null,
  p_adjustment integer default null, p_active boolean default null
)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare v_cookie public.cookie_inventory%rowtype;
begin
  if not exists (select 1 from public.staff_members where user_id = p_staff_id) then
    raise exception using errcode = '42501', message = 'STAFF_REQUIRED';
  end if;
  if (p_quantity is not null and p_adjustment is not null)
    or (p_quantity is null and p_adjustment is null and p_active is null) then
    raise exception using errcode = 'P0001', message = 'INVALID_STOCK_CHANGE';
  end if;
  update public.cookie_inventory set
    quantity_remaining = case when p_quantity is not null then p_quantity
      else quantity_remaining + coalesce(p_adjustment, 0) end,
    active = coalesce(p_active, active)
    where id = p_cookie_id returning * into v_cookie;
  if not found then raise exception using errcode = 'P0001', message = 'INVALID_COOKIE'; end if;
  return to_jsonb(v_cookie);
end;
$$;

create or replace function public.set_cookie_order_status(p_staff_id uuid, p_order_id uuid, p_status text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare v_order public.cookie_orders%rowtype;
begin
  if not exists (select 1 from public.staff_members where user_id = p_staff_id) then
    raise exception using errcode = '42501', message = 'STAFF_REQUIRED';
  end if;
  if p_status is null or p_status not in ('New', 'Preparing', 'Ready') then
    raise exception using errcode = 'P0001', message = 'INVALID_STATUS';
  end if;
  update public.cookie_orders set status = p_status where id = p_order_id returning * into v_order;
  if not found then raise exception using errcode = 'P0001', message = 'ORDER_NOT_FOUND'; end if;
  return to_jsonb(v_order) - 'session_hash';
end;
$$;

revoke all on function public.place_cookie_order(text, text, text) from public, anon, authenticated;
revoke all on function public.set_cookie_inventory(uuid, text, integer, integer, boolean) from public, anon, authenticated;
revoke all on function public.set_cookie_order_status(uuid, uuid, text) from public, anon, authenticated;
grant execute on function public.place_cookie_order(text, text, text) to service_role;
grant execute on function public.set_cookie_inventory(uuid, text, integer, integer, boolean) to service_role;
grant execute on function public.set_cookie_order_status(uuid, uuid, text) to service_role;
commit;
