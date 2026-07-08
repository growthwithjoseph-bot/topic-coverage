# Usage tracking (email gate + domain log) — setup

A dead-simple tracker with **no server to run**. The app POSTs each submission to
a **Google Apps Script Web App**, which appends rows to a **Google Sheet** and
**emails you** on every new signup.

What gets captured:
- **Signups** tab — Timestamp · Email · Expectation · App (you also get an email)
- **Runs** tab — Timestamp · Email · Own domain · Competitors · App

## One-time setup (~5 minutes)

1. Create a Google Sheet (sheets.new). Name it anything (e.g. "Tool tracking").
2. In that Sheet: **Extensions → Apps Script**.
3. Delete the default code, paste the contents of [`apps-script.gs`](apps-script.gs).
   (Change `NOTIFY_EMAIL` at the top if you want alerts sent elsewhere.)
4. Click **Deploy → New deployment**.
   - Type: **Web app**
   - Execute as: **Me**
   - Who has access: **Anyone**
   - **Deploy**, then authorise when prompted (it's your own script).
5. Copy the **Web app URL** (ends in `/exec`).
6. Paste that URL into **`frontend/tracking.js`** — replace
   `PASTE_YOUR_APPS_SCRIPT_WEB_APP_URL_HERE`. Commit + push.

That's it. The `Signups` and `Runs` tabs are created automatically on the first
submission. Until the URL is set, tracking is disabled and the app runs normally.

> One Sheet + one script can serve **both** apps — paste the same URL into
> `tracking.js` in each repo. The `App` column tells them apart.

## Notes
- The Apps Script endpoint is a public append-only URL; it can't read your Sheet.
- Free, no quotas that matter at this scale, no third-party service.
- To change what's emailed, edit `MailApp.sendEmail(...)` in `apps-script.gs`
  and redeploy (**Deploy → Manage deployments → Edit → Version: New**).
