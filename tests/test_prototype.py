"""Browser regression checks: python3 -m unittest discover -s tests -v."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import os
import shutil
import unittest

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]


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
        self.page = self.context.new_page()
        self.page.set_default_timeout(4000)
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [], "Browser JavaScript errors")

    def open(self, path="/"):
        response = self.page.goto(self.base_url + path)
        self.assertEqual(response.status, 200)

    def nav(self, page_id):
        self.page.locator(f'.nav [data-page="{page_id}"]').click()
        self.active(page_id)

    def active(self, page_id):
        expect(self.page.locator("section.page.active")).to_have_attribute("id", page_id)

    def claim(self, table="B3"):
        self.open(f"/?table={table}")
        self.page.locator("#selectedAction").click()
        self.active("claimed")
        expect(self.page.locator("#claimedTable")).to_have_text(f"Table {table}")

    def item(self, name):
        return self.page.locator("#menu .item").filter(has_text=name)

    def place_one_order(self):
        self.nav("orders")
        self.item("Chocolate Chip Cookie").locator(".plus").click()
        self.page.locator("#cartAction").click()
        self.page.get_by_role("button", name="Place demo order", exact=True).click()
        expect(self.page.locator("#cartSummary")).to_contain_text("Order placed")

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
        expect(self.page.locator("#orderLinkStatus")).to_contain_text("Claim a table")
        expect(self.page.locator(".progress .active")).to_have_count(0)
        self.page.get_by_role("button", name="Campus Drinks").click()
        expect(self.page.locator(".vendor.active")).to_contain_text("Cookie Corner")
        expect(self.page.locator("#toast")).to_contain_text("Only Cookie Corner")
        self.page.get_by_role("button", name="Quick Bites").click()
        expect(self.page.locator(".vendor.active")).to_contain_text("Cookie Corner")
        self.page.locator("#cartAction").click()
        self.active("map")
        expect(self.page.locator("#toast")).to_have_text("Claim a table first")
        self.nav("profile")
        self.nav("home")

    def test_qr_recognition_at_root_and_subpath(self):
        cases = [
            ("/?table=B3", "B3", "Available now", False),
            ("/SeatSpot/?table=%20c4%20", "C4", "Available now", False),
            ("/SeatSpot/index.html?table=A2", "A2", "Occupied", True),
            ("/?table=B2", "B2", "Being cleared", True),
        ]
        for path, table, status, disabled in cases:
            with self.subTest(path=path):
                self.open(path)
                self.active("map")
                expect(self.page.locator("#selectedName")).to_have_text(table)
                expect(self.page.locator("#selectedStatus")).to_have_text(status)
                expect(self.page.locator(".tab.active")).to_have_text(f"Zone {table[0]}")
                self.assertEqual(self.page.locator("#selectedAction").is_disabled(), disabled)
                self.assertEqual(self.page.locator("#scannerButton").is_disabled(), disabled)
                expect(self.page.locator("#orderTableTitle")).to_have_text("your table")
        for invalid in ("unknown", "", "%3Cimg%20src=x%20onerror=alert(1)%3E"):
            with self.subTest(invalid=invalid):
                self.open(f"/SeatSpot/?table={invalid}")
                self.active("map")
                expect(self.page.locator("#selectedName")).to_have_text("B3")
                expect(self.page.locator("#toast")).to_contain_text("Unknown table QR")
                expect(self.page.locator("#tableGrid button")).to_have_count(4)

    def test_zone_claim_single_table_and_leave_counts(self):
        self.open("/?table=B3")
        expect(self.page.locator("#availCount")).to_have_text("5")
        expect(self.page.locator("#occCount")).to_have_text("6")
        expect(self.page.locator("#pctCount")).to_have_text("50%")
        for zone in ("A", "C", "B", "A"):
            self.page.locator(f'[data-zone="{zone}"]').click()
            self.assertEqual(self.page.locator("#tableGrid button").all_text_contents(),
                             [f"{zone}{n}" for n in range(1, 5)])
            expect(self.page.locator("#selectedMeta")).to_contain_text(f"Zone {zone}")
        self.page.get_by_role("button", name="Table A4, available", exact=True).click()
        self.page.locator("#selectedAction").click()
        self.active("claimed")
        expect(self.page.locator("#claimedTable")).to_have_text("Table A4")
        expect(self.page.locator("#claimedZone")).to_have_text("Zone A")
        expect(self.page.locator("#cAvail")).to_have_text("4")
        expect(self.page.locator("#cOcc")).to_have_text("7")
        expect(self.page.locator("#cPct")).to_have_text("58%")
        self.nav("map")
        self.page.get_by_role("button", name="Table A1, available", exact=True).click()
        expect(self.page.locator("#selectedAction")).to_be_disabled()
        expect(self.page.locator("#selectedAction")).to_have_text("Leave A4 first")
        expect(self.page.locator("#scannerButton")).to_be_disabled()
        self.nav("home")
        cafeteria = self.page.locator("#locations .card").filter(has_text="Chula Cafeteria A")
        expect(cafeteria.locator(".available")).to_contain_text("16")
        self.nav("map")
        expect(self.page.locator("#selectedName")).to_have_text("A4")
        self.page.locator("#selectedAction").click()
        expect(self.page.locator("#selectedStatus")).to_have_text("Available now")
        expect(self.page.locator("#availCount")).to_have_text("5")
        expect(self.page.locator("#occCount")).to_have_text("6")

    def test_scan_modal_cancel_escape_backdrop_focus_and_claim(self):
        self.open("/?table=B3")
        trigger = self.page.locator("#scannerButton")
        trigger.click()
        modal = self.page.get_by_role("dialog")
        scan = self.page.get_by_role("button", name="Scan B3", exact=True)
        cancel = self.page.get_by_role("button", name="Cancel", exact=True)
        expect(modal).to_be_visible()
        expect(scan).to_be_focused()
        self.page.keyboard.press("Shift+Tab")
        expect(cancel).to_be_focused()
        self.page.keyboard.press("Tab")
        expect(scan).to_be_focused()
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
        # Avoid the phone's clipped, rounded corners when clicking the backdrop.
        modal.click(position={"x": modal.bounding_box()["width"] / 2, "y": 60})
        expect(modal).to_be_hidden()
        expect(trigger).to_be_focused()
        trigger.click()
        scan.click()
        self.active("claimed")
        expect(self.page.locator("#claimedTable")).to_have_text("Table B3")

    def test_order_total_review_progress_and_pickup(self):
        self.claim()
        self.nav("orders")
        self.page.locator("#cartAction").click()
        expect(self.page.locator("#toast")).to_have_text("Add at least one cookie")
        chocolate = self.item("Chocolate Chip Cookie")
        chocolate.locator(".circlebtn:not(.plus)").click()
        expect(self.page.locator("#cartCount")).to_have_text("0")
        chocolate.locator(".plus").click(click_count=2, delay=30)
        self.item("Red Velvet Cookie").locator(".plus").click()
        expect(self.page.locator("#cartCount")).to_have_text("3")
        expect(self.page.locator("#cartTotal")).to_have_text("139")
        self.page.locator("#cartAction").click()
        expect(self.page.locator("#sheetContent")).to_contain_text("139 THB")
        self.page.get_by_role("button", name="Keep editing", exact=True).click()
        expect(self.page.locator("#cartCount")).to_have_text("3")
        self.page.locator("#cartAction").click()
        self.page.get_by_role("button", name="Place demo order", exact=True).click()
        expect(self.page.locator(".progress .active")).to_have_count(1)
        expect(self.page.locator("#cartAction")).to_be_disabled()
        expect(self.page.locator("#menu button:disabled")).to_have_count(6)
        expect(self.page.locator("#cartSummary")).to_contain_text("139 THB")
        expect(self.page.locator("#cartSummary")).to_contain_text("Preparing", timeout=4000)
        expect(self.page.locator(".progress .active")).to_have_count(2)
        expect(self.page.locator("#cartAction")).to_have_text("Confirm pickup", timeout=4000)
        expect(self.page.locator(".progress .active")).to_have_count(3)
        expect(self.page.locator("#menu button:disabled")).to_have_count(6)
        self.page.get_by_role("button", name="Notifications").click()
        expect(self.page.locator("#toast")).to_contain_text("Ready for pickup")
        self.page.locator("#cartAction").click()
        expect(self.page.locator("#cartCount")).to_have_text("0")
        expect(self.page.locator(".progress .active")).to_have_count(0)
        expect(self.page.locator("#menu button:disabled")).to_have_count(0)
        self.item("Matcha Cookie").locator(".plus").click()
        expect(self.page.locator("#cartTotal")).to_have_text("45")
        expect(self.page.locator("#orderTableTitle")).to_have_text("Table B3")

    def test_leave_and_reset_cancel_pending_order_timers(self):
        for action in ("leave", "reset"):
            with self.subTest(action=action):
                self.claim()
                self.page.clock.install()
                self.place_one_order()
                if action == "leave":
                    self.nav("map")
                    self.page.locator("#selectedAction").click()
                    self.active("map")
                else:
                    self.nav("profile")
                    self.page.get_by_role("button", name="Reset prototype", exact=True).click()
                    self.active("home")
                self.page.clock.fast_forward(6000)
                self.nav("orders")
                expect(self.page.locator("#cartCount")).to_have_text("0")
                expect(self.page.locator("#cartTotal")).to_have_text("0")
                expect(self.page.locator("#cartAction")).to_have_text("Review order")
                expect(self.page.locator(".progress .active")).to_have_count(0)
                expect(self.page.locator("#orderTableTitle")).to_have_text("your table")
                self.nav("map")
                expect(self.page.locator("#availCount")).to_have_text("5")
                expect(self.page.locator("#selectedStatus")).to_have_text("Available now")

    def test_mobile_and_desktop_controls_fit_without_horizontal_overflow(self):
        for width in (320, 375, 390, 430, 1280):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 852})
                self.open("/?table=B3")
                self.assert_main_fits()
                self.assert_controls_fit("#tableGrid button")
                self.page.get_by_role("button", name="Table B3, available", exact=True).click()
                self.nav("orders")
                self.assert_main_fits()
                self.assert_controls_fit("#menu button")
                self.item("Chocolate Chip Cookie").locator(".plus").click()
                expect(self.page.locator("#cartCount")).to_have_text("1")
                self.nav("home")
                self.assert_main_fits()

    def assert_main_fits(self):
        dimensions = self.page.locator(".main").evaluate(
            "el => ({content: el.scrollWidth, viewport: el.clientWidth})"
        )
        self.assertLessEqual(dimensions["content"], dimensions["viewport"] + 1,
                             f"Horizontal overflow: {dimensions}")

    def assert_controls_fit(self, selector):
        phone = self.page.locator(".phone").bounding_box()
        for control in self.page.locator(selector).all():
            box = control.bounding_box()
            self.assertGreaterEqual(box["x"], phone["x"])
            self.assertLessEqual(box["x"] + box["width"], phone["x"] + phone["width"])


if __name__ == "__main__":
    unittest.main()
