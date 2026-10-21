# SeatSpot

The existing green-and-white SeatSpot prototype, with its responsive website layout, table map, QR camera scanner, filters, table claiming, and Cookie Corner. Cookie ordering now uses a shared Supabase database through a server-only Vercel API; `/admin` provides authenticated staff inventory and order management. The browser contains no database credentials.

Production address: [seatspot-zi36.vercel.app](https://seatspot-zi36.vercel.app/).

## Run locally

From this repository:

```sh
npm run dev
```

Use Node.js 22. Copy `.env.example` to `.env.local` and configure the two server values following [SUPABASE_SETUP.md](SUPABASE_SETUP.md). Open `http://127.0.0.1:4173/` in a browser; staff use `/admin`. Without backend configuration, ordering is safely paused while the map and scanner still work. Stop the server with Ctrl+C. In a cloud workspace, set `HOST=0.0.0.0` if its development tools require it. Camera access requires the public HTTPS site or a localhost development server; plain HTTP over a local network is insufficient.

## Table-specific QR links

A table's QR code should contain the final public HTTPS URL and its table ID, for example:

```text
https://seatspot-zi36.vercel.app/?table=B3
https://seatspot-zi36.vercel.app/?table=B12
```

Opening a table link selects that table, switches to the correct zone, opens its map, and shows a claim prompt. For an available table, press **Claim Table B3** (or the matching table ID) to check in, or **Not now** to keep browsing without claiming it. Occupied and clearing tables show their status with claiming disabled and a **View map** button. The live map has 36 tables, with 12 in each zone: A1–A12, B1–B12, and C1–C12. All IDs support table links (for example, `?table=B12`); lower-case IDs are accepted, and unknown IDs show a message without claiming anything. The same links work under a hosting subdirectory and after a refresh.

Generate a separate QR image for each full table URL. A QR printed for B3 should encode the complete URL above, not the bare table name. Visitors can scan it inside SeatSpot or use their phone's camera to open the table link directly. Both Home and the live map use the real camera scanner; the map checks that the QR matches the selected table.

## In-page camera scanner

1. On Home, tap **Scan table QR** and allow the browser to use the camera. SeatSpot requests the rear camera without microphone access and displays the live video inside its existing dialog.
2. Point the camera at a table QR. A known ID on the current site's origin or the production origin above is accepted; relative links such as `?table=B12` also work. Unrelated sites, missing or duplicate table parameters, and unknown IDs are rejected while scanning continues.
3. On detection, the camera stops, the correct zone and table are selected, and **Table B3 detected** appears with the normal claim prompt. Confirm the claim to continue ordering. Unavailable tables retain their existing restrictions, and a visitor must leave their current table before scanning another.

On the live map, select an available table and tap **Scan table QR**. The scanner remembers that selection throughout camera retries. A matching code stops the camera and shows **Table B3 verified ✓** with the existing claim prompt. A different valid table code stops the camera and explains, for example, **This QR belongs to Table A2, but you selected B3.** Neither table is claimed and the original selection stays unchanged. **Scan again** retries verification for B3; **View A2** opens A2 on the map without claiming it, respecting its occupied/clearing status. The Home scanner continues to detect any valid table without requiring a prior selection. The old simulated scan behavior has been removed.

**Cancel scanner**, Escape, clicking the dialog backdrop, or choosing **Choose table manually** releases the camera. It also stops when the page is hidden or left. A late camera-permission response after cancellation is released immediately. Permission denial, a missing/busy camera, unsupported browsers, and insecure HTTP show an explanatory message with retry and manual-selection options. If permission was previously denied, enable camera access for SeatSpot in the browser's site settings before retrying.

The local jsQR 1.4.0 library decodes frames entirely in the browser; there is no camera upload, CDN dependency, or reliance on `BarcodeDetector`. Video uses muted inline playback for iPhone Safari and Android Chrome. Keep `assets/` alongside `index.html` on any host; see `assets/README.md` for the decoder's provenance and license.

## Shared inventory and staff dashboard

Cookie inventory and orders now use Supabase through a server-side API. Flavors are Original (`original`), Chocolate (`choc`), Matcha (`matcha`), and Red Velvet (`red`). Existing installations must run [supabase/add-four-cookie-flavors.sql](supabase/add-four-cookie-flavors.sql) before deploying this version: it moves the former `matcha`/Original stock and linked orders to `original`, then adds a separate Matcha flavor with zero initial stock. It preserves all existing quantities, names, statuses, sessions and the one-cookie-total allowance. Visitors enter a name on a welcome screen before opening SeatSpot. The name is saved with their existing anonymous session and copied onto orders; staff see names instead of random IDs. Customers select one cookie flavor, see shared remaining stock, and place one order per 24-hour SeatSpot session. Stock decrements and order creation happen in one database transaction. Staff sign in at `/admin` to set or adjust inventory and change orders between New, Preparing, and Ready. Updates reach visible customer and staff pages automatically every three seconds.

Follow [SUPABASE_SETUP.md](SUPABASE_SETUP.md) for the exact SQL, staff account/allowlist, environment variables, security details, and exhibition checks. Start with [supabase/setup.sql](supabase/setup.sql). Existing installations must run [supabase/add-customer-names.sql](supabase/add-customer-names.sql) before deploying the welcome/name feature; this does not reset inventory. Configure Supabase and Vercel Production environment variables before the first backend release. After setup, an authorized push to the connected GitHub branch triggers the Vercel deployment. Local `.env.local` configuration is optional and is not required on your Mac for Vercel to work.

Stock and orders are shared; the existing table map and table-claim state remain the local interactive prototype. Refresh, Leave Table, Reset, and pickup confirmation do not unlock a second cookie. Clearing cookies or using another browser creates another anonymous session. This is a session allowance, not a cross-device identity check.

## Validation

```sh
npm run build
npm test
python3 -m unittest discover -s tests -v
```

API tests use real isolated PostgreSQL/PostgREST containers and require Docker. Browser tests require Python Playwright and Chromium. See the setup guide for coverage and limitations. No live Supabase project is modified by these tests.
