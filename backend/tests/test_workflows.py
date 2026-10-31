import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from werkzeug.security import generate_password_hash

TEST_DB = tempfile.NamedTemporaryFile(prefix="pistons_test_", suffix=".db", delete=False)
TEST_DB.close()
os.environ["DEMO_DB_PATH"] = TEST_DB.name
os.environ["SESSION_SECRET"] = "unit-test-only-not-production"
os.environ["OWNER_PASSWORD_HASH"] = generate_password_hash("OwnerDemoPass!", method="pbkdf2:sha256:1000")
os.environ["DEVELOPER_PASSWORD_HASH"] = generate_password_hash("DeveloperDemoPass!", method="pbkdf2:sha256:1000")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app as website

ORIGIN = {"Origin": website.PUBLIC_ORIGIN}


def weekday(days=3):
    d = datetime.now(ZoneInfo("America/Chicago")) + timedelta(days=days)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def sample(**overrides):
    data = dict(name="Example Client", vehicle="Example Truck", date=weekday(), time="10:00", issue="Sample vehicle does not start")
    data.update(overrides)
    return data


class PistonsWebsiteTests(unittest.TestCase):
    def setUp(self):
        website.ATTEMPTS.clear()
        with website.connect() as db:
            db.execute("DELETE FROM appointments")
            db.execute("DELETE FROM messages")
        self.client = website.app.test_client()

    def book(self, client=None, **overrides):
        return (client or self.client).post("/api/appointments", json=sample(**overrides), headers=ORIGIN)

    def login(self, client=None, username="owner", password="OwnerDemoPass!"):
        client = client or self.client
        login_page = client.get("/owner/login")
        self.assertEqual(login_page.status_code, 200)
        with client.session_transaction() as sess:
            token = sess["csrf"]
        result = client.post("/owner/login", data=dict(username=username, password=password, csrf=token))
        return result, token

    def csrf(self, client=None):
        with (client or self.client).session_transaction() as sess:
            return sess["csrf"]

    def decide(self, reference, status, client=None, token=None):
        client = client or self.client
        token = token or self.csrf(client)
        return client.post("/owner/decision", data=dict(id=reference, status=status, csrf=token))

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["database"], "temporary")

    def test_private_dashboard_requires_login(self):
        self.assertEqual(self.client.get("/owner").status_code, 302)
        self.assertIn("/owner/login", self.client.get("/owner").headers["Location"])

    def test_owner_password_and_dashboard(self):
        result, _ = self.login()
        self.assertEqual(result.status_code, 302)
        page = self.client.get("/owner")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Signed in as", page.data)
        self.assertIn(b"owner", page.data)

    def test_developer_password_and_dashboard(self):
        result, _ = self.login(username="developer", password="DeveloperDemoPass!")
        self.assertEqual(result.status_code, 302)
        self.assertEqual(self.client.get("/owner").status_code, 200)
        self.assertIn(b"developer", self.client.get("/owner").data)

    def test_wrong_password_and_unknown_username(self):
        self.assertEqual(self.login(username="owner", password="wrong")[0].status_code, 200)
        self.assertEqual(self.client.get("/owner").status_code, 302)
        self.assertEqual(self.login(username="unknown", password="DeveloperDemoPass!")[0].status_code, 200)
        self.assertEqual(self.client.get("/owner").status_code, 302)

    def test_login_csrf_mandatory(self):
        self.client.get("/owner/login")
        result = self.client.post("/owner/login", data=dict(username="owner", password="OwnerDemoPass!", csrf="wrong"))
        self.assertEqual(result.status_code, 403)

    def test_anonymous_cannot_approve(self):
        reference = self.book().json["id"]
        self.assertEqual(self.decide(reference, "Approved", token="wrong").status_code, 302)
        self.assertEqual(self.client.get("/api/status/" + reference).json["status"], "Pending")

    def test_appointment_submit_pending(self):
        response = self.book()
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json["id"].startswith("DEMO-"))
        self.assertEqual(response.json["status"], "Pending")
        self.assertEqual(self.client.get("/api/status/" + response.json["id"]).json["status"], "Pending")

    def test_approve_from_another_client_and_status_page(self):
        customer = self.client
        owner = website.app.test_client()
        reference = self.book(client=customer).json["id"]
        self.assertEqual(self.login(owner)[0].status_code, 302)
        self.assertEqual(self.decide(reference, "Approved", client=owner).status_code, 303)
        self.assertEqual(customer.get("/api/status/" + reference).json["status"], "Approved")
        html = customer.get("/status/" + reference)
        self.assertEqual(html.status_code, 200)
        self.assertIn(b"Approved", html.data)
        self.assertIn(b"not an appointment", html.data)

    def test_decline_and_reset(self):
        reference = self.book().json["id"]
        self.login(username="developer", password="DeveloperDemoPass!")
        self.assertEqual(self.decide(reference, "Declined").status_code, 303)
        self.assertEqual(self.client.get("/api/status/" + reference).json["status"], "Declined")
        self.assertEqual(self.decide(reference, "Pending").status_code, 303)
        self.assertEqual(self.client.get("/api/status/" + reference).json["status"], "Pending")

    def test_prevent_double_booking_same_slot(self):
        a = self.book(name="Example First").json["id"]
        b = self.book(name="Example Second").json["id"]
        self.login()
        self.assertIn("approved", self.decide(a, "Approved").headers["Location"])
        self.assertIn("conflict", self.decide(b, "Approved").headers["Location"])
        self.assertEqual(self.client.get("/api/status/" + b).json["status"], "Pending")

    def test_allow_different_slots(self):
        a = self.book().json["id"]
        b = self.book(time="11:00").json["id"]
        self.login()
        self.assertIn("approved", self.decide(a, "Approved").headers["Location"])
        self.assertIn("approved", self.decide(b, "Approved").headers["Location"])

    def test_decision_csrf_protection(self):
        reference = self.book().json["id"]
        self.login()
        self.assertEqual(self.decide(reference, "Approved", token="bad-token").status_code, 403)
        self.assertEqual(self.client.get("/api/status/" + reference).json["status"], "Pending")

    def test_reject_invalid_decision(self):
        reference = self.book().json["id"]
        self.login()
        self.assertEqual(self.decide(reference, "Canceled").status_code, 400)

    def test_reject_weekend(self):
        d = datetime.now(ZoneInfo("America/Chicago")) + timedelta(days=7)
        while d.weekday() != 5:
            d += timedelta(days=1)
        self.assertEqual(self.book(date=d.strftime("%Y-%m-%d")).status_code, 400)

    def test_reject_past_date(self):
        day = (datetime.now(ZoneInfo("America/Chicago")) - timedelta(days=3)).strftime("%Y-%m-%d")
        self.assertEqual(self.book(date=day).status_code, 400)

    def test_reject_invalid_hours(self):
        self.assertEqual(self.book(time="07:30").status_code, 400)
        self.assertEqual(self.book(time="17:00").status_code, 400)
        self.assertEqual(self.book(time="10:15").status_code, 400)

    def test_reject_real_contact_data(self):
        self.assertEqual(self.book(name="Test person@example.com").status_code, 400)
        self.assertEqual(self.book(issue="Call me at 555-121-9876").status_code, 400)

    def test_reject_invalid_and_long_payload(self):
        self.assertEqual(self.client.post("/api/appointments", json={"broken":"json"}, headers=ORIGIN).status_code, 400)
        self.assertEqual(self.book(issue="x"*701).status_code, 400)

    def test_reject_unapproved_origin(self):
        r = self.client.post("/api/appointments", json=sample(), headers={"Origin":"https://evil.example"})
        self.assertEqual(r.status_code, 403)
        r = self.client.post("/api/messages", json=dict(name="Sample", message="Test only message"))
        self.assertEqual(r.status_code, 403)

    def test_message_reaches_authenticated_staff(self):
        r = self.client.post("/api/messages", json=dict(name="Sample Client", message="Sample message only"), headers=ORIGIN)
        self.assertEqual(r.status_code, 201)
        owner = website.app.test_client()
        self.login(owner)
        page = owner.get("/owner")
        self.assertIn(b"Sample message only", page.data)
        self.assertIn(b"Sample Client", page.data)

    def test_message_rejects_real_contacts(self):
        r = self.client.post("/api/messages", json=dict(name="Sample", message="Call 479-647-2675"), headers=ORIGIN)
        self.assertEqual(r.status_code, 400)

    def test_html_escapes_user_content(self):
        payload = "<script>alert(1)</script>"
        r = self.client.post("/api/messages", json=dict(name="Sample", message=payload), headers=ORIGIN)
        self.assertEqual(r.status_code, 201)
        self.login()
        page = self.client.get("/owner")
        self.assertNotIn(b"<script>alert(1)</script>", page.data)
        self.assertIn(b"&lt;script&gt;", page.data)

    def test_logout_ends_session(self):
        self.login()
        self.assertEqual(self.client.post("/owner/logout", data={"csrf":self.csrf()}).status_code, 303)
        self.assertEqual(self.client.get("/owner").status_code, 302)

    def test_public_status_has_no_customer_data(self):
        reference = self.book(name="Example Private Name").json["id"]
        response = self.client.get("/api/status/" + reference)
        self.assertNotIn("name", response.json)
        self.assertEqual(response.json["demo"], True)
        self.assertNotIn(b"Example Private Name", self.client.get("/status/" + reference).data)

    def test_security_headers(self):
        resp = self.client.get("/owner/login")
        self.assertEqual(resp.headers.get("X-Frame-Options"), "DENY")
        self.assertIn("no-store", resp.headers.get("Cache-Control"))
        self.assertIn("HttpOnly", resp.headers.get("Set-Cookie"))
        self.assertIn("Strict-Transport-Security", resp.headers)

    def test_cross_origin_cors_preflight(self):
        result = self.client.options("/api/messages", headers={"Origin":website.PUBLIC_ORIGIN, "Access-Control-Request-Method":"POST"})
        self.assertEqual(result.status_code, 204)
        self.assertEqual(result.headers.get("Access-Control-Allow-Origin"), website.PUBLIC_ORIGIN)

    def test_appointment_rate_limit(self):
        for _ in range(15):
            self.assertEqual(self.book().status_code, 201)
        self.assertEqual(self.book().status_code, 429)

if __name__ == "__main__":
    unittest.main()
