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
    ap = argparse.ArgumentParser()
    ap.add_argument("--sprint-file", action="append", required=True,
                    help="MCP result file(s) for the sprint issues query (repeatable for pages)")
    ap.add_argument("--sev-file", required=True, help="MCP result file for the SEV bugs query")
    ap.add_argument("--bpr-file", required=True, help="MCP result file for the SEV BPRs query")
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
    args = ap.parse_args()

    # ── Load ────────────────────────────────────────────────────────────────
    sprint_issues: list[dict] = []
    seen: set[str] = set()
    for p in args.sprint_file:
        issues, page_info = load_issues(Path(p))
        for raw in issues:
            issue = normalise(raw)
            if issue["key"] and issue["key"] not in seen:
                seen.add(issue["key"])
                sprint_issues.append(issue)
        if page_info.get("hasNextPage"):
            fail(f"Sprint result file {p} has hasNextPage=true — a page is missing. "
                 f"Fetch the next page with nextPageToken={page_info.get('endCursor')!r} "
                 f"and pass it as an additional --sprint-file. Do NOT proceed with partial data.")

    sev_issues, sev_page = load_issues(Path(args.sev_file))
    bpr_issues, bpr_page = load_issues(Path(args.bpr_file))
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
    sev_bpr_keys = sorted(set(keys_of(bpr_issues)) | linked_bpr_keys)
    _newly_found_bprs = linked_bpr_keys - set(keys_of(bpr_issues))
    if _newly_found_bprs:
        print(f"   + {len(_newly_found_bprs)} SEV BPR(s) found via issuelinks, not in the "
              f"filter=15069 result: {', '.join(sorted(_newly_found_bprs))}")

    # ── Write ───────────────────────────────────────────────────────────────
    out = {
        "sprint_issues": sprint_issues,
        "sev_keys": sev_keys,
        "sev_zero_day_keys": sev_zero_day_keys,
        "sev_bpr_keys": sev_bpr_keys,
    }

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

    out_path = Path(args.out)
    out_path.write_text(json.dumps(out), encoding="utf-8")

    print(f"✅ jira_data.json written: {out_path} ({out_path.stat().st_size:,} bytes)")
    print(f"   Sprint issues: {n} | summaries: {with_summary}/{n} | "
          f"sprint field: {with_sprint_field}/{n}")
    print(f"   SEV keys: {len(sev_keys)} | zero-day: {len(sev_zero_day_keys)} | "
          f"SEV BPRs: {len(sev_bpr_keys)}")


if __name__ == "__main__":
    main()
