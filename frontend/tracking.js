/* Extremely simple usage tracker.
 *
 * 1) An email gate shown once (email required, "what do you expect" optional).
 * 2) Logs the domains submitted on every analysis.
 * Both are POSTed to your Google Apps Script Web App, which appends rows to a
 * Google Sheet and emails you on each new signup. See tracking/README.md.
 *
 * Paste your Apps Script /exec URL below. Until you do, tracking is disabled
 * and the app runs completely normally (no gate, no requests).
 */
const TRACKER_URL = "PASTE_YOUR_APPS_SCRIPT_WEB_APP_URL_HERE";

(function () {
  const configured = TRACKER_URL && !TRACKER_URL.includes("PASTE_YOUR");
  const APP = document.title || location.host;

  function post(payload) {
    if (!configured) return;
    try {
      // text/plain body => a "simple" request, so no CORS preflight to Apps Script.
      fetch(TRACKER_URL, {
        method: "POST",
        body: JSON.stringify(Object.assign({ app: APP }, payload)),
      }).catch(function () {});
    } catch (e) {}
  }

  // Called by the app on each analysis to log the submitted domains.
  window.trackRun = function (own, competitors) {
    post({
      type: "run",
      email: localStorage.getItem("tracker_email") || "",
      own_domain: own || "",
      competitors: (competitors || []).join(", "),
    });
  };

  if (!configured) return;                            // no gate until you set the URL
  if (localStorage.getItem("tracker_email")) return;  // already gave their email

  function showGate() {
    const css = document.createElement("style");
    css.textContent =
      "#trackerGate{position:fixed;inset:0;z-index:1000;display:flex;align-items:center;justify-content:center;font-family:inherit}" +
      "#trackerGate .tg-backdrop{position:absolute;inset:0;background:rgba(15,23,42,.55)}" +
      "#trackerGate .tg-card{position:relative;background:#fff;width:min(420px,92vw);border-radius:14px;padding:22px;box-shadow:0 20px 60px rgba(0,0,0,.3);display:flex;flex-direction:column;gap:10px}" +
      "#trackerGate h3{margin:0;font-size:18px;color:#0f172a}" +
      "#trackerGate p{margin:0 0 4px;color:#64748b;font-size:13px}" +
      "#trackerGate label{display:flex;flex-direction:column;gap:4px;font-size:12.5px;font-weight:600;color:#334155}" +
      "#trackerGate label span{font-weight:400;color:#94a3b8}" +
      "#trackerGate input,#trackerGate textarea{padding:9px 10px;border:1px solid #e2e8f0;border-radius:8px;font-size:14px;font-family:inherit}" +
      "#trackerGate input:focus,#trackerGate textarea:focus{outline:2px solid #93c5fd;border-color:#93c5fd}" +
      "#trackerGate button{margin-top:6px;padding:10px;border:0;border-radius:8px;background:#0f172a;color:#fff;font-weight:600;font-size:14px;cursor:pointer}";
    document.head.appendChild(css);

    const el = document.createElement("div");
    el.id = "trackerGate";
    el.innerHTML =
      '<div class="tg-backdrop"></div>' +
      '<form class="tg-card">' +
      "<h3>Before you start</h3>" +
      "<p>Enter your email to try the tool.</p>" +
      '<label>Email *<input id="tg_email" type="email" required placeholder="you@example.com" autocomplete="email"></label>' +
      "<label>What are you hoping to get out of it? <span>(optional)</span>" +
      '<textarea id="tg_exp" rows="3" placeholder="In a few words…"></textarea></label>' +
      '<button type="submit">Continue →</button>' +
      "</form>";
    document.body.appendChild(el);

    el.querySelector("form").addEventListener("submit", function (ev) {
      ev.preventDefault();
      const email = el.querySelector("#tg_email").value.trim();
      if (!email) return;
      const expectation = el.querySelector("#tg_exp").value.trim();
      localStorage.setItem("tracker_email", email);
      post({ type: "signup", email: email, expectation: expectation });
      el.remove();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", showGate);
  } else {
    showGate();
  }
})();
