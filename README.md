# SeatSpot

The existing SeatSpot interactive prototype, preserved as a self-contained static website. Its green-and-white interface, phone frame, sample locations, table map, simulated QR scanner, and Cookie Corner ordering flow remain in `index.html`. There is no build step, production dependency, API, or secret to configure.

## Run locally

From this repository:

```sh
python3 -m http.server 4173 --bind 127.0.0.1
```

Open `http://127.0.0.1:4173/` in a browser. Stop the server with Ctrl+C. In a cloud workspace, bind to `0.0.0.0` if its development tools require it. You can also open `index.html` directly.

## Table-specific QR links

A table's QR code should contain the final public HTTPS URL and its table ID, for example:

```text
https://YOUR-SITE.example/?table=B3
https://168alyssa-png.github.io/SeatSpot/?table=B3
```

The GitHub Pages address above is the expected address after deployment; it is not a published deployment yet. Opening a table link selects that table, switches to the correct zone, and opens its map. The visitor still presses **Claim table** to check in. Occupied and clearing tables cannot be claimed. Known IDs are A1–A4, B1–B4, and C1–C4; lower-case IDs are accepted, and unknown IDs show a message without claiming anything. The same links work under a hosting subdirectory and after a refresh.

Once the public hostname is settled, generate a separate QR image for each URL. A QR printed for B3 should encode the complete `?table=B3` URL, not the bare table name. Use the phone camera or another QR reader to open it; the in-app **Simulate QR scan** button remains a demonstration and does not access the camera.

## Deploy with GitHub Pages

The included `.github/workflows/pages.yml` publishes only `index.html` and `.nojekyll`. It runs on pushes to `main` or manually from GitHub Actions.

1. Commit these files and push them to the repository's `main` branch. The repository had no commits when this prototype was imported.
2. In the repository's **Settings → Pages**, set the source to **GitHub Actions**.
3. Run **Deploy SeatSpot to GitHub Pages** from the **Actions** tab if the initial push happened before Pages was enabled.
4. Use the deployment URL reported by GitHub. Test the home page and `?table=B3` on that public URL before generating printed QR codes.

No build command, environment variable, backend, or custom routing rule is required. If using another static host, upload `index.html` as the site's root document; keep the query string in table links. Do not upload the `.git` directory.

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

The suite starts and stops its own local server. It checks navigation, filters and search, zones, table claims and release, order totals and timed progress, pickup, modal controls, reset, table links, and narrow-screen layouts. No running development server is needed for tests.

## Prototype behavior

All occupancy, claims, and orders are simulated in the current browser page. Refreshing starts a fresh demo; table links recognize the table again. Different visitors do not share table availability, and orders are not sent to a real vendor. Cookie Corner is the enabled sample vendor; the other vendor buttons explain that limitation. Each table represents four seats, and the map's percentage is occupied tables divided by all twelve tables, including those being cleared. Cafeteria A's home summary follows the same map data; the other locations are examples.

Real shared availability, lasting check-ins, staff order handling, and collision prevention would require a backend in a later project phase. Public static hosting is sufficient to share and demonstrate this prototype.
