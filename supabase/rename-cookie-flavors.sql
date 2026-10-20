-- Existing installations: synchronize stored names without changing IDs,
-- stock quantities, active flags, ordering allowances, or order statuses.
-- Safe to rerun. The API already displays these names using the stable IDs.
begin;

update public.cookie_inventory
set flavor = case id
  when 'matcha' then 'Original'
  when 'choc' then 'Chocolate'
  when 'red' then 'Red Velvet'
end
where id in ('matcha', 'choc', 'red')
  and flavor is distinct from case id
    when 'matcha' then 'Original'
    when 'choc' then 'Chocolate'
    when 'red' then 'Red Velvet'
  end;

update public.cookie_orders
set cookie_flavor = case cookie_id
  when 'matcha' then 'Original'
  when 'choc' then 'Chocolate'
  when 'red' then 'Red Velvet'
end
where cookie_id in ('matcha', 'choc', 'red')
  and cookie_flavor is distinct from case cookie_id
    when 'matcha' then 'Original'
    when 'choc' then 'Chocolate'
    when 'red' then 'Red Velvet'
  end;

commit;
