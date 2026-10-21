-- Four-flavor installations only (apply add-four-cookie-flavors.sql first): synchronize stored names without changing IDs,
-- stock quantities, active flags, ordering allowances, or order statuses.
-- Safe to rerun. The API already displays these names using the stable IDs.
begin;
do $$
begin
  if not exists (select 1 from public.cookie_inventory where id = 'original') then
    raise exception 'Run supabase/add-four-cookie-flavors.sql first.';
  end if;
end;
$$;

update public.cookie_inventory
set flavor = case id
  when 'original' then 'Original'
  when 'matcha' then 'Matcha'
  when 'choc' then 'Chocolate'
  when 'red' then 'Red Velvet'
end
where id in ('original', 'matcha', 'choc', 'red')
  and flavor is distinct from case id
    when 'original' then 'Original'
  when 'matcha' then 'Matcha'
    when 'choc' then 'Chocolate'
    when 'red' then 'Red Velvet'
  end;

update public.cookie_orders
set cookie_flavor = case cookie_id
  when 'original' then 'Original'
  when 'matcha' then 'Matcha'
  when 'choc' then 'Chocolate'
  when 'red' then 'Red Velvet'
end
where cookie_id in ('original', 'matcha', 'choc', 'red')
  and cookie_flavor is distinct from case cookie_id
    when 'original' then 'Original'
  when 'matcha' then 'Matcha'
    when 'choc' then 'Chocolate'
    when 'red' then 'Red Velvet'
  end;

commit;
