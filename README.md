# SeatSpot

The existing SeatSpot interactive prototype, preserved as a static website. Its green-and-white interface, sample locations, table map, and Cookie Corner ordering flow remain in `index.html`. A bundled QR decoder in `assets/` powers the real camera scanner. The responsive layout uses a normal website header, natural page scrolling, and wider desktop content, with bottom navigation on small screens. There is no simulated phone frame or status bar. The app needs no package installation, backend, API key, or secret; Vercel's deployment command copies the HTML and its bundled assets into the public output directory.

Production address: [seatspot-zi36.vercel.app](https://seatspot-zi36.vercel.app/).

## Run locally

From this repository:

```sh
python3 -m http.server 4173 --bind 127.0.0.1
```

Open `http://127.0.0.1:4173/` in a browser. Stop the server with Ctrl+C. In a cloud workspace, bind to `0.0.0.0` if its development tools require it. Camera access requires the public HTTPS site or a localhost development server; plain HTTP over a local network is insufficient.

## Table-specific QR links

A table's QR code should contain the final public HTTPS URL and its table ID, for example:

```text
https://seatspot-zi36.vercel.app/?table=B3
https://seatspot-zi36.vercel.app/?table=B12
```

Opening a table link selects that table, switches to the correct zone, opens its map, and shows a claim prompt. For an available table, press **Claim Table B3** (or the matching table ID) to check in, or **Not now** to keep browsing without claiming it. Occupied and clearing tables show their status with claiming disabled and a **View map** button. The live map has 36 tables, with 12 in each zone: A1–A12, B1–B12, and C1–C12. All IDs support table links (for example, `?table=B12`); lower-case IDs are accepted, and unknown IDs show a message without claiming anything. The same links work under a hosting subdirectory and after a refresh.

Generate a separate QR image for each full table URL. A QR printed for B3 should encode the complete URL above, not the bare table name. Visitors can scan it inside SeatSpot or use their phone's camera to open the table link directly. The live map's existing **Simulate QR scan** remains available for demonstrations without a camera.

## In-page camera scanner

1. On Home, tap **Scan table QR** and allow the browser to use the camera. SeatSpot requests the rear camera without microphone access and displays the live video inside its existing dialog.
2. Point the camera at a table QR. A known ID on the current site's origin or the production origin above is accepted; relative links such as `?table=B12` also work. Unrelated sites, missing or duplicate table parameters, and unknown IDs are rejected while scanning continues.
3. On detection, the camera stops, the correct zone and table are selected, and **Table B3 detected** appears with the normal claim prompt. Confirm the claim to continue ordering. Unavailable tables retain their existing restrictions, and a visitor must leave their current table before scanning another.

**Cancel scanner**, Escape, clicking the dialog backdrop, or choosing **Choose table manually** releases the camera. It also stops when the page is hidden or left. A late camera-permission response after cancellation is released immediately. Permission denial, a missing/busy camera, unsupported browsers, and insecure HTTP show an explanatory message with retry and manual-selection options. If permission was previously denied, enable camera access for SeatSpot in the browser's site settings before retrying.

The local jsQR 1.4.0 library decodes frames entirely in the browser; there is no camera upload, CDN dependency, or reliance on `BarcodeDetector`. Video uses muted inline playback for iPhone Safari and Android Chrome. Keep `assets/` alongside `index.html` on any host; see `assets/README.md` for the decoder's provenance and license.

## Deploy with Vercel (recommended)

Use Vercel's free **Hobby** plan for this demo. The checked-in `vercel.json` configures a static deployment: no framework or dependency installation, and a command that copies `index.html` and `assets/` into the generated `public/` directory. Only that directory is published. The camera Permissions-Policy permits the site's own camera access and disables microphone access. It requires no environment variables, backend, or custom routing rules.

1. Open [Vercel New Project](https://vercel.com/new) and sign in with GitHub. Choose the Hobby plan if asked.
2. Find `168alyssa-png/SeatSpot` under **Import Git Repository** and click **Import**. If it is missing, use **Adjust GitHub App Permissions** (or **Install**) to grant Vercel access to this repository.
3. Use the project name `seatspot` (or another available name), with the repository root as **Root Directory**. The configuration file supplies **Other** as the framework, skips dependency installation, copies the HTML as its build command, and sets the output directory to `public`. Leave environment variables empty.
4. Click **Deploy**. Open the production domain Vercel reports in the project's **Domains** section; use that stable address for QR codes. The actual address depends on availability and is not assumed to be `seatspot.vercel.app`.
5. Check the home page, `/?table=B3`, and `/?table=B12` on that domain. Confirm that the matching table and claim prompt appear. Opening a link must not claim the table until confirmation.

Once the GitHub repository is connected, later pushes to `main` trigger new production deployments. Test results and documentation stay in GitHub; they are not copied into the site's public directory. You do not need to share a Vercel token in chat or add it to the repository.

## Deploy with GitHub Pages (alternative)

The included `.github/workflows/pages.yml` publishes `index.html`, `assets/`, and `.nojekyll`. It runs on pushes to `main` or manually from GitHub Actions.

1. Commit these files and push them to the repository's `main` branch. The repository had no commits when this prototype was imported.
2. In the repository's **Settings → Pages**, set the source to **GitHub Actions**.
3. Run **Deploy SeatSpot to GitHub Pages** from the **Actions** tab if the initial push happened before Pages was enabled.
4. Use the deployment URL reported by GitHub. Test the home page and `?table=B3` on that public URL before generating printed QR codes.

For GitHub Pages, no build command, environment variable, backend, or custom routing rule is required. If using another static host, upload `index.html` as the site's root document with its `assets/` directory; keep the query string in table links. Do not upload the `.git` directory.

## Browser checks

Python 3.10+ and Chromium are needed only for the development checks. Install the test dependency in a local virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

The tests use `CHROMIUM_EXECUTABLE`, a system `chromium`/`google-chrome`, or a Playwright-managed browser. If no system browser is available, install one with `.venv/bin/python -m playwright install chromium` (Linux may also require Playwright's system dependencies). Then run:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

The suite starts and stops its own local server. It checks navigation, filters and search, zones, table claims and release, order totals and timed progress, pickup, modal controls, reset, table links, and narrow-screen layouts. Scanner tests feed actual QR frames through Chromium's native camera/video pipeline and the bundled decoder; error and cancellation tests control media-device responses. The committed PNG fixtures are converted to camera video in a temporary directory with the Python standard library, with no extra test dependencies. No running development server is needed for tests.

After deployment, check physical iPhone Safari and Android Chrome: first-use Allow, rear-camera preview and QR detection, Deny and retry via site settings, Cancel/manual selection, and switching away from the page. Automated tests cannot certify phone hardware or operating-system permission dialogs.

## Prototype behavior

All occupancy, claims, and orders are simulated in the current browser page. Refreshing starts a fresh demo; table links recognize the table again. Different visitors do not share table availability, and orders are not sent to a real vendor. Cookie Corner is the enabled sample vendor; the other vendor buttons explain that limitation. Each table represents four seats (144 seats total), and the map's percentage is occupied tables divided by all 36 tables, including those being cleared. Cafeteria A's home summary follows the same map data; the other locations are examples.

Real shared availability, lasting check-ins, staff order handling, and collision prevention would require a backend in a later project phase. Public static hosting is sufficient to share and demonstrate this prototype.
