# SeatSpot Supabase setup

Complete steps 1–4 before the first backend deployment. Once Supabase setup is complete and deployment is authorized, pushing to the connected GitHub branch triggers Vercel. Never paste database passwords, service-role keys, or staff passwords into chat or GitHub.

## Existing project: add the visitor-name feature before deploying

Run the **complete** contents of [`supabase/add-customer-names.sql`](supabase/add-customer-names.sql) in a new Supabase SQL Editor query. The last line is `commit;`. Run the whole query without selecting only part of it. This migration is additive and repeatable; it does not delete or reset inventory, orders, sessions, or staff.

It adds nullable `customer_name` fields to `cookie_sessions` and `cookie_orders`, plus two service-only functions: `set_customer_name` and `place_named_cookie_order`. Names are required for new orders through the updated API. The named-order function reuses the existing atomic ordering function inside the same database transaction, preserving stock checks, one-cookie enforcement, retries, and rollback. The old ordering function stays available to the previously deployed server during the migration, so SQL can be applied before releasing the new code.

After the migration succeeds, confirm setup is complete before pushing/deploying this feature. There are no new environment variables, staff-account changes, or public database policies to configure. The SQL is also included in `setup.sql` for future setups or reruns.

Customers enter a trimmed name of 1–30 characters before entering the site. The name is stored against the existing hashed anonymous session, never used as the session identity. It survives navigation, refresh, Leave Table, Reset, and reopening the site with the same active 24-hour cookie. The first name saved for a session stays fixed, including across tabs and retries. An optional same-tab `sessionStorage` cache uses the same expiry for continuity during connection failures; the server is authoritative, and persistence still works if browser storage is unavailable. An expired or new anonymous session asks for a name again. A name never resets the cookie allowance.

New orders snapshot the session name alongside table, flavor, quantity, timestamp and status. Existing orders keep their original data: an unknown historical name remains null and displays **Guest** in staff view. Missing table numbers display **—**. The dashboard shows customer name, table, cookie, quantity, time ordered and status; UUIDs remain internal for status updates and are not shown as staff labels. Names render as literal text, with server/database validation and escaped customer summaries.

## 1. Create the Supabase project

Sign in at https://supabase.com/dashboard and create a project (the Free plan works for this exhibition). Choose a database password and keep it in your password manager. Wait until the project is ready. A dedicated SeatSpot project avoids conflicts with existing database objects.

## 2. Run the database setup

Open **SQL Editor → New query**. Copy the complete contents of [`supabase/setup.sql`](supabase/setup.sql), then click **Run**. This creates everything required; no separate table creation or Realtime configuration is needed.

| Table | Purpose |
| --- | --- |
| `cookie_inventory` | Three flavors, quantity remaining, active flag, automatically derived sold-out flag, updated timestamp |
| `cookie_orders` | Internal UUID order ID, customer name, flavor, quantity fixed to 1, optional table ID, timestamp, New/Preparing/Ready status |
| `cookie_sessions` | Hashed anonymous session identity, customer name, creation and expiry times; unique order per session |
| `staff_members` | Allowlist of Supabase Auth user IDs allowed to manage stock and orders |

The SQL also creates the atomic ordering and staff update functions, enables row-level security, and removes customer access to database writes. Rerunning the file preserves existing orders and quantities. Initial stock is **zero** for every flavor; enter the actual quantities in `/admin` after signing in. Zero stock displays **Sold out**. An inactive flavor with stock displays **Unavailable**.

## 3. Create an authorized staff account

In Supabase **Authentication → Users → Add user → Create new user**, create a staff email/password account. Enable **Auto Confirm User** if offered so that email confirmation is not pending. Use a strong password. Copy that user's UUID from the Users page.

Run this in SQL Editor, replacing the example with the actual UUID:

```sql
insert into public.staff_members (user_id)
values ('REPLACE-WITH-STAFF-USER-UUID'::uuid)
on conflict (user_id) do nothing;
```

A normal Supabase Auth user without this allowlist row cannot enter the dashboard or change stock. Repeat for additional staff. There is no public staff registration page. To revoke staff access:

```sql
delete from public.staff_members
where user_id = 'REPLACE-WITH-STAFF-USER-UUID'::uuid;
```

The app checks membership on every staff request; revocation does not require waiting for the staff cookie to expire. Staff sign in at `/admin` and sign in again after their one-hour session expires. Password sign-in does not need an OAuth redirect URL. Keep Supabase Auth's normal rate limits enabled.

## 4. Configure the two server environment variables

Find the project's URL in **Project Settings → Data API** (or the project's Connect dialog). Find the legacy **service_role** key in **Project Settings → API Keys → Legacy anon, service_role API keys**. Use the `service_role` JWT for this implementation, not the `anon`/publishable key, database password, or a new `sb_secret_...` key.

| Variable | Value |
| --- | --- |
| `SUPABASE_URL` | `https://YOUR-PROJECT.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | The project's legacy `service_role` key; secret, server only |

Local configuration is optional: your Mac does not need `.env.local` for the Vercel deployment. For local use, copy `.env.example` to **`.env.local`** in the repository root and fill in both values. `.env.local` is ignored by Git. Use Node.js 22 and run:

```sh
npm run dev
```

Open http://127.0.0.1:4173/admin, sign in using the staff account, and set the actual available quantities. Then open http://127.0.0.1:4173/ as a customer. The developer server loads `.env.local` automatically. Restart it after changing those variables. There are no npm dependencies to install.

For a Vercel release, open the existing SeatSpot project → **Settings → Environment Variables** and add the same two names and values to **Production**. Add them to Preview only if you intend previews to share this same inventory; otherwise use a separate Supabase test project for Preview. These variables must remain server-only: do not use a `PUBLIC_`, `NEXT_PUBLIC_`, or `VITE_` prefix and do not put them in HTML or browser JavaScript. The build copies static assets only; API credentials are read at server runtime.

After the SQL, staff allowlist, and Production environment variables are configured, push the authorized changes to the connected repository to trigger Vercel. Adding variables to Vercel alone does not change an existing deployment; the new deployment must finish before testing the backend on the public site. The checked-in configuration builds `public/`, runs `/api/seatspot` as a Node server function, and serves the staff page at `/admin`. Use Node.js 22 in Vercel's Build settings if an older project override exists. Keep the current HTTPS domain so existing physical QR links continue to work.

## 5. Check the connected app before the exhibition

1. In `/admin`, set Chocolate stock to 1 and give the other two flavors their actual quantities. Verify active flags are enabled for flavors being offered.
2. Open the customer site in two separate browser profiles or devices. Both should display the same counts, updated automatically every three seconds while visible.
3. Enter a name on the welcome screen, then claim B3 through `?table=B3` or the real QR flow. Select Chocolate and press **Place order**. Confirm flavor and Table B3 appear; staff should see one New order. The other customer should see 0 remaining / Sold out and a disabled Chocolate button.
4. Have the second customer order another flavor without claiming a table. Staff should see **—** for the table. The app allows ordering without table check-in.
5. Move an order through **Preparing** and **Ready** in `/admin`. The customer progress display should follow the actual staff status. **Confirm pickup** acknowledges collection locally; it does not restore the one-cookie allowance or remove the order.
6. Refresh, leave the table, or use Reset prototype. The original order and ordering lock should remain for that session. Test Home scanning, map QR verification/mismatch, filters, and leaving tables as usual.
7. Restore actual physical stock through `/admin` after testing. Test orders remain in the dashboard; avoid deleting real orders or resetting inventory during the event.

## Behavior and security

- Stock and orders live in Supabase and are shared across browsers/devices. Customers and staff poll every three seconds; a temporarily unavailable service pauses ordering instead of inventing demo stock. No Supabase Realtime subscription is needed.
- A single PostgreSQL transaction locks the session, checks stock and active status, decrements by one, and inserts an order. A unique session constraint and nonnegative stock constraint provide additional protection. Failed inserts roll back stock. Simultaneous orders cannot oversell. Retrying the same session returns the original order without another decrement, even if a different flavor was sent.
- Customer identity is an opaque, HttpOnly, SameSite cookie, Secure on HTTPS, with a fixed 24-hour session. The database stores only its SHA-256 hash. Refresh, navigation, Leave Table, Reset, and pickup preserve the allowance. A fresh browser profile, cleared cookies, or an expired session creates a new anonymous session; this is one cookie **per session**, not proof of one cookie per person across devices. Customer responses include only their own order.
- Customer inventory is read-only. Every staff request validates a Supabase Auth access token and allowlist membership. Staff tokens are HttpOnly cookies, never browser localStorage. RLS and revoked grants block direct anonymous/authenticated database reads and writes; only the server's service role can access these tables and the narrowly granted mutation functions. Do not add public write policies or expose the service key.
- Table availability/claiming remains the original local SeatSpot prototype. This change shares cookie inventory and orders; it does not introduce shared table reservations. The order stores a snapshot of the checked-in table ID, or null if unavailable. Payments are not processed; displayed THB prices remain prototype information.
- The backend requires Vercel functions (or the included local Node server). A plain static host such as GitHub Pages cannot run this ordering API. The old Pages workflow is manual-only for a visual preview.

## Developer verification

```sh
npm run build
npm test
python3 -m unittest discover -s tests -v
```

The database/API tests and backend browser tests require Docker with `postgres:17-alpine` and `postgrest/postgrest:v13.0.7`; Python tests also require Playwright and Chromium. Tests launch isolated disposable local databases and do not touch your Supabase project or use `.env.local` credentials. Local Supabase Auth is a test fixture; the production Auth connection must be checked after you finish setup. Camera tests exercise the actual video/canvas/jsQR decoder in Chromium using QR video fixtures. Physical iPhone Safari and Android Chrome testing is still recommended for camera permission behavior.

## Flavor names and existing installations

Stable database IDs are unchanged: `matcha` displays **Original**, `choc` displays **Chocolate**, and `red` displays **Red Velvet**. The API uses these names for inventory, order confirmations, and the staff dashboard, including records created before the rename. No migration is needed for the website to display the new names.

To synchronize the stored inventory and order flavor text too, run the complete contents of [`supabase/rename-cookie-flavors.sql`](supabase/rename-cookie-flavors.sql) once in Supabase SQL Editor. It changes names only; stock, IDs, quantities, statuses, sessions, and the one-cookie rule are preserved. No SQL function or environment-variable changes are needed. New setups seed the new names automatically; rerunning `setup.sql` also updates inventory names while preserving quantities.
