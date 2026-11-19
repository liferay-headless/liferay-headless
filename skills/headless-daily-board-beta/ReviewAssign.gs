/**
 * Headless Daily Board — "Review + assign" for PR rows (board v0.19.0, 2026-11-03)
 *
 * Add this as a NEW file next to Code.gs in the "Headless Daily Board" Apps Script project
 * (Files → + → Script → name it "ReviewAssign"). Then add ONE line to Code.gs — see below.
 *
 * Why: the team finds its PRs on GitHub by assignee (assignee:@me), so a requested reviewer who is
 * not also an assignee does not see the PR in their list. The board's PR-row button now says
 * "Review + assign": Code.gs requests the review as before, and this adds the same person as an
 * assignee. Existing assignees (usually the author) are kept — GitHub adds, it does not replace.
 * Uses the script property Code.gs v2 already has: GITHUB_TOKEN.
 *
 * ── The one line for Code.gs ───────────────────────────────────────────────────────────────
 * In assign(req), in the part that handles PR rows (req.mode === "review"), right AFTER the
 * GitHub review request succeeds and BEFORE that part returns, add:
 *
 *     addPrAssignee_(req.url, req.ghLogin);
 *
 * Then Deploy → Manage deployments → edit the web app → Version: New version → Deploy.
 * To test first: run testAddPrAssignee_ below on a PR of your own (edit the URL and login).
 */
var RA_GH_OWNER = "liferay-headless";
var RA_GH_REPO = "liferay-portal";

function addPrAssignee_(prUrl, ghLogin) {
  var m = String(prUrl || "").match(/github\.com\/([^\/]+)\/([^\/]+)\/pull\/(\d+)/);
  var login = String(ghLogin || "").trim();
  if (!m || !login) return "assignee not added (no PR link or GitHub login)";
  if (m[1] !== RA_GH_OWNER || m[2] !== RA_GH_REPO) throw new Error("Unexpected repository: " + m[1] + "/" + m[2]);
  if (!/^[A-Za-z0-9-]{1,39}$/.test(login)) throw new Error("Not a GitHub login: " + login);
  var token = PropertiesService.getScriptProperties().getProperty("GITHUB_TOKEN");
  // A PR is an issue in GitHub's API: POST /repos/{owner}/{repo}/issues/{number}/assignees
  var res = UrlFetchApp.fetch(
    "https://api.github.com/repos/" + RA_GH_OWNER + "/" + RA_GH_REPO + "/issues/" + m[3] + "/assignees", {
      method: "post",
      contentType: "application/json",
      headers: { Authorization: "Bearer " + token, Accept: "application/vnd.github+json" },
      payload: JSON.stringify({ assignees: [login] }),
      muteHttpExceptions: true
    });
  var code = res.getResponseCode();
  if (code !== 201 && code !== 200) throw new Error("GitHub assignee failed (" + code + "): " + res.getContentText().slice(0, 200));
  var added = (JSON.parse(res.getContentText()).assignees || []).some(function (a) { return a.login.toLowerCase() === login.toLowerCase(); });
  // GitHub silently ignores people without access to the repository.
  return added ? "review requested + assigned" : "review requested (GitHub did not accept " + login + " as assignee)";
}

function testAddPrAssignee_() {
  Logger.log(addPrAssignee_("https://github.com/liferay-headless/liferay-portal/pull/0000", "your-github-login"));
}
