"""Browser regression checks: python3 -m unittest discover -s tests -v."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import os
import re
import shutil
import unittest

from playwright.sync_api import expect, sync_playwright
from backend_fixture import install_ordering_fixture


ROOT = Path(__file__).resolve().parents[1]
DEMO_TABLES = {
    "A1": "Available now", "A2": "Occupied", "A3": "Occupied", "A4": "Available now",
    "A5": "Available now", "A6": "Being cleared", "A7": "Occupied", "A8": "Available now",
    "A9": "Occupied", "A10": "Available now", "A11": "Occupied", "A12": "Available now",
    "B1": "Occupied", "B2": "Being cleared", "B3": "Available now", "B4": "Occupied",
    "B5": "Available now", "B6": "Occupied", "B7": "Available now", "B8": "Occupied",
    "B9": "Being cleared", "B10": "Available now", "B11": "Occupied", "B12": "Available now",
    "C1": "Available now", "C2": "Occupied", "C3": "Occupied", "C4": "Available now",
    "C5": "Occupied", "C6": "Available now", "C7": "Being cleared", "C8": "Available now",
    "C9": "Available now", "C10": "Occupied", "C11": "Available now", "C12": "Occupied",
}


class StaticHandler(SimpleHTTPRequestHandler):
    """Serve the same static site at / and a GitHub Pages style /SeatSpot/."""

    def do_GET(self):
        if self.path.startswith("/SeatSpot/"):
            self.path = self.path[len("/SeatSpot"):]
        super().do_GET()

    def log_message(self, *_args):
        pass


class PrototypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), partial(StaticHandler, directory=str(ROOT))
        )
        cls.server_thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.playwright = sync_playwright().start()
        executable = (os.environ.get("CHROMIUM_EXECUTABLE")
                      or shutil.which("chromium") or shutil.which("google-chrome"))
        options = {"headless": True, "args": ["--no-sandbox"]}
        if executable:
            options["executable_path"] = executable
        cls.browser = cls.playwright.chromium.launch(**options)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 430, "height": 932})
        self.backend = install_ordering_fixture(self.context)
        self.page = self.context.new_page()
        self.page.set_default_timeout(4000)
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [], "Browser JavaScript errors")

    def open(self, path="/", keep_prompt=False):
        self.backend["order"] = None  # independent map viewport/scenario fixture
        response = self.page.goto(self.base_url + path)
        self.assertEqual(response.status, 200)
        expect(self.page.locator("#welcomeScreen")).to_be_hidden()
        if not keep_prompt and self.page.locator("#modal").is_visible():
            self.page.locator("#sheetContent .secondary").click()

    def nav(self, page_id):
        self.page.locator(f'.nav [data-page="{page_id}"]').click()
        self.active(page_id)

    def active(self, page_id):
        expect(self.page.locator("section.page.active")).to_have_attribute("id", page_id)

    def claim(self, table="B3"):
        self.open(f"/?table={table}", keep_prompt=True)
        self.page.get_by_role("button", name=f"Claim Table {table}", exact=True).click()
        expect(self.page.locator("#modal")).to_be_hidden()
        self.active("claimed")
        expect(self.page.locator("#claimedTable")).to_have_text(f"Table {table}")

    def item(self, name):
        return self.page.locator("#menu .item").filter(has_text=name)

    def place_one_order(self):
        self.nav("orders")
        self.item("Chocolate Cookie").locator(".cookie-select").click()
        self.page.locator("#cartAction").click()
        expect(self.page.locator("#cartSummary")).to_contain_text("Chocolate")

    def click_modal_backdrop(self):
        modal = self.page.locator("#modal")
        bounds = modal.bounding_box()
        sheet = modal.locator(".sheet").bounding_box()
        candidates = ((4, 4), (bounds["width"] - 4, 4),
                      (4, bounds["height"] - 4))
        for x, y in candidates:
            page_x, page_y = bounds["x"] + x, bounds["y"] + y
            inside_sheet = (sheet["x"] <= page_x <= sheet["x"] + sheet["width"]
                            and sheet["y"] <= page_y <= sheet["y"] + sheet["height"])
            if not inside_sheet:
                modal.click(position={"x": x, "y": y})
                return
        self.fail("The dialog must leave a clickable backdrop outside its sheet")

    def test_home_search_filters_navigation_and_demo_stalls(self):
        self.open()
        self.active("home")
        expect(self.page.locator("#locations .loc-title")).to_have_count(3)
        search = self.page.get_by_role("searchbox", name="Search location")
        search.fill("cHuLa")
        expect(self.page.locator("#locations .loc-title")).to_have_count(2)
        self.page.locator('[data-filter="Quiet"]').click()
        expect(self.page.locator("#locations .loc-title")).to_have_count(1)
        expect(self.page.locator("#locations")).to_contain_text("Chula Cafeteria B")
        self.page.locator('[data-filter="Near plug"]').click()
        expect(self.page.locator("#locations .loc-title")).to_have_count(1)
        expect(self.page.locator("#locations")).to_contain_text("Chula Cafeteria A")
        search.fill("no such location")
        expect(self.page.locator("#locations")).to_contain_text("No matching locations")
        search.fill("")
        self.page.locator('[data-filter="Near food"]').click()
        expect(self.page.locator("#locations .loc-title")).to_have_count(2)
        self.page.locator('[data-filter="Now"]').click()
        expect(self.page.locator("#locations .loc-title")).to_have_count(3)
        self.page.get_by_role("button", name="Notifications").click()
        expect(self.page.locator("#toast")).to_have_text("No new notifications")
        self.page.locator("#locations .btn").first.click()
        self.active("map")
        self.nav("orders")
        expect(self.page.locator("#orderTableTitle")).to_have_text("your table")
        expect(self.page.locator("#orderLinkStatus")).to_contain_text("Checking into a table is optional")
        expect(self.page.locator(".progress .active")).to_have_count(0)
        self.page.get_by_role("button", name="Campus Drinks").click()
        expect(self.page.locator(".vendor.active")).to_contain_text("Cookie Corner")
        expect(self.page.locator("#toast")).to_contain_text("Only Cookie Corner")
        self.page.get_by_role("button", name="Quick Bites").click()
        expect(self.page.locator(".vendor.active")).to_contain_text("Cookie Corner")
        expect(self.page.locator("#cartAction")).to_be_disabled()
        self.active("orders")
        self.nav("profile")
        self.nav("home")

    def test_qr_recognition_and_claim_prompt_for_all_demo_tables(self):
        for table, status in DEMO_TABLES.items():
            with self.subTest(table=table):
                self.open(f"/?table={table}", keep_prompt=True)
                self.active("map")
                expect(self.page.locator("#selectedName")).to_have_text(table)
                expect(self.page.locator("#selectedStatus")).to_have_text(status)
                expect(self.page.locator(".tab.active")).to_have_text(f"Zone {table[0]}")
                selected = self.page.locator("#tableGrid .selected")
                expect(selected).to_have_text(table)
                expect(selected).to_have_attribute("aria-pressed", "true")
                disabled = status != "Available now"
                self.assertEqual(self.page.locator("#selectedAction").is_disabled(), disabled)
                self.assertEqual(self.page.locator("#scannerButton").is_disabled(), disabled)
                expect(self.page.locator("#modal")).to_be_visible()
                heading = self.page.locator("#sheetContent h2")
                confirm = self.page.get_by_role("button", name=f"Claim Table {table}", exact=True)
                if disabled:
                    expect(heading).to_contain_text(f"Table {table}")
                    expect(heading).to_contain_text("occupied" if status == "Occupied" else "being cleared")
                    expect(confirm).to_be_disabled()
                    view_map = self.page.get_by_role("button", name="View map", exact=True)
                    expect(view_map).to_be_focused()
                    view_map.click()
                else:
                    expect(heading).to_have_text(f"Claim Table {table}?")
                    expect(confirm).to_be_enabled()
                    expect(confirm).to_be_focused()
                    self.page.get_by_role("button", name="Not now", exact=True).click()
                expect(self.page.locator("#modal")).to_be_hidden()
                expect(selected).to_be_focused()
                self.active("map")
                expect(self.page.locator("#orderTableTitle")).to_have_text("your table")
                expect(self.page.locator("#availCount")).to_have_text("17")
                expect(self.page.locator("#occCount")).to_have_text("15")

    def test_qr_normalization_subpaths_and_refresh(self):
        cases = [
            ("/?table=b3", "B3"),
            ("/SeatSpot/?table=%20c4%20", "C4"),
            ("/SeatSpot/index.html?table=%20a1%20&source=qr", "A1"),
            ("/SeatSpot/?table=%20b12%20", "B12"),
        ]
        for path, table in cases:
            with self.subTest(path=path):
                self.open(path, keep_prompt=True)
                expect(self.page.locator("#sheetContent h2")).to_have_text(f"Claim Table {table}?")
                self.page.reload()
                self.active("map")
                expect(self.page.locator("#modal")).to_be_visible()
                expect(self.page.locator("#selectedName")).to_have_text(table)
                expect(self.page.locator(".tab.active")).to_have_text(f"Zone {table[0]}")
                expect(self.page.locator("#sheetContent h2")).to_have_text(f"Claim Table {table}?")
                expect(self.page.locator("#availCount")).to_have_text("17")

    def test_qr_confirmation_claims_each_available_table(self):
        for table, status in DEMO_TABLES.items():
            if status != "Available now":
                continue
            with self.subTest(table=table):
                self.claim(table)
                expect(self.page.locator("#claimedZone")).to_have_text(f"Zone {table[0]}")
                expect(self.page.locator("#qrCode")).to_have_text(table)
                expect(self.page.locator("#orderTableTitle")).to_have_text(f"Table {table}")
                expect(self.page.locator("#cAvail")).to_have_text("16")
                expect(self.page.locator("#cOcc")).to_have_text("16")
                expect(self.page.locator("#cPct")).to_have_text("44%")
                self.nav("map")
                expect(self.page.locator("#selectedName")).to_have_text(table)
                expect(self.page.locator("#selectedAction")).to_have_text("Leave table")

    def test_qr_prompt_dismissal_keeps_selected_table_without_claiming(self):
        for dismiss in ("Not now", "Escape", "backdrop"):
            with self.subTest(dismiss=dismiss):
                self.open("/?table=A4", keep_prompt=True)
                modal = self.page.locator("#modal")
                confirm = self.page.get_by_role("button", name="Claim Table A4", exact=True)
                expect(confirm).to_be_focused()
                self.page.keyboard.press("Shift+Tab")
                expect(self.page.get_by_role("button", name="Not now", exact=True)).to_be_focused()
                self.page.keyboard.press("Tab")
                expect(confirm).to_be_focused()
                self.page.locator("#sheetContent h2").click()
                expect(modal).to_be_visible()
                if dismiss == "Escape":
                    self.page.keyboard.press("Escape")
                elif dismiss == "backdrop":
                    self.click_modal_backdrop()
                else:
                    self.page.get_by_role("button", name=dismiss, exact=True).click()
                expect(modal).to_be_hidden()
                expect(self.page.locator("#tableGrid .selected")).to_be_focused()
                self.active("map")
                expect(self.page.locator("#selectedName")).to_have_text("A4")
                expect(self.page.locator(".tab.active")).to_have_text("Zone A")
                expect(self.page.locator("#selectedStatus")).to_have_text("Available now")
                expect(self.page.locator("#orderTableTitle")).to_have_text("your table")
                expect(self.page.locator("#availCount")).to_have_text("17")
                expect(self.page.locator("#selectedAction")).to_be_enabled()
                self.page.locator("#selectedAction").click()
                self.active("claimed")
                expect(self.page.locator("#claimedTable")).to_have_text("Table A4")

    def test_default_and_unknown_table_links_do_not_show_claim_prompt(self):
        for path in ("/", "/SeatSpot/", "/index.html?source=qr"):
            with self.subTest(path=path):
                self.open(path, keep_prompt=True)
                self.active("home")
                expect(self.page.locator("#modal")).to_be_hidden()
        for invalid in ("unknown", "", "%3Cimg%20src=x%20onerror=alert(1)%3E"):
            with self.subTest(invalid=invalid):
                self.open(f"/SeatSpot/?table={invalid}", keep_prompt=True)
                self.active("map")
                expect(self.page.locator("#modal")).to_be_hidden()
                expect(self.page.locator("#selectedName")).to_have_text("B3")
                expect(self.page.locator("#toast")).to_contain_text("Unknown table QR")
                expect(self.page.locator("#tableGrid button")).to_have_count(12)

    def test_zone_claim_single_table_and_leave_counts(self):
        self.open("/?table=B3")
        expect(self.page.locator("#availCount")).to_have_text("17")
        expect(self.page.locator("#occCount")).to_have_text("15")
        expect(self.page.locator("#pctCount")).to_have_text("42%")
        for zone in ("A", "C", "B", "A"):
            self.page.locator(f'[data-zone="{zone}"]').click()
            self.assertEqual(self.page.locator("#tableGrid button").all_text_contents(),
                             [f"{zone}{n}" for n in range(1, 13)])
            expect(self.page.locator("#tableGrid button:visible")).to_have_count(12)
            expect(self.page.locator("#selectedMeta")).to_contain_text(f"Zone {zone}")
        self.page.get_by_role("button", name="Table A4, available", exact=True).click()
        self.page.locator("#selectedAction").click()
        self.active("claimed")
        expect(self.page.locator("#claimedTable")).to_have_text("Table A4")
        expect(self.page.locator("#claimedZone")).to_have_text("Zone A")
        expect(self.page.locator("#cAvail")).to_have_text("16")
        expect(self.page.locator("#cOcc")).to_have_text("16")
        expect(self.page.locator("#cPct")).to_have_text("44%")
        self.nav("map")
        self.page.get_by_role("button", name="Table A1, available", exact=True).click()
        expect(self.page.locator("#selectedAction")).to_be_disabled()
        expect(self.page.locator("#selectedAction")).to_have_text("Leave A4 first")
        expect(self.page.locator("#scannerButton")).to_be_disabled()
        self.nav("home")
        cafeteria = self.page.locator("#locations .card").filter(has_text="Chula Cafeteria A")
        expect(cafeteria.locator(".available")).to_contain_text("64")
        self.nav("map")
        expect(self.page.locator("#selectedName")).to_have_text("A4")
        self.page.locator("#selectedAction").click()
        expect(self.page.locator("#selectedStatus")).to_have_text("Available now")
        expect(self.page.locator("#availCount")).to_have_text("17")
        expect(self.page.locator("#occCount")).to_have_text("15")

    def test_new_last_row_table_claim_and_reset_restore_expanded_map(self):
        self.open("/?table=A1")
        self.page.get_by_role("button", name="Table A12, available", exact=True).click()
        expect(self.page.locator("#selectedName")).to_have_text("A12")
        expect(self.page.locator("#selectedMeta")).to_contain_text("Zone A")
        self.page.locator("#selectedAction").click()
        self.active("claimed")
        expect(self.page.locator("#claimedTable")).to_have_text("Table A12")
        expect(self.page.locator("#claimedZone")).to_have_text("Zone A")
        expect(self.page.locator("#cAvail")).to_have_text("16")
        expect(self.page.locator("#cOcc")).to_have_text("16")
        self.nav("profile")
        self.page.get_by_role("button", name="Reset prototype", exact=True).click()
        self.active("home")
        cafeteria = self.page.locator("#locations .card").filter(has_text="Chula Cafeteria A")
        expect(cafeteria.locator(".available")).to_contain_text("68")
        expect(cafeteria).to_contain_text("60 / 144 seats occupied")
        self.nav("map")
        expect(self.page.locator("#availCount")).to_have_text("17")
        expect(self.page.locator("#occCount")).to_have_text("15")
        expect(self.page.locator("#pctCount")).to_have_text("42%")
        self.page.locator('[data-zone="A"]').click()
        expect(self.page.locator("#tableGrid button")).to_have_count(12)
        last_table = self.page.get_by_role("button", name="Table A12, available", exact=True)
        last_table.click()
        expect(self.page.locator("#selectedStatus")).to_have_text("Available now")
        expect(self.page.locator("#selectedAction")).to_have_text("Claim table")

    def test_scan_modal_cancel_escape_backdrop_focus_and_claim(self):
        self.open("/?table=B3")
        trigger = self.page.locator("#scannerButton")
        expect(trigger).to_have_text("📷 Scan table QR")
        expect(self.page.get_by_role("button", name=re.compile("Simulate QR scan"))).to_have_count(0)
        trigger.click()
        modal = self.page.get_by_role("dialog")
        manual = self.page.get_by_role("button", name="Choose table manually", exact=True)
        cancel = self.page.get_by_role("button", name="Cancel scanner", exact=True)
        retry = self.page.get_by_role("button", name="Try camera again", exact=True)
        expect(modal).to_be_visible()
        expect(self.page.locator("#sheetContent h2")).to_have_text("Scan your table QR")
        expect(self.page.locator("#scannerVideo")).to_have_count(1)
        expect(self.page.get_by_role("button", name="Scan B3", exact=True)).to_have_count(0)
        expect(manual).to_be_focused()
        # No camera is supplied to this browser. Exercise the real scanner's
        # permission/device fallback rather than replacing QR decoding.
        expect(retry).to_be_visible()
        expect(self.page.locator("#scannerStatus")).to_contain_text(
            re.compile("permission was denied|No camera was found|unavailable")
        )
        self.page.keyboard.press("Shift+Tab")
        expect(retry).to_be_focused()
        self.page.keyboard.press("Shift+Tab")
        expect(cancel).to_be_focused()
        self.page.keyboard.press("Tab")
        expect(retry).to_be_focused()
        self.page.keyboard.press("Escape")
        expect(modal).to_be_hidden()
        expect(trigger).to_be_focused()
        trigger.click()
        cancel.click()
        expect(modal).to_be_hidden()
        expect(trigger).to_be_focused()
        trigger.click()
        self.page.locator("#sheetContent h2").click()
        expect(modal).to_be_visible()
        self.click_modal_backdrop()
        expect(modal).to_be_hidden()
        expect(trigger).to_be_focused()
        trigger.click()
        manual.click()
        expect(modal).to_be_hidden()
        expect(trigger).to_be_focused()
        self.active("map")
        expect(self.page.locator("#selectedName")).to_have_text("B3")
        expect(self.page.locator("#selectedStatus")).to_have_text("Available now")
        expect(self.page.locator("#orderTableTitle")).to_have_text("your table")
        expect(self.page.locator("#availCount")).to_have_text("17")
        self.page.locator("#selectedAction").click()
        self.active("claimed")
        expect(self.page.locator("#claimedTable")).to_have_text("Table B3")

    def test_single_cookie_order_progress_and_pickup(self):
        self.claim()
        self.nav("orders")
        expect(self.page.locator("#cartAction")).to_be_disabled()
        expect(self.page.locator(".plus,.circlebtn")).to_have_count(0)
        self.item("Chocolate Cookie").locator(".cookie-select").click()
        self.page.locator("#cartAction").click()
        expect(self.page.locator("#cartSummary")).to_contain_text("Chocolate")
        expect(self.page.locator("#menu button:disabled")).to_have_count(3)
        for status, steps in (("Preparing", 2), ("Ready", 3)):
            self.backend['order']['status'] = status
            self.page.evaluate("refreshCustomerOrders()")
            expect(self.page.locator(".progress .active")).to_have_count(steps)
        self.page.locator("#cartAction").click()
        expect(self.page.locator("#cartAction")).to_have_text("Collected ✓")
        expect(self.page.locator("#menu button:disabled")).to_have_count(3)
        expect(self.page.locator("#orderTableTitle")).to_have_text("Table B3")

    def test_leave_and_reset_preserve_cookie_session_limit(self):
        self.claim()
        self.place_one_order()
        self.nav("map")
        self.page.locator("#selectedAction").click()
        self.nav("orders")
        expect(self.page.locator("#cartSummary")).to_contain_text("Chocolate")
        expect(self.page.locator("#menu button:disabled")).to_have_count(3)
        self.nav("profile")
        self.page.get_by_role("button", name="Reset prototype", exact=True).click()
        self.nav("orders")
        expect(self.page.locator("#cartSummary")).to_contain_text("Chocolate")
        expect(self.page.locator("#menu button:disabled")).to_have_count(3)
        expect(self.page.locator("#orderTableTitle")).to_have_text("your table")

    def test_mobile_and_desktop_controls_fit_without_horizontal_overflow(self):
        viewports = ((320, 640), (375, 852), (390, 852), (430, 852),
                     (1280, 640), (844, 390))
        for width, height in viewports:
            with self.subTest(width=width, height=height):
                self.page.set_viewport_size({"width": width, "height": height})
                self.open("/?table=B12")
                self.assert_main_fits()
                expect(self.page.locator("#tableGrid button:visible")).to_have_count(12)
                self.assert_controls_fit("#tableGrid button")
                self.page.get_by_role("button", name="Table B12, available", exact=True).click()
                expect(self.page.locator("#selectedName")).to_have_text("B12")
                self.page.locator("#selectedAction").click()
                self.active("claimed")
                expect(self.page.locator("#claimedTable")).to_have_text("Table B12")
                expect(self.page.locator("#claimedZone")).to_have_text("Zone B")
                self.assert_main_fits()
                self.nav("orders")
                self.assert_main_fits()
                self.assert_controls_fit("#menu button")
                self.item("Chocolate Cookie").locator(".cookie-select").click()
                expect(self.page.locator("#cartSummary")).to_contain_text("Chocolate")
                self.nav("home")
                self.assert_main_fits()

    def test_website_uses_available_width_and_document_scrolling(self):
        for width, height in ((320, 640), (1280, 640), (844, 390)):
            with self.subTest(width=width, height=height):
                self.page.set_viewport_size({"width": width, "height": height})
                self.claim("B12")
                expect(self.page.locator(".phone, .shell, .status, .island")).to_have_count(0)
                if width <= 430:
                    app = self.page.locator(".app").bounding_box()
                    self.assertAlmostEqual(app["x"], 0, delta=1)
                    self.assertAlmostEqual(app["width"], width, delta=1)
                if width == 1280:
                    self.assertGreater(self.page.locator(".main").bounding_box()["width"], 900)
                self.assert_document_scrolling()
                for page_id in ("map", "orders", "profile", "home"):
                    self.nav(page_id)
                    self.assert_main_fits()
                    self.assert_document_scrolling()
                    self.assert_controls_fit(".nav button", within_main=False)

    def test_claim_scan_and_order_dialogs_fit_small_and_desktop_viewports(self):
        for width, height in ((320, 640), (1280, 640), (844, 390)):
            with self.subTest(width=width, height=height):
                self.page.set_viewport_size({"width": width, "height": height})
                self.open("/?table=B12", keep_prompt=True)
                self.assert_dialog_fits()
                self.click_modal_backdrop()
                expect(self.page.locator("#modal")).to_be_hidden()
                expect(self.page.locator("#scannerButton")).to_have_text("📷 Scan table QR")
                self.page.locator("#scannerButton").click()
                expect(self.page.locator("#sheetContent h2")).to_have_text("Scan your table QR")
                expect(self.page.locator("#scannerVideo")).to_have_count(1)
                expect(self.page.get_by_role("button", name="Scan B12", exact=True)).to_have_count(0)
                self.assert_dialog_fits()
                self.page.get_by_role("button", name="Choose table manually", exact=True).click()
                expect(self.page.locator("#modal")).to_be_hidden()
                self.active("map")
                expect(self.page.locator("#selectedName")).to_have_text("B12")
                expect(self.page.locator("#selectedStatus")).to_have_text("Available now")
                expect(self.page.locator("#orderTableTitle")).to_have_text("your table")
                self.page.locator("#selectedAction").click()
                self.active("claimed")
                self.nav("orders")
                self.item("Chocolate Cookie").locator(".cookie-select").click()
                self.page.locator("#cartAction").click()
                expect(self.page.locator("#modal")).to_be_hidden()
                expect(self.page.locator("#cartSummary")).to_contain_text("Chocolate")
                self.nav("map")
                self.page.locator("#selectedAction").click()
                expect(self.page.locator("#selectedStatus")).to_have_text("Available now")

    def assert_main_fits(self):
        dimensions = self.page.locator(".main").evaluate(
            "el => ({content: el.scrollWidth, viewport: el.clientWidth})"
        )
        self.assertLessEqual(dimensions["content"], dimensions["viewport"] + 1,
                             f"Horizontal overflow: {dimensions}")
        document = self.page.evaluate(
            "() => ({content: document.documentElement.scrollWidth, viewport: innerWidth})"
        )
        self.assertLessEqual(document["content"], document["viewport"] + 1,
                             f"Document horizontal overflow: {document}")

    def assert_controls_fit(self, selector, within_main=True):
        viewport_width = self.page.viewport_size["width"]
        bounds = (self.page.locator(".main").bounding_box() if within_main
                  else {"x": 0, "width": viewport_width})
        for control in self.page.locator(selector).all():
            box = control.bounding_box()
            self.assertGreaterEqual(box["x"], max(0, bounds["x"]) - 1)
            self.assertLessEqual(box["x"] + box["width"],
                                 min(viewport_width, bounds["x"] + bounds["width"]) + 1)

    def assert_document_scrolling(self):
        metrics = self.page.locator(".main").evaluate(
            "el => ({overflow: getComputedStyle(el).overflowY, top: el.scrollTop, "
            "height: document.documentElement.scrollHeight, viewport: innerHeight})"
        )
        self.assertNotIn(metrics["overflow"], ("auto", "scroll", "hidden"),
                         "Page content should use normal document scrolling")
        self.assertEqual(metrics["top"], 0)
        self.page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        if metrics["height"] > metrics["viewport"] + 1:
            self.assertGreater(self.page.evaluate("window.scrollY"), 0)
        self.assertEqual(self.page.locator(".main").evaluate("el => el.scrollTop"), 0)

    def assert_dialog_fits(self):
        modal = self.page.locator("#modal")
        expect(modal).to_be_visible()
        viewport = self.page.viewport_size
        for element in (modal, modal.locator(".sheet")):
            bounds = element.bounding_box()
            self.assertGreaterEqual(bounds["x"], -1)
            self.assertGreaterEqual(bounds["y"], -1)
            self.assertLessEqual(bounds["x"] + bounds["width"], viewport["width"] + 1)
            self.assertLessEqual(bounds["y"] + bounds["height"], viewport["height"] + 1)
        for button in modal.locator("button").all():
            button.scroll_into_view_if_needed()
            expect(button).to_be_visible()
            bounds = button.bounding_box()
            self.assertGreaterEqual(bounds["x"], -1)
            self.assertGreaterEqual(bounds["y"], -1)
            self.assertLessEqual(bounds["x"] + bounds["width"], viewport["width"] + 1)
            self.assertLessEqual(bounds["y"] + bounds["height"], viewport["height"] + 1)


if __name__ == "__main__":
    unittest.main()
