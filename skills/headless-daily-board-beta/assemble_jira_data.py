#!/usr/bin/env python3
"""
assemble_jira_data.py — build and validate jira_data.json from Atlassian MCP result files.

The Atlassian MCP saves large query results to tool-result files instead of
returning them inline. This script reads those files (or small inline results
saved to temp JSON files), validates the data, and writes jira_data.json in
the exact format headless_daily_report.py expects.

Usage:
  python3 assemble_jira_data.py \
      --sprint-file <path> [--sprint-file <path2> ...] \
      --sev-file <path> \
      --bpr-file <path> \
      --out jira_data.json

Each input file may be either:
  * an MCP tool-result file:  {"issues": {"nodes": [...], "pageInfo": {...}}}
  * a plain JSON array of issue objects:  [{"key": ..., "fields": {...}}, ...]

Multiple --sprint-file arguments are concatenated (pagination support).

Exit codes: 0 = OK, 1 = validation failure (do NOT run the report), 2 = usage/IO error.
"""
import argparse
import json
import sys
from pathlib import Path

# Fields the report script never reads — stripped to keep jira_data.json lean.
STRIP_FIELDS = {"description"}

MIN_SPRINT_ISSUES = 20
MIN_WITH_SUMMARY = 15
MIN_WITH_SPRINT_FIELD = 10

# Bumped in lockstep with headless_daily_report.py and assemble_slack_data.py.
# See CHANGELOG.md for what changed at each version.
SKILL_VERSION = "2.3.1"


def fail(msg: str) -> None:
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(1)


def load_issues(path: Path) -> tuple[list[dict], dict]:
    """Return (issues, pageInfo) from an MCP result file or plain JSON array."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"❌ Cannot read {path}: {e}", file=sys.stderr)
        sys.exit(2)

    if isinstance(data, list):
        return data, {}
    if isinstance(data, dict):
        issues_obj = data.get("issues")
        if isinstance(issues_obj, dict) and "nodes" in issues_obj:
            return issues_obj["nodes"] or [], issues_obj.get("pageInfo") or {}
        if isinstance(issues_obj, list):
            return issues_obj, {}
        if "nodes" in data:
            return data["nodes"] or [], data.get("pageInfo") or {}
    print(f"❌ Unrecognised JSON structure in {path}", file=sys.stderr)
    sys.exit(2)


def normalise(issue: dict) -> dict:
    """Ensure {key, fields:{...}} shape and strip unused heavy fields."""
    if "fields" not in issue:
        fields = {k: v for k, v in issue.items() if k not in ("key", "id")}
        issue = {"key": issue.get("key", ""), "id": issue.get("id", ""), "fields": fields}
    issue["fields"] = {k: v for k, v in (issue.get("fields") or {}).items()
                       if k not in STRIP_FIELDS}
    return issue


def keys_of(issues: list[dict]) -> list[str]:
    return [i.get("key", "") for i in issues]


def main() -> None:
    print(f"assemble_jira_data.py -- skill v{SKILL_VERSION}", file=sys.stderr)
    ap = argparse.ArgumentParser()
    ap.add_argument("--sprint-file", action="append", required=True,
                    help="MCP result file(s) for the sprint issues query (repeatable for pages)")
    ap.add_argument("--sev-file", action="append", required=True, help="MCP result file(s) for the SEV bugs query — repeat once per page (2026-10-16: was single-file, extra pages were silently dropped)")
    ap.add_argument("--bpr-file", action="append", required=True, help="MCP result file(s) for the SEV BPRs query — repeat once per page")
    ap.add_argument("--out", default="jira_data.json", help="Output path (default: jira_data.json)")
    ap.add_argument("--expected-count", type=int, default=None,
                    help="True total for the sprint filter, from a computeIssueCount call. "
                         "If given, the number of UNIQUE sprint issues loaded must equal it "
                         "exactly, or the build fails. This is the ONLY reliable guard against "
                         "a truncated page that the MCP falsely marks hasNextPage=false "
                         "(root cause of the LPP-64669 miss on 2026-07-02).")
    ap.add_argument("--changelog-file", default=None,
                    help="Optional JSON file mapping issue key -> list of changelog history "
                         "dicts (same shape as the Jira API's changelog.histories), built by "
                         "Claude from getJiraIssue(expand=changelog) MCP calls during data "
                         "collection. Merged into jira_data.json's optional 'changelogs' field "
                         "so headless_daily_report.py never needs a direct HTTPS fallback for "
                         "these issues (2026-07-08, per Nóra — see SKILL.md Workflow step 1).")
    ap.add_argument("--comment-file", default=None,
                    help="Optional JSON file mapping issue key -> the issue's Jira "
                         "'comment' field object (shape: {\"comments\": [...]}, same as "
                         "fields.comment on a raw Jira issue). Built by Claude from the SAME "
                         "per-issue getJiraIssue calls used for --changelog-file (add "
                         "\"comment\" to that call's fields list — no extra round-trips), "
                         "covering the Section-1-eligible candidate subset. Merged into each "
                         "matching sprint_issues[*].fields.comment. This lets the bulk sprint "
                         "query itself OMIT the heavy 'comment' field entirely (2026-08-25 perf "
                         "fix): comment threads on this board can run to thousands of words, "
                         "which is what forced the bulk sprint query down to maxResults:5 "
                         "(~16 sequential calls for a 78-issue sprint). Without 'comment' in "
                         "the bulk fetch, a single maxResults:100 call reliably returns the "
                         "whole sprint (verified live 2026-08-25). Comments are only ever read "
                         "by trigger-evaluation code for issues in an in-progress-like status "
                         "anyway (see SKILL.md 'Section 1 visibility gate'), which is the same "
                         "issue set already targeted by the changelog pre-fetch — so nothing is "
                         "lost by fetching comments only for that subset. Issues NOT in this "
                         "file simply keep no 'comment' field; downstream code already treats a "
                         "missing comment list as 'fall back to the issue's created date' "
                         "(see _last_comment_date() in headless_daily_report.py), which is a "
                         "no-op for these issues since they're not in a Section-1-eligible "
                         "status in the first place.")
    ap.add_argument("--sev-bpr-detail-file", action="append", default=[],
                    help="MCP result file(s) of the SEV BPR detail query printed by "
                         "--plan-sev-bpr (repeatable for pages). The returned BPRs are "
                         "appended to sprint_issues so headless_daily_report.py never has "
                         "to fetch them over HTTPS (proxy-blocked, no token in the sandbox). "
                         "Added 2026-10-13 (board beta v0.12.0).")
    ap.add_argument("--plan-sev-bpr", action="store_true",
                    help="Print the JQL + fields for the SEV BPR detail query (the SEV BPRs "
                         "not already in the sprint result) and exit without writing anything.")
    args = ap.parse_args()

    # ── Load ────────────────────────────────────────────────────────────────
    sprint_issues: list[dict] = []
    seen: set[str] = set()
    # FIXED 2026-08-19 (see CHANGELOG-fixes-2026-08-19.md): this check used
    # to fire on EVERY supplied --sprint-file that had hasNextPage=true, but
    # pages 1..N-1 of any multi-page traversal always have hasNextPage=true
    # by definition — the documented pagination workflow (page until
    # exhausted, pass every page as a separate --sprint-file) was therefore
    # impossible to satisfy. A logic bug, not an MCP flakiness issue
    # (confirmed via a clean re-fetch of the first page, which reproduced
    # identically). Now only the LAST supplied --sprint-file — the true end
    # of the traversal — is required to have hasNextPage=false.
    for idx, p in enumerate(args.sprint_file):
        issues, page_info = load_issues(Path(p))
        for raw in issues:
            issue = normalise(raw)
            if issue["key"] and issue["key"] not in seen:
                seen.add(issue["key"])
                sprint_issues.append(issue)
        is_last_file = (idx == len(args.sprint_file) - 1)
        if is_last_file and page_info.get("hasNextPage"):
            fail(f"Sprint result file {p} (last supplied page) has hasNextPage=true — a page is missing. "
                 f"Fetch the next page with nextPageToken={page_info.get('endCursor')!r} "
                 f"and pass it as an additional --sprint-file. Do NOT proceed with partial data.")

    def load_pages(paths):
        allis, last, seen_k = [], {}, set()
        for p in paths:
            iss, last = load_issues(Path(p))
            for i in iss:
                k = i.get("key")
                if k not in seen_k:
                    seen_k.add(k); allis.append(i)
        return allis, last
    sev_issues, sev_page = load_pages(args.sev_file)
    bpr_issues, bpr_page = load_pages(args.bpr_file)
    if sev_page.get("hasNextPage"):
        fail("SEV bugs result has hasNextPage=true — fetch remaining pages first.")
    if bpr_page.get("hasNextPage"):
        fail("SEV BPRs result has hasNextPage=true — fetch remaining pages first.")

    sev_issues = [normalise(i) for i in sev_issues]
    bpr_issues = [normalise(i) for i in bpr_issues]

    # ── Defense-in-depth: drop any SEV issue already closed/resolved by build
    # time, even though the JQL already filters "status not in (closed)".
    # ROOT CAUSE (2026-07-15): a SEV bug (LPD-97411) closed between an early
    # fetch and the final build in the same session, and the stale early
    # fetch was reused instead of a fresh one — the closed bug then appeared
    # in the published report. This check is a safety net for that race, NOT
    # a substitute for re-fetching SEV data fresh immediately before running
    # this script (see SKILL.md).
    def _is_done(issue: dict) -> bool:
        status = (issue.get("fields") or {}).get("status") or {}
        cat = (status.get("statusCategory") or {}).get("key", "")
        name = (status.get("name") or "").strip().lower()
        return cat == "done" or name in ("closed", "resolved", "answered")

    stale_sev = [i["key"] for i in sev_issues if _is_done(i)]
    if stale_sev:
        print(f"   ⚠ Dropping {len(stale_sev)} SEV issue(s) already closed/resolved "
              f"at build time (stale fetch — re-verify next time): {', '.join(stale_sev)}",
              file=sys.stderr)
        sev_issues = [i for i in sev_issues if i["key"] not in stale_sev]

    # ── Resolve additional SEV BPRs via each SEV bug's own issuelinks ───────
    # ROOT CAUSE (2026-07-15): the saved BPR filter (filter=15069) depends on
    # the Branch Manager having tagged/created the backport ticket by fetch
    # time, which can lag behind the SEV bug's own status change (BPR-91107 /
    # BPR-91108 for LPD-97411 didn't exist yet on the first fetch). Reading
    # each SEV bug's own issuelinks is a more reliable source of truth and is
    # unioned in below. Requires "issuelinks" in the SEV bugs query's fields
    # (see SKILL.md) — silently finds nothing if that field wasn't fetched.
    linked_bpr_keys: set[str] = set()
    for issue in sev_issues:
        for link in (issue.get("fields") or {}).get("issuelinks") or []:
            for side in ("inwardIssue", "outwardIssue"):
                other = link.get(side)
                if other and str(other.get("key", "")).startswith("BPR-"):
                    linked_bpr_keys.add(other["key"])

    # ── Validate (hard stops — mirror SKILL.md rules) ───────────────────────
    n = len(sprint_issues)
    if n < MIN_SPRINT_ISSUES:
        fail(f"Only {n} sprint issues loaded (expected ≥ {MIN_SPRINT_ISSUES}). "
             f"The MCP likely returned cached/stale or truncated data. "
             f"Retry the query; if it persists, start a fresh session.")

    # ── Completeness guard against a silently truncated page ─────────────────
    # ROOT CAUSE (2026-07-02): the searchJiraIssuesUsingJql MCP returned a
    # truncated first page (52 issues) but set pageInfo.hasNextPage=false, so the
    # hasNextPage loop above passed and issues that genuinely matched the filter
    # (e.g. LPP-64669, an In-Queue customer LPP) were silently dropped. Trusting a
    # single page's hasNextPage is NOT sufficient. The only reliable check is to
    # compare the number of UNIQUE issues loaded against the filter's true total,
    # obtained from a separate computeIssueCount=true call and passed via
    # --expected-count. Mismatch => a page is missing => hard stop.
    if args.expected_count is not None:
        if n != args.expected_count:
            fail(f"Sprint issue count mismatch: loaded {n} unique issues but the filter's "
                 f"true total is {args.expected_count}. The MCP returned an INCOMPLETE result "
                 f"set (a truncated page falsely marked hasNextPage=false — the LPP-64669 bug). "
                 f"Re-run the sprint query paging via endCursor until the cursor is exhausted, "
                 f"pass every page as an additional --sprint-file, and re-run with the same "
                 f"--expected-count. Do NOT proceed with partial data.")
        print(f"   ✓ completeness verified: {n} loaded == {args.expected_count} filter total")
    else:
        print("   ⚠ --expected-count NOT supplied: cannot verify the result is complete. "
              "A truncated page marked hasNextPage=false would go undetected. "
              "Fetch the filter total via computeIssueCount=true and pass --expected-count "
              "on every run (see SKILL.md).", file=sys.stderr)

    sprint_keys = set(keys_of(sprint_issues))
    sev_keys_set = set(keys_of(sev_issues))
    if sprint_keys and sprint_keys == sev_keys_set:
        fail("Sprint query and SEV query returned IDENTICAL issue sets — the MCP returned "
             "the same cached response for two different queries. Retry in a fresh session.")

    with_summary = sum(1 for i in sprint_issues if (i["fields"].get("summary") or "").strip())
    if with_summary < MIN_WITH_SUMMARY:
        fail(f"Only {with_summary}/{n} sprint issues have a non-empty summary — "
             f"field data is incomplete. Retry the query.")

    with_sprint_field = sum(1 for i in sprint_issues if i["fields"].get("customfield_10020"))
    if with_sprint_field < MIN_WITH_SPRINT_FIELD:
        fail(f"Only {with_sprint_field}/{n} sprint issues have customfield_10020 (sprint) — "
             f"Days in Queue and issue inclusion would be wrong. Retry the query.")

    # ── Derive SEV key lists ────────────────────────────────────────────────
    sev_keys = keys_of(sev_issues)
    sev_zero_day_keys = [i["key"] for i in sev_issues
                         if "zero-day-vulnerability" in (i["fields"].get("labels") or [])]
    # 2026-10-13 (board beta v0.12.0): the SEV bugs query covers EVERY team's
    # security bugs (63 on 2026-10-13, only 5 of them Headless), so only take
    # linked BPRs from SEV bugs that are in the Headless sprint result.
    # Before this, other teams' backports (e.g. Commerce's BPR-93181/93183 for
    # LPD-106190) were only kept off the report because their HTTPS fetch failed.
    linked_bpr_keys = set()
    for issue in sev_issues:
        if issue.get("key") not in sprint_keys:
            continue
        for link in (issue.get("fields") or {}).get("issuelinks") or []:
            for side in ("inwardIssue", "outwardIssue"):
                other = link.get(side)
                if other and str(other.get("key", "")).startswith("BPR-"):
                    linked_bpr_keys.add(other["key"])
    sev_bpr_keys = sorted(set(keys_of(bpr_issues)) | linked_bpr_keys)
    _newly_found_bprs = linked_bpr_keys - set(keys_of(bpr_issues))
    if _newly_found_bprs:
        print(f"   + {len(_newly_found_bprs)} SEV BPR(s) found via issuelinks, not in the "
              f"filter=15069 result: {', '.join(sorted(_newly_found_bprs))}")

    # ── SEV BPR details (2026-10-13, board beta v0.12.0) ─────────────────────
    # SEV BPRs outside the sprint filter used to be fetched one by one over
    # direct HTTPS by headless_daily_report.py, which always fails in the
    # sandbox (no token, proxy-blocked) -> active SEV BPRs silently missing.
    # Now Claude fetches them in ONE MCP query (printed below) and passes the
    # result here; every queried key is recorded as checked so the report
    # script skips the HTTPS fallback for it.
    missing_bpr = sorted(set(sev_bpr_keys) - sprint_keys)
    if args.plan_sev_bpr:
        if not missing_bpr:
            print("SEV BPR detail query: none needed (all SEV BPRs are already in the sprint result).")
            return
        print(f"SEV BPR detail query ({len(missing_bpr)} keys) — searchJiraIssuesUsingJql, maxResults 100, page until hasNextPage=false:")
        print("jql: key in (" + ",".join(missing_bpr) + ") AND statusCategory != Done "
              "AND status not in (Open, Scheduled, \"Awaiting Original Fix\")")
        print('fields: ["key","summary","status","assignee","labels","issuetype","priority","project",'
              '"updated","created","duedate","customfield_10804","customfield_10168","parent",'
              '"customfield_10001","customfield_10020","issuelinks","subtasks"]')
        return
    detail_added: list[str] = []
    if args.sev_bpr_detail_file:
        for idx, p in enumerate(args.sev_bpr_detail_file):
            issues, page_info = load_issues(Path(p))
            if idx == len(args.sev_bpr_detail_file) - 1 and page_info.get("hasNextPage"):
                fail(f"SEV BPR detail file {p} (last page) has hasNextPage=true — fetch the next page "
                     f"(nextPageToken={page_info.get('endCursor')!r}) and pass it as another --sev-bpr-detail-file.")
            for raw in issues:
                issue = normalise(raw)
                k = issue.get("key", "")
                if k in set(missing_bpr) and k not in seen and not _is_done(issue):
                    seen.add(k)
                    sprint_issues.append(issue)
                    detail_added.append(k)
        print(f"   SEV BPR details: {len(detail_added)} active BPR(s) added from the detail query"
              + (f": {', '.join(detail_added)}" if detail_added else ""))
    elif missing_bpr:
        print(f"   ⚠ {len(missing_bpr)} SEV BPR(s) are not in the sprint result and no "
              f"--sev-bpr-detail-file was given — run with --plan-sev-bpr, fetch them via the MCP "
              f"and pass the result, or active SEV BPRs will be missing from the report.",
              file=sys.stderr)

    # ── Write ───────────────────────────────────────────────────────────────
    out = {
        "sprint_issues": sprint_issues,
        "sev_keys": sev_keys,
        "sev_zero_day_keys": sev_zero_day_keys,
        "sev_bpr_keys": sev_bpr_keys,
    }
    if args.sev_bpr_detail_file:
        out["sev_bpr_checked_keys"] = missing_bpr

    # ── Optional pre-fetched changelogs (2026-07-08, per Nóra) ────────────────
    # Merged in as-is; does not affect any of the validation/completeness
    # checks above, which only ever cover sprint_issues/sev_issues/bpr_issues.
    if args.changelog_file:
        cl_path = Path(args.changelog_file)
        if not cl_path.exists():
            fail(f"--changelog-file {cl_path} does not exist.")
        try:
            changelogs = json.loads(cl_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(f"--changelog-file {cl_path} is not valid JSON: {exc}")
        if not isinstance(changelogs, dict):
            fail(f"--changelog-file {cl_path} must contain a JSON object "
                 f"(issue key -> list of history dicts), got {type(changelogs).__name__}.")
        out["changelogs"] = changelogs
        print(f"   Changelogs: {len(changelogs)} pre-fetched (from {cl_path})")

    # ── Optional pre-fetched comments (2026-08-25 perf fix) ───────────────────
    # Merged directly into sprint_issues[*].fields.comment by key. Does not
    # affect any validation above (summary/customfield_10020 checks already
    # ran against the bulk-fetched fields, which never depended on comment).
    if args.comment_file:
        cm_path = Path(args.comment_file)
        if not cm_path.exists():
            fail(f"--comment-file {cm_path} does not exist.")
        try:
            comments_by_key = json.loads(cm_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(f"--comment-file {cm_path} is not valid JSON: {exc}")
        if not isinstance(comments_by_key, dict):
            fail(f"--comment-file {cm_path} must contain a JSON object "
                 f"(issue key -> comment field object), got {type(comments_by_key).__name__}.")
        merged = 0
        unmatched = []
        for issue in sprint_issues:
            key = issue.get("key", "")
            if key in comments_by_key:
                issue["fields"]["comment"] = comments_by_key[key]
                merged += 1
        unmatched = sorted(set(comments_by_key) - sprint_keys)
        print(f"   Comments: {merged}/{len(comments_by_key)} pre-fetched entries merged into sprint_issues (from {cm_path})")
        if unmatched:
            print(f"   ⚠ {len(unmatched)} comment-file key(s) did not match any sprint issue "
                  f"(harmless — usually a SEV BPR not in the sprint filter): {', '.join(unmatched)}",
                  file=sys.stderr)

    out_path = Path(args.out)
    out_path.write_text(json.dumps(out), encoding="utf-8")

    print(f"✅ jira_data.json written: {out_path} ({out_path.stat().st_size:,} bytes)")
    print(f"   Sprint issues: {n} | summaries: {with_summary}/{n} | "
          f"sprint field: {with_sprint_field}/{n}")
    print(f"   SEV keys: {len(sev_keys)} | zero-day: {len(sev_zero_day_keys)} | "
          f"SEV BPRs: {len(sev_bpr_keys)}")


if __name__ == "__main__":
    main()
