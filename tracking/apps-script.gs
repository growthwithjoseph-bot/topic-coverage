/**
 * Google Apps Script backend for the usage tracker.
 * Appends form submissions to a Google Sheet and emails you on each new signup.
 * Setup steps are in tracking/README.md.
 */

// Where new-signup alerts are sent. Change to your address if different.
var NOTIFY_EMAIL = "giuseppe.milo26@gmail.com";

function doPost(e) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var data = {};
  try { data = JSON.parse((e && e.postData && e.postData.contents) || "{}"); } catch (err) {}
  var now = new Date();

  if (data.type === "signup") {
    var signups = tab_(ss, "Signups", ["Timestamp", "Email", "Expectation", "App"]);
    signups.appendRow([now, data.email || "", data.expectation || "", data.app || ""]);
    try {
      MailApp.sendEmail(
        NOTIFY_EMAIL,
        "New signup: " + (data.email || "(no email)"),
        "Email: " + (data.email || "") +
          "\nExpectation: " + (data.expectation || "(none)") +
          "\nApp: " + (data.app || "") +
          "\nTime: " + now
      );
    } catch (err) {}
  } else if (data.type === "run") {
    var runs = tab_(ss, "Runs", ["Timestamp", "Email", "Own domain", "Competitors", "App"]);
    runs.appendRow([now, data.email || "", data.own_domain || "", data.competitors || "", data.app || ""]);
  }

  return ContentService
    .createTextOutput(JSON.stringify({ ok: true }))
    .setMimeType(ContentService.MimeType.JSON);
}

function tab_(ss, name, headers) {
  var s = ss.getSheetByName(name);
  if (!s) { s = ss.insertSheet(name); s.appendRow(headers); }
  return s;
}
