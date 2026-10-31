# Pistons Auto Repair — Monday Owner Demo

**Status:** An unofficial interactive demo, not an operational booking service. Business owner approval is required before representing this website as official or collecting any real customer information.

## Links

- Public demonstration: https://pistons-auto-repair-demo.onrender.com
- Private staff demonstration login: https://pistons-staff-demo.onrender.com/owner/login
- Render static site: https://dashboard.render.com/static/srv-dbj674k9v7es7397lqsg
- Render staff demo server: https://dashboard.render.com/web/srv-dbj6drss728c738v0vg0

Do not store staff passwords, secrets, or customer information in the public GitHub repository.

## Five-minute in-person demonstration

1. Open the public website on a phone. Show the services, contact, tap-to-call and directions links.
2. Scroll to the appointment form. Use **fictional** sample information (e.g. Sample Customer, Sample Vehicle, Sample issue). Do not use real names, contact details or actual appointments.
3. Submit the sample appointment. The server should show a reference number and **Pending** status. Save the reference or leave the tab open.
4. Open the private staff login on another phone or browser. The owner can view the login page, but do **not** give away administrator credentials or accept real customer details in the demo. Use the private demonstration password in an appropriate one-to-one setting.
5. See the example appointment in the staff dashboard. Press **Approve** or **Decline** and show the new status.
6. On the public site, submit a sample message. Refresh the staff dashboard and see it under messages.
7. Open the sample appointment's private status link to see the updated decision.

Because the demo server runs on Render's free tier, the first request may be slow while the instance wakes up. The temporary SQLite database can reset whenever the free instance restarts or redeploys, so don't depend on sample data still being present on Monday.

## October 31 quality verification

All three automated suites passed on the final review branch:

- **28 backend integration tests:** sample requests, approved/declined/pending flow, cross-browser status, double-booking prevention, owner/developer login, logout, CSRF checks, anonymous access denial, validation, rate limiting, message handling, security headers.
- **6 headless Chromium UI tests:** booking and message forms, mobile layout, staff navigation, status link rendering, error handling.
- **7 live HTTP tests:** actual public demo and staff-server responses, protected login gate, browser preflight CORS, fictional booking request and status page, fictional message, blocked unapproved origin.
- Both existing Render services reported a successful **live** deploy of the hardened application. Tests did not use real customer information.

### Staff demo accounts

There are now two separate username/password accounts, `owner` and `developer`. Temporary demo password hashes are stored in Render environment variables, **not in GitHub**. The developer can show the dashboard to the owner without sharing an admin password. The old single shared password has been replaced.

After owner acceptance, change the temporary demo passwords, provision individual production accounts, and do not reuse any demo credential on the real business website.

### Approval demonstration

1. Open the public website, submit a fictional appointment with a weekday/time in the future.
2. Open the private staff website and sign in as `developer` or `owner`.
3. Click **Approve** or **Decline** on the request.
4. Use the **Check sample approval status** link from the original customer page to see the readable updated status.

## Verified during October 31, 2026 preparation

- Both Render services reported **live** after deployment.
- Render logged a sample message POST to `/api/messages` with HTTP **201 Created**, confirming it was accepted.
- Render logged a successful staff login and access to `/owner` with HTTP **200**.
- Cross-client end-to-end flows passed in integration tests; full browser and live server smoke tests passed. A real two-person hands-on owner walkthrough is still useful before Monday.
- Password-protected staff access uses separate owner and developer demo accounts; true production account lifecycle, MFA and recovery still require setup.
- No paid hosting or databases have been activated for this project.

## Questions to confirm with owner

- Exact business name, phone number, address, hours, service menu, and any service limitations.
- Shop branding, logo, photos and review permission.
- How long appointments should be, time slots, days off, holidays, and staff capacity.
- Who can approve appointments; whether different roles are required; who should receive notifications.
- Whether to send confirmations by email, SMS or both and whether customers can cancel or reschedule.
- Business domain ownership and whether they want hosting billed directly or managed.
- Upfront setup fee, recurring maintenance, scope of changes, timeline and ownership of content/source code.
- Privacy policy, data retention, backup, appropriate handling of customer information.

## Required before a real public launch

1. Written authorization from the business owner to publish as its official site and use its name/branding.
2. Remove all demo notices **only after** real forms work and the owner approves the production launch.
3. Provision persistent production database, backups, monitoring and a tested restore procedure. **Do not use Render free service's ephemeral SQLite as production storage.**
4. Establish separate owner/manager and developer accounts with strong individual passwords, secure account recovery and preferably MFA.
5. Rotate the shared demo password. Never reuse it for the production dashboard.
6. Build and test secure real customer intake fields and a privacy notice. Stop collecting sample-only records before production.
7. Connect and test customer notifications (email and/or SMS). Confirm service costs and sender configuration.
8. Configure scheduling rules, conflict checks, calendar/timezone policies and business closures with the owner.
9. Test the whole process from two separate devices: request, pending, owner login, approve, decline, customer confirmation, status update, and message delivery.
10. Verify business details and photos, review mobile accessibility, ensure HTTPS, and approve a written scope of work.

### Current implementation limitations

- The live public static site is for demonstrations and fictional sample submissions only.
- The live staff server uses a shared private password and temporary local database.
- Staff responses update status but **do not send customers email or SMS**.
- No real customer details should be entered or submitted.
- A new account and durable server/database may require an appropriately priced hosting tier when activated; no paid service should be created without owner/user consent.

## Troubleshooting

- If a request does not appear: confirm the public form showed successful submission, refresh the staff dashboard, check the server availability and Render logs.
- If the staff login fails: confirm the demo password; repeated incorrect attempts are rate-limited; do not expose the password publicly.
- If sample data disappeared: the free-tier demo database is temporary. Send another fictional request.
- If an appointment cannot be approved: the system blocks approval when another approved appointment has the same date/time.
