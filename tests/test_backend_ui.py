"""Browser integration against the actual API, SQL schema and PostgREST.

Requires Docker, Chromium and Python Playwright. Supabase Auth alone is a local
fixture; database permissions, transactions and application requests are real.
"""
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


class BackendUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = subprocess.Popen(['node', 'tests/local-stack.mjs'], cwd=ROOT,
                                     stdout=subprocess.PIPE, text=True)
        cls.urls = json.loads(cls.stack.stdout.readline())
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True, executable_path=
            os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium'), args=['--no-sandbox'])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.stack.terminate()
        cls.stack.wait(timeout=30)
        cls.stack.stdout.close()

    def fixture(self, action, body=None):
        with urlopen(Request(self.urls['fixture']+'/__test__/'+action,
                             data=json.dumps(body or {}).encode(),
                             headers={'Content-Type':'application/json'})) as response:
            return json.load(response)

    def setUp(self):
        self.fixture('reset')
        self.contexts = []
        self.errors = []

    def tearDown(self):
        for context in self.contexts:
            context.close()
        self.assertEqual(self.errors, [])

    def page(self, path='/', width=390, name='Test visitor'):
        context = self.browser.new_context(viewport={'width':width,'height':844})
        self.contexts.append(context)
        page = context.new_page()
        page.set_default_timeout(10000)
        page.on('pageerror', lambda error:self.errors.append(str(error)))
        page.goto(self.urls['base']+path)
        if not path.startswith('/admin') and name is not None:
            page.locator('#customerName').fill(name)
            page.locator('#welcomeContinue').click()
            expect(page.locator('#welcomeScreen')).to_be_hidden()
        return page

    def orders(self, page):
        page.locator('.nav [data-page="orders"]').click()
        expect(page.locator('[data-stock="choc"]')).to_contain_text('remaining')

    def login(self, page):
        page.locator('#staffEmail').fill('staff@example.test')
        page.locator('#staffPassword').fill('test-only-staff-password')
        page.get_by_role('button',name='Sign in',exact=True).click()
        expect(page.locator('#staffDashboard')).to_be_visible()

    def test_shared_inventory_single_cookie_and_persistent_order(self):
        self.fixture('stock', {'cookie_id':'choc','quantity':1})
        first=self.page('/?table=B3')
        first.get_by_role('button',name='Claim Table B3',exact=True).click()
        second=self.page()
        self.orders(first)
        self.orders(second)
        expect(first.locator('.plus,.circlebtn')).to_have_count(0)
        expect(first.locator('#menu .item b')).to_have_text(['Chocolate Cookie', 'Original Cookie', 'Red Velvet Cookie'])
        expect(first.locator('[data-cookie="matcha"] .cookie')).to_have_class('cookie original')
        first.locator('[data-cookie="choc"] .cookie-select').click()
        first.locator('#cartAction').click()
        expect(first.locator('#cartSummary')).to_contain_text('Chocolate')
        expect(first.locator('#cartSummary')).to_contain_text('Table B3')
        expect(first.locator('#menu button:disabled')).to_have_count(3)
        expect(second.locator('[data-stock="choc"]')).to_have_text('0 remaining')
        expect(second.locator('[data-cookie="choc"] .cookie-select')).to_have_text('Sold out')
        expect(second.locator('[data-cookie="choc"] .cookie-select')).to_be_disabled()
        second.locator('[data-cookie="matcha"] .cookie-select').click()
        second.locator('#cartAction').click()
        expect(second.locator('#cartSummary')).to_contain_text('Original')
        expect(first.locator('[data-stock="matcha"]')).to_have_text('4 remaining')
        first.reload()
        # The table prompt is the existing local map behavior, not an ordering reset.
        if first.locator('#modal').is_visible():
            first.get_by_role('button',name='Not now',exact=True).click()
        self.orders(first)
        expect(first.locator('#cartSummary')).to_contain_text('Chocolate')
        expect(first.locator('#menu button:disabled')).to_have_count(3)
        first.locator('.nav [data-page="profile"]').click()
        first.get_by_role('button',name='Reset prototype',exact=True).click()
        self.orders(first)
        expect(first.locator('#menu button:disabled')).to_have_count(3)

    def test_staff_inventory_orders_and_status_update_customer(self):
        staff=self.page('/admin')
        self.login(staff)
        expect(staff.locator('#staffInventory h3')).to_have_text(['Chocolate', 'Original', 'Red Velvet'])
        stock=staff.locator('[data-cookie="red"]')
        stock.locator('[name="quantity"]').fill('2')
        stock.get_by_role('button',name='Set stock',exact=True).click()
        expect(stock.locator('.stock-count')).to_have_text('2 remaining')
        stock.get_by_role('button',name='+1',exact=True).click()
        expect(stock.locator('.stock-count')).to_have_text('3 remaining')
        customer=self.page('/?table=B12')
        customer.get_by_role('button',name='Claim Table B12',exact=True).click()
        self.orders(customer)
        customer.locator('[data-cookie="red"] .cookie-select').click()
        customer.locator('#cartAction').click()
        row=staff.locator('#staffOrders tr')
        expect(row).to_have_count(1)
        expect(row.locator('td').first).to_have_text('Test visitor')
        self.assertNotRegex(row.inner_text(), r'[0-9a-f]{8}-[0-9a-f]{4}-')
        expect(row).to_contain_text('B12')
        expect(row).to_contain_text('Red Velvet')
        expect(row.locator('td').nth(4)).not_to_be_empty()
        for status in ['Preparing','Ready','New','Ready']:
            row.get_by_role('button',name='Mark order',exact=False).filter(has_text=status).click()
            expect(row.locator('.order-status')).to_have_text(status)
            expect(customer.locator('#cartSummary')).to_contain_text(status)
        customer.locator('#cartAction').click()
        expect(customer.locator('#cartAction')).to_have_text('Collected ✓')
        expect(customer.locator('#menu button:disabled')).to_have_count(3)
        stock.locator('[name="active"]').uncheck()
        stock.get_by_role('button',name='Set stock',exact=True).click()
        other=self.page()
        self.orders(other)
        expect(other.locator('[data-cookie="red"] .cookie-select')).to_have_text('Unavailable')
        expect(other.locator('[data-cookie="red"] .cookie-select')).to_be_disabled()
        staff.get_by_role('button',name='Sign out',exact=True).click()
        expect(staff.locator('#staffLogin')).to_be_visible()

    def test_mobile_and_desktop_customer_staff_layout(self):
        for width in [320,390,1280]:
            customer=self.page(width=width)
            self.orders(customer)
            staff=self.page('/admin',width=width)
            self.login(staff)
            for page in [customer,staff]:
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'))
            self.contexts[-1].close()
            self.contexts[-2].close()

    def test_staff_account_requires_allowlist(self):
        staff=self.page('/admin')
        staff.locator('#staffEmail').fill('visitor@example.test')
        staff.locator('#staffPassword').fill('test-only-visitor-password')
        staff.get_by_role('button',name='Sign in',exact=True).click()
        expect(staff.locator('#staffMessage')).to_contain_text('does not have staff access')
        expect(staff.locator('#staffDashboard')).to_be_hidden()

    def test_unavailable_backend_pauses_orders_and_preserves_map(self):
        page=self.page()
        page.route('**/api/seatspot?*', lambda route: route.fulfill(status=503,
                   content_type='application/json', body='{"error":{"code":"SETUP_REQUIRED","message":"Ordering is not available yet."}}'))
        page.reload()
        page.locator('.nav [data-page="orders"]').click()
        expect(page.locator('#inventoryStatus')).to_contain_text('Ordering is paused')
        expect(page.locator('#cartAction')).to_be_disabled()
        expect(page.locator('#menu button:disabled')).to_have_count(3)
        expect(page.locator('#retryInventory')).to_be_visible()
        page.locator('.nav [data-page="map"]').click()
        page.get_by_role('button',name='Table B3, available',exact=True).click()
        expect(page.locator('#selectedName')).to_have_text('B3')
        expect(page.locator('#scannerButton')).to_be_enabled()
        page.unroute('**/api/seatspot?*')
        page.locator('.nav [data-page="orders"]').click()
        page.locator('#retryInventory').click()
        expect(page.locator('#inventoryStatus')).to_contain_text('Stock is shared')
        expect(page.locator('#menu button:enabled')).to_have_count(3)

    def test_welcome_required_qr_preserved_and_name_survives_reload_leave_and_reset(self):
        page=self.page('/?table=B3',name=None)
        expect(page.locator('#welcomeScreen')).to_be_visible()
        expect(page.locator('#seatspotApp')).to_be_hidden()
        expect(page.locator('#customerName')).to_have_attribute('maxlength','30')
        page.locator('#customerName').fill('   ')
        page.locator('#welcomeContinue').click()
        expect(page.locator('#welcomeMessage')).to_contain_text('Enter a name')
        expect(page.locator('#seatspotApp')).to_be_hidden()
        page.locator('#customerName').fill('Alyssa')
        page.locator('#welcomeContinue').click()
        expect(page.locator('#welcomeScreen')).to_be_hidden()
        expect(page.get_by_role('heading',name='Claim Table B3?',exact=True)).to_be_visible()
        page.get_by_role('button',name='Claim Table B3',exact=True).click()
        self.orders(page)
        page.locator('[data-cookie="matcha"] .cookie-select').click()
        page.locator('#cartAction').click()
        expect(page.locator('#cartSummary')).to_contain_text('Alyssa')
        expect(page.locator('#cartSummary')).to_contain_text('Table B3')
        page.locator('.nav [data-page="map"]').click()
        page.locator('#selectedAction').click()
        page.locator('.nav [data-page="profile"]').click()
        page.get_by_role('button',name='Reset prototype',exact=True).click()
        self.orders(page)
        expect(page.locator('#menu button:disabled')).to_have_count(3)
        page.reload()
        expect(page.locator('#welcomeScreen')).to_be_hidden()
        if page.locator('#modal').is_visible():
            page.get_by_role('button',name='Not now',exact=True).click()
        self.orders(page)
        expect(page.locator('#cartSummary')).to_contain_text('Alyssa')
        expect(page.locator('#menu button:disabled')).to_have_count(3)
        # A separate tab restores the server name even with sessionStorage cleared.
        tab=page.context.new_page()
        tab.goto(self.urls['base'])
        expect(tab.locator('#welcomeScreen')).to_be_hidden()
        expect(tab.locator('#seatspotApp')).to_be_visible()

    def test_name_is_literal_text_on_customer_and_staff_views_and_no_table_is_dash(self):
        name='<img src=x onerror=alert(1)>'
        page=self.page(name=name)
        self.orders(page)
        page.locator('[data-cookie="choc"] .cookie-select').click()
        page.locator('#cartAction').click()
        expect(page.locator('#cartSummary')).to_contain_text(name)
        expect(page.locator('#cartSummary img')).to_have_count(0)
        staff=self.page('/admin')
        self.login(staff)
        row=staff.locator('#staffOrders tr')
        expect(row.locator('td').nth(0)).to_have_text(name)
        expect(row.locator('td').nth(1)).to_have_text('—')
        expect(row.locator('td').nth(3)).to_have_text('1')
        expect(row.locator('img')).to_have_count(0)
        self.assertNotRegex(row.inner_text(),r'[0-9a-f]{8}-[0-9a-f]{4}-')
        for button in row.get_by_role('button').all():
            self.assertNotRegex(button.get_attribute('aria-label'),r'[0-9a-f]{8}-[0-9a-f]{4}-')

    def test_new_visitor_requires_name_when_storage_is_unavailable(self):
        page=self.page(name=None)
        page.add_init_script("(() => {Storage.prototype.setItem=()=>{throw new Error('disabled')};Storage.prototype.getItem=()=>{throw new Error('disabled')};})();")
        page.reload()
        page.locator('#customerName').fill('Guest name')
        page.locator('#welcomeContinue').click()
        expect(page.locator('#welcomeScreen')).to_be_hidden()
        page.reload()
        expect(page.locator('#welcomeScreen')).to_be_hidden()
        self.orders(page)
        expect(page.locator('#cartAction')).to_be_disabled()
