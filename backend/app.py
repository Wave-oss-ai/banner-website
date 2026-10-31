import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from collections import defaultdict, deque
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "")
if not app.secret_key:
    raise RuntimeError("SESSION_SECRET must be configured before starting the server")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=18000,
    MAX_CONTENT_LENGTH=8192,
)
# Separate accounts for the shop owner and website developer. The old shared
# password is never accepted when these are configured.
USER_HASHES = {
    "owner": os.environ.get("OWNER_PASSWORD_HASH", ""),
    "developer": os.environ.get("DEVELOPER_PASSWORD_HASH", ""),
}
if not all(USER_HASHES.values()):
    raise RuntimeError("OWNER_PASSWORD_HASH and DEVELOPER_PASSWORD_HASH must be configured")
PUBLIC_ORIGIN = "https://pistons-auto-repair-demo.onrender.com"
DATABASE_PATH = os.environ.get("DEMO_DB_PATH", "/tmp/pistons_owner_demo.sqlite3")
TZ = ZoneInfo("America/Chicago")
ATTEMPTS = defaultdict(deque)

def connect():
    db = sqlite3.connect(DATABASE_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=5000")
    return db

def create_tables():
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS appointments (
            id TEXT PRIMARY KEY, name TEXT NOT NULL,
            vehicle TEXT NOT NULL, date TEXT NOT NULL, time TEXT NOT NULL,
            issue TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Pending',
            created_at TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, body TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
create_tables()

def rate_limit(group, maximum, interval):
    key = (group, request.remote_addr or "unknown")
    now = time.monotonic()
    hits = ATTEMPTS[key]
    while hits and now - hits[0] > interval:
        hits.popleft()
    if len(hits) >= maximum:
        return True
    hits.append(now)
    return False

def check_demo_text(text):
    # Public preview should never invite users to send real names, emails, or phone numbers.
    return not re.search(
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}",
        text,
    )

@app.after_request
def add_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; img-src 'self' data:; form-action 'self'; "
        "base-uri 'self'; frame-ancestors 'none'"
    )
    if request.path.startswith("/api/") and request.headers.get("Origin") == PUBLIC_ORIGIN:
        response.headers["Access-Control-Allow-Origin"] = PUBLIC_ORIGIN
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Vary"] = "Origin"
    return response

@app.get("/health")
def health():
    return jsonify(status="ok", environment="unofficial_demo", database="temporary")

@app.get("/")
def home():
    return redirect(url_for("owner_login"))

@app.route("/api/appointments", methods=["POST", "OPTIONS"])
def appointment_submission():
    if request.method == "OPTIONS":
        return ("", 204)
    if request.headers.get("Origin") != PUBLIC_ORIGIN:
        return jsonify(error="Only the public demo site can submit sample requests."), 403
    if rate_limit("appointments", 15, 300):
        return jsonify(error="Too many sample requests. Please try later."), 429
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Expected a JSON request."), 400
    values = []
    for field, limit in (("name", 80), ("vehicle", 100), ("date", 10), ("time", 5), ("issue", 700)):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            return jsonify(error="Complete the sample request fields."), 400
        values.append(value.strip())
    name, vehicle, day, clock, issue = values
    if len(issue) < 5 or not check_demo_text(" ".join(values)):
        return jsonify(error="Use fictional sample details only. No phone numbers or emails."), 400
    try:
        requested = datetime.strptime(day + " " + clock, "%Y-%m-%d %H:%M")
    except ValueError:
        return jsonify(error="Invalid date or time."), 400
    if requested.replace(tzinfo=TZ) <= datetime.now(TZ):
        return jsonify(error="Choose a future date and time."), 400
    if requested.weekday() >= 5 or requested.hour < 8 or requested.hour > 16 or requested.minute not in (0, 30) or (requested.hour == 16 and requested.minute > 30):
        return jsonify(error="Select a weekday from 8:00 AM through 4:30 PM."), 400
    reference = "DEMO-" + secrets.token_urlsafe(12)
    with connect() as db:
        db.execute(
            "INSERT INTO appointments(id,name,vehicle,date,time,issue,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (reference, name, vehicle, day, clock, issue, "Pending", datetime.now(timezone.utc).isoformat()),
        )
    return jsonify(id=reference, status="Pending", demo=True), 201

@app.route("/api/messages", methods=["POST", "OPTIONS"])
def message_submission():
    if request.method == "OPTIONS":
        return ("", 204)
    if request.headers.get("Origin") != PUBLIC_ORIGIN:
        return jsonify(error="Only the public demo site can submit sample messages."), 403
    if rate_limit("messages", 15, 300):
        return jsonify(error="Too many sample messages. Please try later."), 429
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Expected JSON."), 400
    name, body = data.get("name"), data.get("message")
    if not isinstance(name, str) or not isinstance(body, str) or not (1 <= len(name.strip()) <= 80) or not (5 <= len(body.strip()) <= 700):
        return jsonify(error="Enter a sample name and message."), 400
    if not check_demo_text(name + " " + body):
        return jsonify(error="Demo only. Do not enter real contact information."), 400
    reference = "MSG-" + secrets.token_urlsafe(9)
    with connect() as db:
        db.execute(
            "INSERT INTO messages(id,name,body,created_at) VALUES(?,?,?,?)",
            (reference, name.strip(), body.strip(), datetime.now(timezone.utc).isoformat()),
        )
    return jsonify(id=reference, demo=True), 201

@app.get("/api/status/<reference>")
def public_status(reference):
    if not re.fullmatch(r"DEMO-[A-Za-z0-9_-]{12,30}", reference):
        return jsonify(error="Not found"), 404
    with connect() as db:
        row = db.execute("SELECT status FROM appointments WHERE id=?", (reference,)).fetchone()
    if row is None:
        return jsonify(error="Not found"), 404
    return jsonify(status=row["status"], demo=True)


@app.get("/status/<reference>")
def status_page(reference):
    if not re.fullmatch(r"DEMO-[A-Za-z0-9_-]{12,30}", reference):
        return "Sample request not found.", 404
    with connect() as db:
        row = db.execute("SELECT status FROM appointments WHERE id=?", (reference,)).fetchone()
    if row is None:
        return render_template_string("""<!doctype html><title>Sample request missing</title>
        <body style="font-family:system-ui;background:#10151b;color:white;padding:40px">
        <h1>Sample request not found</h1><p>The free demonstration server may have reset.</p>
        <a style="color:#ff8d7d" href="https://pistons-auto-repair-demo.onrender.com">Back to demo website</a></body>"""), 404
    return render_template_string("""<!doctype html><html lang="en"><head>
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Appointment Status · Sample Only</title></head>
    <body style="font-family:system-ui;background:#11161e;color:white;margin:0">
    <main style="max-width:600px;margin:45px auto;padding:24px">
    <p style="color:#f7b9a1;font-weight:700">UNOFFICIAL TEST ONLY</p>
    <h1>Sample appointment status</h1>
    <div style="background:#253041;padding:22px;border-radius:10px">
    <p>Your sample request is currently:</p>
    <h2 style="color:#c5ffd7">{{ status }}</h2></div>
    <p>This is not an appointment with Pistons Auto Repair. Records may reset.</p>
    <p><a style="color:#ff9384" href="/status/{{ reference }}">Refresh status</a> ·
    <a style="color:#ff9384" href="https://pistons-auto-repair-demo.onrender.com">Return to website</a></p>
    </main></body></html>""", status=row["status"], reference=reference)

STYLE = """
<style>
*{box-sizing:border-box}body{margin:0;background:#11161e;color:#f3f6fa;font:15px/1.55 system-ui,-apple-system,sans-serif}
main{max-width:1000px;margin:35px auto;padding:0 20px}h1{font-size:clamp(29px,5vw,43px);line-height:1.2}
h2{font-size:24px}.muted{color:#acb9c9}.top{background:#efdbad;color:#423014;padding:10px;text-align:center;font-weight:800;font-size:12px}
.panel{background:#202a36;border:1px solid #485567;border-radius:11px;padding:21px;margin:15px 0}
button,.button{cursor:pointer;display:inline-block;background:#e94938;border:1px solid #e94938;color:#fff;text-decoration:none;padding:11px 16px;border-radius:5px;font-weight:800}
button.secondary,.secondary{background:transparent;border:1px solid #738095;color:#fff}
input{display:block;padding:12px;width:100%;max-width:460px;border:1px solid #667385;background:#141b25;border-radius:6px;color:#fff;font:inherit;margin:7px 0 15px}
label{display:block;font-weight:700}a{color:#ff8a7f}button:focus-visible,input:focus-visible{outline:3px solid #ffbc75;outline-offset:2px}
.badge{display:inline-block;border-radius:15px;padding:4px 10px;background:#7c5b25;color:#fff0c3;font-size:12px;font-weight:800}
.badge.approved{background:#205a3c;color:#b9fdd1}.badge.declined{background:#712e37;color:#ffccd2}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.stat{background:#202a36;padding:18px;border-radius:8px}.stat strong{display:block;font-size:26px}
.row{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.small{font-size:12px}.actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:18px}
.error{color:#ffb2a8}form.inline{display:inline}footer{text-align:center;font-size:12px;color:#a7b3c2;padding:25px}
@media(max-width:600px){.grid{grid-template-columns:1fr}.actions button{flex:1}}
</style>
"""

LOGIN_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Staff Demo Login | Pistons</title>""" + STYLE + """</head><body>
<div class="top">UNOFFICIAL DEMO ONLY — private access for previewing appointment approvals</div>
<main style="max-width:570px"><h1>Pistons Auto Repair<br>Staff Demo Login</h1>
<p class="muted">Use the private demo password to review sample appointment requests. This is not an official customer booking system.</p>
<div class="panel"><form method="post" action="/owner/login">
<input type="hidden" name="csrf" value="{{ csrf }}">
<label for="username">Staff account</label><input id="username" name="username" autocomplete="username" required placeholder="owner or developer" maxlength="40">
<label for="password">Staff demo password</label><input type="password" id="password" name="password" autocomplete="current-password" required>
{% if error %}<p class="error" role="alert">{{ error }}</p>{% endif %}
<button type="submit">SIGN IN SECURELY</button>
</form></div>
<p><a href="https://pistons-auto-repair-demo.onrender.com">← Back to public website</a></p>
<p class="small muted">Sessions expire. Each staff member has their own login. Demo records are temporary and can reset on free hosting.</p>
</main><footer>Unofficial Pistons Auto Repair demonstration</footer></body></html>"""

DASH_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Staff Dashboard Demo | Pistons</title>""" + STYLE + """</head><body>
<div class="top">PRIVATE STAFF PREVIEW · UNOFFICIAL DEMO ONLY · Temporary sample records</div>
<main><div class="row"><div><p style="color:#ff8d7e;font-size:12px;font-weight:900;letter-spacing:2px">PISTONS AUTO REPAIR</p><h1>Owner & Staff Dashboard</h1></div>
<form method="post" action="/owner/logout"><input type="hidden" name="csrf" value="{{ csrf }}"><button class="secondary" type="submit">Log out</button></form></div>
<p class="muted">Signed in as <b>{{ username }}</b> ({{ role }}). Approve or decline fictional sample appointments only. This is not an official booking service.</p>
<div class="grid"><div class="stat">Pending<strong>{{ counts['Pending'] }}</strong></div><div class="stat">Approved<strong>{{ counts['Approved'] }}</strong></div><div class="stat">Declined<strong>{{ counts['Declined'] }}</strong></div></div>
{% if message %}<p class="panel" role="status">{{ message }}</p>{% endif %}
<h2>Appointment requests</h2>
{% if appointments %}
{% for a in appointments %}
<article class="panel"><div class="row"><h3 style="margin:0">{{ a['name'] }}</h3><span class="badge {{ a['status']|lower }}">{{ a['status'] }}</span></div>
<p class="small muted">Reference {{ a['id'] }}</p><p><b>Preferred:</b> {{ a['date'] }} at {{ a['time'] }} Central<br><b>Vehicle:</b> {{ a['vehicle'] }}</p>
<p>{{ a['issue'] }}</p><div class="actions">
<form method="post" action="/owner/decision" class="inline"><input type="hidden" name="csrf" value="{{ csrf }}"><input type="hidden" name="id" value="{{ a['id'] }}"><input type="hidden" name="status" value="Approved"><button type="submit">Approve</button></form>
<form method="post" action="/owner/decision" class="inline"><input type="hidden" name="csrf" value="{{ csrf }}"><input type="hidden" name="id" value="{{ a['id'] }}"><input type="hidden" name="status" value="Declined"><button type="submit" class="secondary">Decline</button></form>
<form method="post" action="/owner/decision" class="inline"><input type="hidden" name="csrf" value="{{ csrf }}"><input type="hidden" name="id" value="{{ a['id'] }}"><input type="hidden" name="status" value="Pending"><button type="submit" class="secondary">Reset pending</button></form>
</div></article>
{% endfor %}
{% else %}<p class="panel muted">No sample appointment requests yet. Submit one on the public website.</p>{% endif %}
<h2>Customer message examples</h2>
{% if messages %}{% for m in messages %}<div class="panel"><b>{{ m['name'] }}</b><p>{{ m['body'] }}</p><span class="small muted">Demo message · {{ m['created_at'][:16] }}</span></div>{% endfor %}
{% else %}<p class="panel muted">No sample messages yet.</p>{% endif %}
<div class="actions"><a class="button secondary" href="https://pistons-auto-repair-demo.onrender.com">← Public website</a><a class="button secondary" href="/owner">Refresh requests</a></div>
</main><footer>DEMO ONLY · Records can disappear on server restart · Not for real customer information</footer></body></html>"""

def owner_only(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if (session.get("staff") is not True or
            session.get("username") not in USER_HASHES or
            session.get("role") not in ("owner", "developer")):
            return redirect(url_for("owner_login"))
        return fn(*args, **kwargs)
    return wrapper

def csrf_ok():
    sent = request.form.get("csrf", "")
    existing = session.get("csrf", "")
    return bool(existing) and secrets.compare_digest(sent, existing)

@app.route("/owner/login", methods=["GET", "POST"])
def owner_login():
    if session.get("staff"):
        return redirect(url_for("owner_dashboard"))
    if not session.get("csrf"):
        session["csrf"] = secrets.token_urlsafe(32)
    error = ""
    if request.method == "POST":
        if not csrf_ok():
            return "Invalid login token. Refresh and try again.", 403
        if rate_limit("login", 7, 600):
            return "Too many attempts. Try again later.", 429
        password = request.form.get("password", "")
        username = request.form.get("username", "").strip().lower()
        # Reject unknown accounts and avoid leaking which usernames are valid.
        if len(password) > 256 or username not in USER_HASHES:
            error = "Username or password not recognized."
        elif check_password_hash(USER_HASHES[username], password):
            session.clear()
            session["staff"] = True
            session["username"] = username
            session["role"] = "owner" if username == "owner" else "developer"
            session["csrf"] = secrets.token_urlsafe(32)
            session.permanent = True
            return redirect(url_for("owner_dashboard"))
        else:
            error = "Username or password not recognized."
    return render_template_string(LOGIN_HTML, csrf=session["csrf"], error=error)

@app.get("/owner")
@owner_only
def owner_dashboard():
    with connect() as db:
        appointments = db.execute("SELECT * FROM appointments ORDER BY created_at DESC LIMIT 100").fetchall()
        messages = db.execute("SELECT * FROM messages ORDER BY created_at DESC LIMIT 100").fetchall()
        rows = db.execute("SELECT status,COUNT(*) as count FROM appointments GROUP BY status").fetchall()
    counts = {"Pending": 0, "Approved": 0, "Declined": 0}
    for row in rows:
        counts[row["status"]] = row["count"]
    status = request.args.get("result", "")
    messages_by_result = {"approved": "Sample appointment approved.", "declined": "Sample appointment declined.",
        "pending": "Sample appointment returned to Pending.", "conflict": "Time slot already approved for another sample request.",
        "missing": "Sample request no longer exists."}
    return render_template_string(DASH_HTML, appointments=appointments, messages=messages, counts=counts, csrf=session["csrf"],
                                  username=session.get("username"), role=session.get("role"),
                                  message=messages_by_result.get(status, ""))

@app.post("/owner/decision")
@owner_only
def owner_decision():
    if not csrf_ok():
        return "Invalid form token.", 403
    reference = request.form.get("id", "")
    status = request.form.get("status", "")
    if status not in ("Approved", "Declined", "Pending") or not isinstance(reference, str) or len(reference) > 100:
        return "Invalid request.", 400
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        item = db.execute("SELECT id,date,time FROM appointments WHERE id=?", (reference,)).fetchone()
        if item is None:
            return redirect(url_for("owner_dashboard", result="missing"), code=303)
        if status == "Approved":
            other = db.execute("SELECT id FROM appointments WHERE date=? AND time=? AND status='Approved' AND id!=?",
                               (item["date"], item["time"], reference)).fetchone()
            if other:
                return redirect(url_for("owner_dashboard", result="conflict"), code=303)
        db.execute("UPDATE appointments SET status=? WHERE id=?", (status, reference))
    return redirect(url_for("owner_dashboard", result=status.lower()), code=303)

@app.post("/owner/logout")
@owner_only
def logout():
    if not csrf_ok():
        return "Invalid form token.", 403
    session.clear()
    return redirect(url_for("owner_login"), code=303)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")))
