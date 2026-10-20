-- Run the ENTIRE file in Supabase SQL Editor before deploying the name feature.
-- Additive and repeatable: no inventory, orders, sessions, or staff are reset.
begin;

alter table public.cookie_sessions add column if not exists customer_name text
  check (customer_name is null or (
    char_length(customer_name) between 1 and 30
    and char_length(btrim(customer_name)) > 0
    and customer_name !~ '[[:cntrl:]]'
  ));
alter table public.cookie_orders add column if not exists customer_name text
  check (customer_name is null or (
    char_length(customer_name) between 1 and 30
    and char_length(btrim(customer_name)) > 0
    and customer_name !~ '[[:cntrl:]]'
  ));

create or replace function public.set_customer_name(p_session_hash text, p_customer_name text)
returns text language plpgsql security definer set search_path = '' as $$
declare
  v_session public.cookie_sessions%rowtype;
  v_name text := btrim(p_customer_name);
begin
  if v_name is null or char_length(v_name) not between 1 and 30
     or v_name ~ '[[:cntrl:]]' then
    raise exception using errcode = 'P0001', message = 'INVALID_NAME';
  end if;
  select * into v_session from public.cookie_sessions
    where session_hash = p_session_hash for update;
  if not found or v_session.expires_at <= now() then
    raise exception using errcode = 'P0001', message = 'SESSION_EXPIRED';
  end if;
  -- Keep the first name chosen for this session, including across tabs/retries.
  update public.cookie_sessions
    set customer_name = coalesce(customer_name, v_name)
    where session_hash = p_session_hash
    returning customer_name into v_name;
  return v_name;
end;
$$;

create or replace function public.place_named_cookie_order(
  p_session_hash text, p_cookie_id text, p_table_id text default null
)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_session public.cookie_sessions%rowtype;
  v_result jsonb;
  v_order public.cookie_orders%rowtype;
begin
  select * into v_session from public.cookie_sessions
    where session_hash = p_session_hash for update;
  if not found or v_session.expires_at <= now() then
    raise exception using errcode = 'P0001', message = 'SESSION_EXPIRED';
  end if;
  if v_session.customer_name is null then
    raise exception using errcode = 'P0001', message = 'NAME_REQUIRED';
  end if;
  -- Reuse the existing atomic stock decrement, unique session and retry logic.
  -- This function and the original function run in the SAME transaction.
  v_result := public.place_cookie_order(p_session_hash, p_cookie_id, p_table_id);
  if not (v_result->>'already_ordered')::boolean then
    update public.cookie_orders set customer_name = v_session.customer_name
      where id = (v_result->'order'->>'id')::uuid;
  end if;
  select * into v_order from public.cookie_orders
    where id = (v_result->'order'->>'id')::uuid;
  return jsonb_build_object('order', to_jsonb(v_order) - 'session_hash',
    'already_ordered', (v_result->>'already_ordered')::boolean);
end;
$$;

revoke all on function public.set_customer_name(text, text) from public, anon, authenticated;
revoke all on function public.place_named_cookie_order(text, text, text) from public, anon, authenticated;
grant execute on function public.set_customer_name(text, text) to service_role;
grant execute on function public.place_named_cookie_order(text, text, text) to service_role;

-- Make new fields/functions available to the Supabase REST API.
notify pgrst, 'reload schema';
commit;
