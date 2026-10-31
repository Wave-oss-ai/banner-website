"""Browser UI regression checks for the unofficial Pistons website demo."""
import json
import os
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        return


class BrowserSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = partial(QuietHandler, directory=str(ROOT))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.origin = "http://127.0.0.1:" + str(cls.server.server_port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1300, "height": 850})
        self.page = self.context.new_page()
        self.page.goto(self.origin, wait_until="domcontentloaded")
        self.page.locator("#bookingForm").wait_for()

    def tearDown(self):
        self.context.close()

    def test_page_has_book_and_message_forms(self):
        self.assertIn("Pistons Auto Repair", self.page.title())
        self.assertEqual(self.page.locator("#bookingForm").count(), 1)
        self.assertEqual(self.page.locator("#messageForm").count(), 1)
        self.assertEqual(self.page.locator("#ownerView").count(), 0)
        self.assertEqual(self.page.locator("#ownerSwitch").inner_text(), "STAFF LOGIN")
        self.assertIn("UNOFFICIAL WEBSITE DEMO", self.page.locator(".noticebar").inner_text())

    def test_sample_message_post_and_confirmation(self):
        requests = []
        def respond(route):
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers={"Access-Control-Allow-Origin":self.origin, "Access-Control-Allow-Methods":"POST, OPTIONS", "Access-Control-Allow-Headers":"content-type"})
            else:
                requests.append(json.loads(route.request.post_data))
                route.fulfill(status=201, content_type="application/json", headers={"Access-Control-Allow-Origin":self.origin}, body='{"id":"MSG-MOCK","demo":true}')
        self.page.route("**/api/messages", respond)
        self.page.locator("#msgName").fill("Sample Client")
        self.page.locator("#msgText").fill("A fictional question from the automated browser test.")
        self.page.locator("#messageForm button[type=submit]").click()
        self.page.locator("#messageFeedback").get_by_text("Sample message saved", exact=False).wait_for()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["name"], "Sample Client")
        self.assertEqual(requests[0]["message"], "A fictional question from the automated browser test.")

    def test_booking_post_and_readable_status_link(self):
        requests = []
        def respond(route):
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers={"Access-Control-Allow-Origin":self.origin,"Access-Control-Allow-Methods":"POST, OPTIONS","Access-Control-Allow-Headers":"content-type"})
            else:
                requests.append(json.loads(route.request.post_data))
                route.fulfill(status=201, content_type="application/json", headers={"Access-Control-Allow-Origin":self.origin}, body='{"id":"DEMO-EXAMPLE123456","status":"Pending","demo":true}')
        self.page.route("**/api/appointments", respond)
        self.page.locator("#bookingForm button[type=submit]").click()
        self.page.locator("#bookingFeedback").get_by_text("Sample request", exact=False).wait_for()
        link = self.page.locator("#bookingFeedback a")
        self.assertEqual(link.count(), 1)
        self.assertIn("/status/DEMO-EXAMPLE123456", link.get_attribute("href"))
        self.assertEqual(len(requests), 1)
        self.assertTrue(requests[0]["name"])
        self.assertEqual(requests[0]["time"], "10:00")

    def test_booking_error_is_shown_and_submit_reenabled(self):
        def respond(route):
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers={"Access-Control-Allow-Origin":self.origin,"Access-Control-Allow-Methods":"POST, OPTIONS","Access-Control-Allow-Headers":"content-type"})
            else:
                route.fulfill(status=400, content_type="application/json", headers={"Access-Control-Allow-Origin":self.origin}, body='{"error":"Choose a future date."}')
        self.page.route("**/api/appointments", respond)
        button = self.page.locator("#bookingForm button[type=submit]")
        button.click()
        self.page.locator("#bookingFeedback").get_by_text("Choose a future date.", exact=False).wait_for()
        self.assertTrue(button.is_enabled())

    def test_staff_login_navigation(self):
        self.page.route("https://pistons-staff-demo.onrender.com/owner/login", lambda route: route.fulfill(
            status=200, content_type="text/html", body="<html><title>Staff login</title><h1>Staff Login</h1></html>"))
        self.page.locator("#ownerSwitch").click()
        self.page.wait_for_url("https://pistons-staff-demo.onrender.com/owner/login")
        self.assertIn("Staff login", self.page.title())

    def test_mobile_no_horizontal_overflow(self):
        self.page.set_viewport_size({"width":375,"height":812})
        self.page.wait_for_timeout(100)
        measures = self.page.evaluate("({screen:window.innerWidth,scroll:document.documentElement.scrollWidth})")
        self.assertLessEqual(measures["scroll"], measures["screen"] + 2)
        self.assertTrue(self.page.locator("#bookingForm").count() > 0)
        self.assertTrue(self.page.locator(".mobilebar").is_visible())

if __name__ == "__main__":
    unittest.main()
