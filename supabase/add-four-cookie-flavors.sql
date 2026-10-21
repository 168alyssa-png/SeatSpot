-- Existing three-flavor SeatSpot: matcha currently means Original.
-- Run the ENTIRE file before deploying the four-flavor application.
-- Preserves existing stock, orders, names, sessions, and one-cookie allowances.
begin;

lock table public.cookie_sessions, public.cookie_inventory, public.cookie_orders
  in access exclusive mode;

alter table public.cookie_inventory
  drop constraint if exists cookie_inventory_id_check;
alter table public.cookie_inventory
  add constraint cookie_inventory_id_check
  check (id in ('original', 'choc', 'matcha', 'red'));

-- Cascade the ID rename to existing orders without removing their references.
alter table public.cookie_orders
  drop constraint if exists cookie_orders_cookie_id_fkey;
alter table public.cookie_orders
  add constraint cookie_orders_cookie_id_fkey
  foreign key (cookie_id) references public.cookie_inventory(id)
  on update cascade;

do $$
begin
  -- Presence of original makes reruns safe: never move the NEW Matcha stock.
  if not exists (select 1 from public.cookie_inventory where id = 'original') then
    if not exists (select 1 from public.cookie_inventory where id = 'matcha') then
      raise exception 'Original inventory was not found. No changes committed.';
    end if;
    update public.cookie_inventory
      set id = 'original', flavor = 'Original'
      where id = 'matcha';
    update public.cookie_orders
      set cookie_flavor = 'Original'
      where cookie_id = 'original' and cookie_flavor is distinct from 'Original';
  end if;
end;
$$;

-- This is a NEW flavor, so its initial stock is zero. Existing rows are untouched.
insert into public.cookie_inventory (id, flavor, quantity_remaining, active)
values ('matcha', 'Matcha', 0, true)
on conflict (id) do nothing;

-- Synchronize display text only; never replace quantities or active flags.
update public.cookie_inventory
set flavor = case id
  when 'original' then 'Original'
  when 'choc' then 'Chocolate'
  when 'matcha' then 'Matcha'
  when 'red' then 'Red Velvet'
end
where flavor is distinct from case id
  when 'original' then 'Original'
  when 'choc' then 'Chocolate'
  when 'matcha' then 'Matcha'
  when 'red' then 'Red Velvet'
end;

notify pgrst, 'reload schema';
commit;
