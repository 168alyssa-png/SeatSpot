"""Real QR camera and scanner lifecycle checks; run with unittest discovery.

Chromium receives deterministic QR video through its fake camera device. Its
real media/video/canvas/decoder pipeline runs, including stopping MediaStream
tracks. Only permission errors and pending permission races use media mocks.
"""

from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import os
import re
import shutil
import struct
import unittest
import zlib

from playwright.sync_api import expect, sync_playwright

from test_prototype import ROOT, StaticHandler
from backend_fixture import install_ordering_fixture


FIXTURES = Path(__file__).parent / "fixtures"

# Record actual native streams and constraints without replacing successful
# camera acquisition or QR decoding.
RECORD_CAMERA = """() => {
  window.cameraRequests = [];
  window.cameraStreams = [];
  window.nativeGetUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia = async constraints => {
    cameraRequests.push(constraints);
    const stream = await nativeGetUserMedia(constraints);
    cameraStreams.push(stream);
    return stream;
  };
}"""


def qr_camera_video(png_path, output_path):
    """Upscale our tiny grayscale QR fixture into one looping YUV420 frame."""
    png = png_path.read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    offset, compressed = 8, b""
    while offset < len(png):
        length = struct.unpack("!I", png[offset:offset + 4])[0]
        kind = png[offset + 4:offset + 8]
        data = png[offset + 8:offset + 8 + length]
        if kind == b"IHDR":
            width, height, depth, color, compression, filtering, interlace = struct.unpack("!2I5B", data)
            assert (depth, color, compression, filtering, interlace) == (8, 0, 0, 0, 0)
        elif kind == b"IDAT":
            compressed += data
        offset += length + 12
    raw = zlib.decompress(compressed)
    rows = []
    for y in range(height):
        start = y * (width + 1)
        assert raw[start] == 0, "QR fixtures use PNG filter zero"
        rows.append(raw[start + 1:start + 1 + width])
    frame_width, frame_height = 640, 480
    scale = min(frame_width // width, frame_height // height) - 1
    left, top = (frame_width - width * scale) // 2, (frame_height - height * scale) // 2
    luma = bytearray([235]) * (frame_width * frame_height)
    for y, row in enumerate(rows):
        expanded = bytes(16 if pixel == 0 else 235 for pixel in row for _ in range(scale))
        for repeat in range(scale):
            start = (top + y * scale + repeat) * frame_width + left
            luma[start:start + len(expanded)] = expanded
    output_path.write_bytes(
        b"YUV4MPEG2 W640 H480 F30:1 Ip A1:1 C420jpeg\nFRAME\n"
        + luma + bytes([128]) * (frame_width * frame_height // 2)
    )


class ScannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), partial(StaticHandler, directory=str(ROOT))
        )
        cls.server_thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.temp = TemporaryDirectory(prefix="seatspot-scanner-")
        cls.videos = {}
        for png in FIXTURES.glob("*.png"):
            path = Path(cls.temp.name) / (png.stem + ".y4m")
            qr_camera_video(png, path)
            cls.videos[png.stem] = path
        cls.playwright = sync_playwright().start()
        cls.executable = (os.environ.get("CHROMIUM_EXECUTABLE")
                          or shutil.which("chromium") or shutil.which("google-chrome"))

    @classmethod
    def tearDownClass(cls):
        cls.playwright.stop()
        cls.temp.cleanup()
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join()

    def setUp(self):
        self.browser = None
        self.errors = []

    def tearDown(self):
        if self.browser:
            self.browser.close()
        self.assertEqual(self.errors, [], "Browser JavaScript errors")

    def open_camera_page(self, fixture=None, init_script=None, viewport=None):
        if self.browser:
            self.browser.close()
        args = ["--no-sandbox", "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
        if fixture:
            args.append(f"--use-file-for-fake-video-capture={self.videos[fixture]}")
        options = {"headless": True, "args": args}
        if self.executable:
            options["executable_path"] = self.executable
        self.browser = self.playwright.chromium.launch(**options)
        self.context = self.browser.new_context(viewport=viewport or {"width": 390, "height": 844})
        install_ordering_fixture(self.context)
        self.context.add_init_script(f"({RECORD_CAMERA})();\n{init_script or ''}")
        self.page = self.context.new_page()
        self.page.set_default_timeout(6000)
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        response = self.page.goto(self.base_url)
        self.assertEqual(response.status, 200)

    def start_scanner(self):
        self.page.get_by_role("button", name=re.compile("Scan table QR")).click()

    def expect_camera_live(self):
        self.page.wait_for_function("""() => {
          const v = document.getElementById('scannerVideo');
          return v && v.videoWidth > 0 && v.srcObject &&
            v.srcObject.getVideoTracks().some(t => t.readyState === 'live');
        }""")
        self.assertTrue(self.page.locator("#scannerVideo").evaluate("v => v.playsInline && v.muted"),
                        "Inline muted video is required for phone browser camera playback")

    def expect_all_tracks_stopped(self):
        self.page.wait_for_function("""() => cameraStreams.length > 0 &&
          cameraStreams.every(s => s.getTracks().every(t => t.readyState === 'ended'))""")

    def expect_claim_prompt(self, table):
        expect(self.page.locator("#sheetContent h2")).to_have_text(f"Claim Table {table}?")
        expect(self.page.locator("#sheetContent")).to_contain_text(f"Table {table} detected")
        expect(self.page.locator("#selectedName")).to_have_text(table)
        expect(self.page.locator(".tab.active")).to_have_text(f"Zone {table[0]}")
        expect(self.page.locator("#tableGrid .selected")).to_have_text(table)

    def select_map_table(self, table="B3"):
        self.page.locator('.nav [data-page="map"]').click()
        self.page.locator(f'[data-zone="{table[0]}"]').click()
        self.page.get_by_role("button", name=f"Table {table}, available", exact=True).click()
        expect(self.page.locator("#selectedName")).to_have_text(table)
        expect(self.page.locator("#scannerButton")).to_have_text("📷 Scan table QR")

    def expect_verified_claim_prompt(self, table):
        expect(self.page.locator("#sheetContent h2")).to_have_text(f"Claim Table {table}?")
        expect(self.page.locator("#sheetContent")).to_contain_text(f"Table {table} verified ✓")
        expect(self.page.locator("#selectedName")).to_have_text(table)
        expect(self.page.locator("#tableGrid .selected")).to_have_text(table)
        expect(self.page.locator("#claimedTable")).to_have_text("No table")
        expect(self.page.locator("#orderTableTitle")).to_have_text("your table")
        expect(self.page.get_by_role("button", name=f"Claim Table {table}", exact=True)).to_be_enabled()

    def expect_table_mismatch(self, scanned, selected="B3"):
        expect(self.page.locator("#sheetContent")).to_contain_text(
            f"This QR belongs to Table {scanned}, but you selected {selected}."
        )
        expect(self.page.get_by_role("button", name="Scan again", exact=True)).to_be_visible()
        expect(self.page.get_by_role("button", name=f"View {scanned}", exact=True)).to_be_visible()
        expect(self.page.get_by_role("button", name="Cancel scanner", exact=True)).to_be_visible()
        expect(self.page.locator("#selectedName")).to_have_text(selected)
        expect(self.page.locator("#tableGrid .selected")).to_have_text(selected)
        expect(self.page.locator("#claimedTable")).to_have_text("No table")
        expect(self.page.locator("#orderTableTitle")).to_have_text("your table")
        expect(self.page.get_by_role("button", name=re.compile(r"^Claim Table "))).to_have_count(0)
        self.expect_all_tracks_stopped()

    def test_map_real_camera_verifies_selected_tables_then_claims_orders_and_leaves(self):
        for fixture, table, width in (("table-b3", "B3", 390), ("table-b12", "B12", 320)):
            with self.subTest(table=table, width=width):
                self.open_camera_page(fixture, viewport={"width": width, "height": 844})
                self.select_map_table(table)
                self.page.locator("#scannerButton").click()
                self.expect_verified_claim_prompt(table)
                self.expect_all_tracks_stopped()
                self.assertEqual(self.page.evaluate("cameraRequests.length"), 1)
                request = self.page.evaluate("cameraRequests[0]")
                self.assertFalse(request["audio"])
                self.assertIn("environment", str(request["video"]))
                self.page.get_by_role("button", name=f"Claim Table {table}", exact=True).click()
                expect(self.page.locator("#claimedTable")).to_have_text(f"Table {table}")
                self.page.locator('.nav [data-page="orders"]').click()
                cookie = self.page.locator("#menu .item").filter(has_text="Chocolate Cookie")
                cookie.locator(".cookie-select").click()
                self.page.locator("#cartAction").click()
                expect(self.page.locator("#cartSummary")).to_contain_text("Chocolate")
                self.page.locator('.nav [data-page="map"]').click()
                self.page.locator("#selectedAction").click()
                expect(self.page.locator("#claimedTable")).to_have_text("No table")
                expect(self.page.locator("#selectedStatus")).to_have_text("Available now")
                expect(self.page.locator("#scannerButton")).to_be_enabled()

    def test_map_mismatch_preserves_selection_and_url_until_viewing_scanned_table(self):
        for fixture, scanned, status, width in (
            ("table-a2", "A2", "Occupied", 320),
            ("table-b12", "B12", "Available now", 390),
        ):
            with self.subTest(scanned=scanned):
                self.open_camera_page(fixture, viewport={"width": width, "height": 844})
                self.select_map_table()
                original_url = self.page.url
                original_counts = self.page.locator("#availCount").text_content()
                self.page.locator("#scannerButton").click()
                self.expect_table_mismatch(scanned)
                self.assertEqual(self.page.url, original_url)
                expect(self.page.locator("#availCount")).to_have_text(original_counts)
                self.page.get_by_role("button", name=f"View {scanned}", exact=True).click()
                expect(self.page.locator("#modal")).to_be_hidden()
                expect(self.page.locator("section.page.active")).to_have_attribute("id", "map")
                expect(self.page.locator("#selectedName")).to_have_text(scanned)
                expect(self.page.locator(".tab.active")).to_have_text(f"Zone {scanned[0]}")
                expect(self.page.locator("#tableGrid .selected")).to_have_text(scanned)
                expect(self.page.locator("#selectedStatus")).to_have_text(status)
                expect(self.page.locator("#claimedTable")).to_have_text("No table")
                expect(self.page.locator("#availCount")).to_have_text(original_counts)
                if status == "Occupied":
                    expect(self.page.locator("#selectedAction")).to_be_disabled()
                    expect(self.page.locator("#scannerButton")).to_be_disabled()
                else:
                    expect(self.page.locator("#selectedAction")).to_be_enabled()
                    # A new map scan must snapshot this newly selected table,
                    # rather than retaining B3 from the previous mismatch.
                    self.page.locator("#scannerButton").click()
                    self.expect_verified_claim_prompt(scanned)
                    self.expect_all_tracks_stopped()
                    self.assertEqual(self.page.evaluate("cameraRequests.length"), 2)

    def test_map_scan_again_retains_original_table_and_opens_only_one_new_camera(self):
        self.open_camera_page("table-a2")
        self.select_map_table()
        original_url = self.page.url
        self.page.locator("#scannerButton").click()
        self.expect_table_mismatch("A2")
        self.page.get_by_role("button", name="Scan again", exact=True).evaluate(
            "button => { button.click(); button.click(); }"
        )
        self.page.wait_for_function("cameraRequests.length >= 2")
        self.expect_table_mismatch("A2")
        self.assertEqual(self.page.evaluate("cameraRequests.length"), 2)
        self.assertEqual(self.page.url, original_url)
        self.page.get_by_role("button", name="Cancel scanner", exact=True).click()
        expect(self.page.locator("#modal")).to_be_hidden()
        expect(self.page.locator("#scannerButton")).to_be_focused()
        # Home scanning must remain unrestricted after a map verification scan.
        self.page.locator('.nav [data-page="home"]').click()
        self.start_scanner()
        expect(self.page.locator("#sheetContent h2")).to_have_text("Table A2 is occupied")
        expect(self.page.locator("#selectedName")).to_have_text("A2")
        self.expect_all_tracks_stopped()

    def test_map_permission_denied_retry_retains_expected_table(self):
        self.open_camera_page("table-a2", init_script="""(() => {
          let denied = false;
          const recordCamera = navigator.mediaDevices.getUserMedia;
          navigator.mediaDevices.getUserMedia = constraints => {
            if (!denied) {
              denied = true;
              return Promise.reject(new DOMException('Camera denied', 'NotAllowedError'));
            }
            return recordCamera(constraints);
          };
        })()""")
        self.select_map_table()
        original_url = self.page.url
        self.page.locator("#scannerButton").click()
        expect(self.page.locator("#scannerStatus")).to_contain_text(re.compile(r"permission|allow|denied", re.I))
        expect(self.page.get_by_role("button", name="Choose table manually", exact=True)).to_be_visible()
        self.page.get_by_role("button", name="Try camera again", exact=True).click()
        self.expect_table_mismatch("A2")
        self.assertEqual(self.page.url, original_url)
        self.assertEqual(self.page.evaluate("cameraRequests.length"), 1)

    def test_map_cancel_escape_backdrop_and_manual_choice_stop_camera(self):
        self.open_camera_page()
        self.select_map_table()
        for dismiss in ("Cancel scanner", "Escape", "backdrop", "Choose table manually"):
            with self.subTest(dismiss=dismiss):
                self.page.locator("#scannerButton").click()
                self.expect_camera_live()
                if dismiss == "Escape":
                    self.page.keyboard.press("Escape")
                elif dismiss == "backdrop":
                    self.page.locator("#modal").click(position={"x": 2, "y": 2})
                else:
                    self.page.get_by_role("button", name=dismiss, exact=True).click()
                expect(self.page.locator("#modal")).to_be_hidden()
                self.expect_all_tracks_stopped()
                expect(self.page.locator("#selectedName")).to_have_text("B3")
                expect(self.page.locator("#claimedTable")).to_have_text("No table")
                if dismiss != "Choose table manually":
                    expect(self.page.locator("#scannerButton")).to_be_focused()

    def test_map_duplicate_open_and_stale_permission_keep_latest_selected_table(self):
        self.open_camera_page(init_script="""(() => {
          window.pendingCameras = [];
          navigator.mediaDevices.getUserMedia = constraints => {
            cameraRequests.push(constraints);
            return new Promise(resolve => pendingCameras.push(resolve));
          };
          window.resolvedCameras = {};
          window.resolveCamera = async index => {
            const stream = await nativeGetUserMedia({video: true, audio: false});
            cameraStreams.push(stream);
            resolvedCameras[index] = stream;
            pendingCameras[index](stream);
          };
        })()""")
        self.select_map_table()
        button = self.page.locator("#scannerButton")
        button.evaluate("button => { button.click(); button.click(); }")
        self.page.wait_for_function("pendingCameras.length > 0")
        self.assertEqual(self.page.evaluate("pendingCameras.length"), 1)
        self.page.get_by_role("button", name="Cancel scanner", exact=True).click()
        self.select_map_table("B12")
        button.evaluate("button => { button.click(); button.click(); }")
        self.page.wait_for_function("pendingCameras.length === 2")
        self.page.evaluate("resolveCamera(1)")
        self.expect_camera_live()
        self.page.evaluate("resolveCamera(0)")
        self.page.wait_for_function("resolvedCameras[0].getTracks().every(t => t.readyState === 'ended')")
        self.assertTrue(self.page.evaluate("resolvedCameras[1].getTracks().every(t => t.readyState === 'live')"))
        self.expect_camera_live()
        expect(self.page.locator("#selectedName")).to_have_text("B12")
        expect(self.page.locator("#claimedTable")).to_have_text("No table")
        self.assertEqual(self.page.evaluate("cameraRequests.length"), 2)
        self.page.get_by_role("button", name="Cancel scanner", exact=True).click()
        self.expect_all_tracks_stopped()

    def test_real_camera_decodes_public_and_relative_urls_and_claims_tables(self):
        for fixture, table in (("table-b3", "B3"), ("table-b12", "B12")):
            with self.subTest(table=table):
                self.open_camera_page(fixture)
                self.start_scanner()
                self.expect_claim_prompt(table)
                self.expect_all_tracks_stopped()
                requests = self.page.evaluate("cameraRequests")
                self.assertEqual(len(requests), 1)
                self.assertFalse(requests[0].get("audio"), "Scanning must not request the microphone")
                self.assertIn("environment", str(requests[0]["video"]), "Prefer the phone rear camera")
                self.page.get_by_role("button", name=f"Claim Table {table}", exact=True).click()
                expect(self.page.locator("#claimedTable")).to_have_text(f"Table {table}")
                self.page.locator('.nav [data-page="orders"]').click()
                expect(self.page.locator("#orderTableTitle")).to_have_text(f"Table {table}")
                cookie = self.page.locator("#menu .item").filter(has_text="Chocolate Cookie")
                cookie.locator(".cookie-select").click()
                self.page.locator("#cartAction").click()
                expect(self.page.locator("#cartSummary")).to_contain_text("Chocolate")

    def test_real_camera_rejects_invalid_qr_codes_and_keeps_scanning(self):
        for fixture in ("wrong-origin", "unknown-table", "plain-text", "malformed"):
            with self.subTest(fixture=fixture):
                self.open_camera_page(fixture)
                self.start_scanner()
                self.expect_camera_live()
                expect(self.page.locator("#scannerStatus")).to_contain_text(
                    re.compile(r"(invalid|not .*SeatSpot|valid SeatSpot|not recognized|not a SeatSpot)", re.I),
                    timeout=10000,
                )
                expect(self.page.locator("#sheetContent h2")).to_have_text("Scan your table QR")
                self.assertEqual(self.page.url, self.base_url + "/", "Decoded QR contents must not navigate the page")
                self.assertEqual(self.page.evaluate("cameraRequests.length"), 1)
                self.assertTrue(self.page.evaluate(
                    "cameraStreams[0].getVideoTracks().every(t => t.readyState === 'live')"
                ))
                self.page.get_by_role("button", name="Cancel scanner", exact=True).click()
                self.expect_all_tracks_stopped()

    def test_real_camera_respects_an_occupied_table(self):
        self.open_camera_page("table-a2")
        self.start_scanner()
        expect(self.page.locator("#sheetContent h2")).to_contain_text("Table A2")
        expect(self.page.locator("#sheetContent h2")).to_contain_text("occupied")
        expect(self.page.get_by_role("button", name="Claim Table A2", exact=True)).to_be_disabled()
        expect(self.page.locator("#selectedName")).to_have_text("A2")
        expect(self.page.locator(".tab.active")).to_have_text("Zone A")
        self.expect_all_tracks_stopped()

    def test_cancel_escape_backdrop_and_manual_choice_stop_the_camera(self):
        self.open_camera_page()
        for dismiss in ("Cancel scanner", "Escape", "backdrop", "Choose table manually"):
            with self.subTest(dismiss=dismiss):
                self.start_scanner()
                expect(self.page.locator("#sheetContent h2")).to_have_text("Scan your table QR")
                self.expect_camera_live()
                if dismiss == "Escape":
                    self.page.keyboard.press("Escape")
                elif dismiss == "backdrop":
                    self.page.locator("#modal").click(position={"x": 2, "y": 2})
                else:
                    self.page.get_by_role("button", name=dismiss, exact=True).click()
                expect(self.page.locator("#modal")).to_be_hidden()
                self.expect_all_tracks_stopped()
                if dismiss == "Choose table manually":
                    expect(self.page.locator("section.page.active")).to_have_attribute("id", "map")
                else:
                    expect(self.page.get_by_role("button", name=re.compile("Scan table QR"))).to_be_focused()
                self.page.locator('.nav [data-page="home"]').click()

    def test_permission_denied_has_helpful_fallback_and_retry_can_start_camera(self):
        self.open_camera_page(init_script="""(() => {
          let denied = false;
          const recordCamera = navigator.mediaDevices.getUserMedia;
          navigator.mediaDevices.getUserMedia = constraints => {
            if (!denied) {
              denied = true;
              return Promise.reject(new DOMException('Camera denied', 'NotAllowedError'));
            }
            return recordCamera(constraints);
          };
        })()""")
        self.start_scanner()
        expect(self.page.locator("#scannerStatus")).to_contain_text(re.compile(r"permission|allow|denied", re.I))
        expect(self.page.get_by_role("button", name="Choose table manually", exact=True)).to_be_visible()
        self.page.get_by_role("button", name="Try camera again", exact=True).click()
        self.expect_camera_live()
        self.page.get_by_role("button", name="Cancel scanner", exact=True).click()
        self.expect_all_tracks_stopped()

    def test_camera_unavailable_and_insecure_context_offer_manual_fallback(self):
        cases = {
            "missing": "Object.defineProperty(navigator, 'mediaDevices', {value: undefined})",
            "insecure": "Object.defineProperty(window, 'isSecureContext', {value: false})",
            "not-found": "navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('No camera', 'NotFoundError'))",
            "busy": "navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('Camera busy', 'NotReadableError'))",
        }
        for case, script in cases.items():
            with self.subTest(case=case):
                self.open_camera_page(init_script=script)
                self.start_scanner()
                expect(self.page.locator("#scannerStatus")).to_contain_text(
                    re.compile(r"camera|HTTPS|secure|supported", re.I)
                )
                self.page.get_by_role("button", name="Choose table manually", exact=True).click()
                expect(self.page.locator("#modal")).to_be_hidden()
                expect(self.page.locator("section.page.active")).to_have_attribute("id", "map")
                self.page.get_by_role("button", name="Table B3, available", exact=True).click()
                self.page.locator("#selectedAction").click()
                expect(self.page.locator("#claimedTable")).to_have_text("Table B3")

    def test_cancel_while_permission_is_pending_releases_late_stream(self):
        self.open_camera_page(init_script="""(() => {
          window.pendingCameras = [];
          navigator.mediaDevices.getUserMedia = constraints => {
            cameraRequests.push(constraints);
            return new Promise(resolve => pendingCameras.push(resolve));
          };
          window.resolveCamera = async index => {
            const stream = await nativeGetUserMedia({video: true, audio: false});
            cameraStreams.push(stream);
            pendingCameras[index](stream);
          };
        })()""")
        self.start_scanner()
        self.page.wait_for_function("pendingCameras.length === 1")
        self.page.get_by_role("button", name="Cancel scanner", exact=True).click()
        expect(self.page.locator("#modal")).to_be_hidden()
        self.page.evaluate("resolveCamera(0)")
        self.expect_all_tracks_stopped()
        expect(self.page.locator("#modal")).to_be_hidden()

    def test_duplicate_open_and_stale_permission_do_not_replace_current_camera(self):
        self.open_camera_page(init_script="""(() => {
          window.pendingCameras = [];
          navigator.mediaDevices.getUserMedia = constraints => {
            cameraRequests.push(constraints);
            return new Promise(resolve => pendingCameras.push(resolve));
          };
          window.resolvedCameras = {};
          window.resolveCamera = async index => {
            const stream = await nativeGetUserMedia({video: true, audio: false});
            cameraStreams.push(stream);
            resolvedCameras[index] = stream;
            pendingCameras[index](stream);
          };
        })()""")
        button = self.page.get_by_role("button", name=re.compile("Scan table QR"))
        button.evaluate("button => { button.click(); button.click(); }")
        self.page.wait_for_function("pendingCameras.length > 0")
        self.assertEqual(self.page.evaluate("pendingCameras.length"), 1)
        self.page.get_by_role("button", name="Cancel scanner", exact=True).click()
        self.start_scanner()
        self.page.wait_for_function("pendingCameras.length === 2")
        self.page.evaluate("resolveCamera(1)")
        self.expect_camera_live()
        self.page.evaluate("resolveCamera(0)")
        self.page.wait_for_function("resolvedCameras[0].getTracks().every(t => t.readyState === 'ended')")
        self.assertTrue(self.page.evaluate("resolvedCameras[1].getTracks().every(t => t.readyState === 'live')"))
        self.expect_camera_live()
        self.page.get_by_role("button", name="Cancel scanner", exact=True).click()
        self.expect_all_tracks_stopped()

    def test_background_and_pagehide_release_camera(self):
        for event in ("visibilitychange", "pagehide"):
            with self.subTest(event=event):
                self.open_camera_page()
                self.start_scanner()
                self.expect_camera_live()
                if event == "visibilitychange":
                    self.page.evaluate("""() => {
                      Object.defineProperty(document, 'visibilityState', {value: 'hidden', configurable: true});
                      Object.defineProperty(document, 'hidden', {value: true, configurable: true});
                      document.dispatchEvent(new Event('visibilitychange'));
                    }""")
                else:
                    self.page.evaluate("window.dispatchEvent(new Event('pagehide'))")
                self.expect_all_tracks_stopped()

    def test_scanner_video_and_controls_fit_phone_desktop_and_landscape(self):
        self.open_camera_page()
        for width, height in ((320, 640), (1280, 640), (844, 390)):
            with self.subTest(width=width, height=height):
                self.page.set_viewport_size({"width": width, "height": height})
                self.start_scanner()
                self.expect_camera_live()
                modal = self.page.locator("#modal")
                for element in (modal.locator(".sheet"), self.page.locator("#scannerVideo")):
                    bounds = element.bounding_box()
                    self.assertGreaterEqual(bounds["x"], -1)
                    self.assertGreaterEqual(bounds["y"], -1)
                    self.assertLessEqual(bounds["x"] + bounds["width"], width + 1)
                    self.assertLessEqual(bounds["y"] + bounds["height"], height + 1)
                for control in modal.get_by_role("button").all():
                    control.scroll_into_view_if_needed()
                    expect(control).to_be_visible()
                    bounds = control.bounding_box()
                    self.assertGreaterEqual(bounds["x"], -1)
                    self.assertLessEqual(bounds["x"] + bounds["width"], width + 1)
                self.page.get_by_role("button", name="Cancel scanner", exact=True).click()
                self.expect_all_tracks_stopped()


if __name__ == "__main__":
    unittest.main()
