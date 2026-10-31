"""Integration smoke checks against the *deployed* public demo services.

All POSTs use fictional sample data and never submit customer details.
"""
import json
import time
import unittest
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

PUBLIC = "https://pistons-auto-repair-demo.onrender.com"
STAFF = "https://pistons-staff-demo.onrender.com"


def http(url, method="GET", payload=None, headers=None):
    hdrs = {"User-Agent": "PistonsDemoQualityCheck/1.0", **(headers or {})}
    if payload is not None:
        hdrs["Content-Type"] = "application/json"
        payload = json.dumps(payload).encode()
    req = Request(url, data=payload, headers=hdrs, method=method)
    for attempt in range(5):
        try:
            with urlopen(req, timeout=45) as response:
                return response.status, response.read(), response.headers
        except HTTPError as err:
            if err.code not in (500, 502, 503, 504) or attempt == 4:
                return err.code, err.read(), err.headers
        except (URLError, TimeoutError):
            if attempt == 4:
                raise
        time.sleep(min(2**attempt, 10))
    raise AssertionError("Request failed after retries")


def sample_day():
    dt = datetime.now(ZoneInfo("America/Chicago")) + timedelta(days=3)
    while dt.weekday() >= 5:
        dt += timedelta(days=1)
    return dt.strftime("%Y-%m-%d")


class LiveWebsiteSmokeTests(unittest.TestCase):
    def test_live_home_and_private_staff_button(self):
        status, body, _ = http(PUBLIC + "/")
        self.assertEqual(status, 200)
        page = body.decode("utf-8")
        self.assertIn("STAFF LOGIN", page)
        self.assertNotIn('id="ownerView"', page)
        self.assertIn("/status/", page)
        self.assertIn("UNOFFICIAL WEBSITE DEMO", page)

    def test_live_staff_healthy(self):
        status, body, _ = http(STAFF + "/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["environment"], "unofficial_demo")

    def test_live_login_requires_credentials(self):
        status, body, hdr = http(STAFF + "/owner/login")
        self.assertEqual(status, 200)
        self.assertIn(b'name="username"', body)
        self.assertIn(b'name="password"', body)
        self.assertEqual(hdr.get("X-Frame-Options"), "DENY")
        status, body, _ = http(STAFF + "/owner")
        self.assertEqual(status, 200)  # redirected to login
        self.assertIn(b"Staff Demo Login", body)
        self.assertNotIn(b"Customer message examples", body)

    def test_live_cross_origin_preflight(self):
        status, _, hdr = http(STAFF + "/api/appointments", method="OPTIONS", headers={
            "Origin": PUBLIC, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"
        })
        self.assertEqual(status, 204)
        self.assertEqual(hdr.get("Access-Control-Allow-Origin"), PUBLIC)

    def test_live_booking_pending_status_and_readable_page(self):
        request = {"name":"CI Example Customer", "vehicle":"Imaginary Vehicle", "date":sample_day(),
                   "time":"10:30", "issue":"Fictional engine concern for demo testing"}
        code, body, _ = http(STAFF + "/api/appointments", method="POST", payload=request, headers={"Origin":PUBLIC})
        self.assertEqual(code, 201, body)
        reference = json.loads(body)["id"]
        self.assertTrue(reference.startswith("DEMO-"))
        code, body, _ = http(STAFF + "/api/status/" + reference)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["status"], "Pending")
        code, page, _ = http(STAFF + "/status/" + reference)
        self.assertEqual(code, 200)
        self.assertIn(b"Sample appointment status", page)
        self.assertIn(b"Pending", page)

    def test_live_sample_message_acceptance(self):
        code, body, _ = http(STAFF + "/api/messages", method="POST",
            payload={"name":"CI Sample Client", "message":"Automated sample: fictional appointment question"},
            headers={"Origin":PUBLIC})
        self.assertEqual(code, 201, body)
        self.assertTrue(json.loads(body)["demo"])

    def test_live_disallowed_origin_rejected(self):
        code, body, _ = http(STAFF + "/api/messages", method="POST",
            payload={"name":"CI Example", "message":"Fictional testing request"},
            headers={"Origin":"https://other.example"})
        self.assertEqual(code, 403)


if __name__ == "__main__":
    unittest.main()
