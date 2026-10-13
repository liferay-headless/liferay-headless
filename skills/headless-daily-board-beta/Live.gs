/**
 * Headless Daily Board — live status (board v0.17.0, 2026-10-13)
 *
 * Add this as a NEW file next to Code.gs in the "Headless Daily Board" Apps Script project
 * (Files → + → Script → name it "Live"). Code.gs v2 stays unchanged.
 *
 * The board page calls liveStatus({keys, prs}) once when it opens. It answers with the current
 * Jira status of the given issue keys and the current state of the given PRs, read-only.
 * Uses the script properties Code.gs v2 already has: JIRA_EMAIL, JIRA_TOKEN, GITHUB_TOKEN.
 * Results are cached for 5 minutes, so many viewers ≈ a few Jira/GitHub requests.
 */
var LIVE_JIRA_BASE = "https://liferay.atlassian.net";
var LIVE_GH_OWNER = "liferay-headless";
var LIVE_GH_REPO = "liferay-portal";
var LIVE_CACHE_SECONDS = 300;

function liveStatus(req) {
  req = req || {};
  // Validate input: only well-formed Jira keys and PR numbers, bounded size (no open proxy).
  var keys = (req.keys || []).filter(function (k) { return /^[A-Z][A-Z0-9]+-\d+$/.test(String(k)); })
    .map(String).slice(0, 400).sort();
  var prs = (req.prs || []).map(Number).filter(function (n) { return n > 0 && n < 1e7 && Math.floor(n) === n; })
    .slice(0, 150).sort(function (a, b) { return a - b; });

  var cache = CacheService.getScriptCache();
  var digest = Utilities.base64EncodeWebSafe(
    Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, keys.join(",") + "|" + prs.join(",")));
  var cacheKey = "live:" + digest.slice(0, 40);
  var hit = cache.get(cacheKey);
  if (hit) return JSON.parse(hit);

  var out = { at: new Date().toISOString(), issues: {}, prs: {} };
  try { out.issues = liveJira_(keys); } catch (e) { out.jiraError = String(e && e.message || e); }
  try { out.prs = liveGithub_(prs); } catch (e) { out.githubError = String(e && e.message || e); }
  try { cache.put(cacheKey, JSON.stringify(out), LIVE_CACHE_SECONDS); } catch (e) { /* too big to cache: fine */ }
  return out;
}

/** {KEY: {status, cat}} via Jira bulk fetch (100 per call; unknown keys are skipped, not errors). */
function liveJira_(keys) {
  var res = {};
  if (!keys.length) return res;
  var p = PropertiesService.getScriptProperties();
  var auth = "Basic " + Utilities.base64Encode(p.getProperty("JIRA_EMAIL") + ":" + p.getProperty("JIRA_TOKEN"));
  for (var i = 0; i < keys.length; i += 100) {
    var r = UrlFetchApp.fetch(LIVE_JIRA_BASE + "/rest/api/3/issue/bulkfetch", {
      method: "post", contentType: "application/json", muteHttpExceptions: true,
      headers: { Authorization: auth, Accept: "application/json" },
      payload: JSON.stringify({ issueIdsOrKeys: keys.slice(i, i + 100), fields: ["status"] })
    });
    if (r.getResponseCode() !== 200) throw new Error("Jira " + r.getResponseCode() + ": " + r.getContentText().slice(0, 200));
    (JSON.parse(r.getContentText()).issues || []).forEach(function (it) {
      var st = (it.fields || {}).status || {};
      res[it.key] = { status: st.name || "", cat: (st.statusCategory || {}).key || "" };
    });
  }
  return res;
}

/** {number: {state: OPEN|CLOSED|MERGED, isDraft, reviewDecision}} via one GitHub GraphQL call per 50 PRs. */
function liveGithub_(prs) {
  var res = {};
  if (!prs.length) return res;
  var token = PropertiesService.getScriptProperties().getProperty("GITHUB_TOKEN");
  for (var i = 0; i < prs.length; i += 50) {
    var chunk = prs.slice(i, i + 50);
    var q = "query{repository(owner:\"" + LIVE_GH_OWNER + "\",name:\"" + LIVE_GH_REPO + "\"){" +
      chunk.map(function (n) { return "p" + n + ":pullRequest(number:" + n + "){state isDraft reviewDecision}"; }).join(" ") + "}}";
    var r = UrlFetchApp.fetch("https://api.github.com/graphql", {
      method: "post", contentType: "application/json", muteHttpExceptions: true,
      headers: { Authorization: "bearer " + token },
      payload: JSON.stringify({ query: q })
    });
    if (r.getResponseCode() !== 200) throw new Error("GitHub " + r.getResponseCode() + ": " + r.getContentText().slice(0, 200));
    var repo = ((JSON.parse(r.getContentText()).data) || {}).repository || {};
    chunk.forEach(function (n) {
      var pr = repo["p" + n];
      if (pr) res[n] = { state: pr.state, isDraft: !!pr.isDraft, reviewDecision: pr.reviewDecision || "" };
    });
  }
  return res;
}

/** Run this once from the editor to test: View → Execution log shows what the board would get. */
function testLiveStatus() {
  Logger.log(JSON.stringify(liveStatus({ keys: ["LPD-108615", "LPD-106781"], prs: [4404, 4428] })));
}
