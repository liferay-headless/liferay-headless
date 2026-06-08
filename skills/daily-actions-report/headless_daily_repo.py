#!/usr/bin/env python3
"""
headless_daily_report.py — Headless Team Daily Actions Report
Self-sufficient pipeline: fetches, classifies, and publishes the team's daily
triage report to Confluence.

Usage:
  python3 headless_daily_report.py --jira-data-file jira_data.json --pr-data-file pr_data.json
  python3 headless_daily_report.py --jira-data-file jira_data.json --pr-data-file pr_data.json --publish
  python3 headless_daily_report.py --jira-data-file jira_data.json --pr-data-file pr_data.json --dry-run
  python3 headless_daily_report.py --jira-data-file jira_data.json --no-testing-panel
  python3 headless_daily_report.py --jira-data-file jira_data.json --date YYYY-MM-DD

Requirements:
  pip install requests

Environment variables:
  ATLASSIAN_EMAIL   — Your Atlassian account email
  ATLASSIAN_TOKEN   — Atlassian API token

Sprint config (sprint label, dates, Confluence page ID) is read at runtime from
  project_current_sprint.md in the daily-actions-report skill folder.
Nothing sprint-specific is hardcoded in this file.

PUBLISH FALLBACK — IF THE SCRIPT'S PUBLISH STEP FAILS:
  The script publishes via direct HTTPS to liferay.atlassian.net, which may be
  proxy-blocked in Claude's sandbox. If Step 14 fails with a ProxyError or
  connection error, DO NOT fall back to the updateConfluencePage MCP tool —
  it does not support ?notifyWatchers=false and will spam Jira watchers.

  Instead, use javascript_tool via the liferay.atlassian.net Chrome tab:

    (async () => {
      const pageId = "{actions_report_page_id}";
      const verResp = await fetch(
        `https://liferay.atlassian.net/wiki/rest/api/content/${pageId}?expand=version`,
        {headers: {"Content-Type": "application/json"}}
      );
      const currentVersion = (await verResp.json()).version.number;
      const resp = await fetch(
        `https://liferay.atlassian.net/wiki/rest/api/content/${pageId}?notifyWatchers=false`,
        {
          method: "PUT",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            type: "page",
            title: "{sprint_label} — Daily Actions Report",
            version: {number: currentVersion + 1, minorEdit: true},
            body: {
              atlas_doc_format: {
                value: JSON.stringify(adf),
                representation: "atlas_doc_format"
              }
            }
          })
        }
      );
      return `HTTP ${resp.status} — version: ${(await resp.json())?.version?.number}`;
    })()

  This runs inside the user's logged-in browser session, bypasses the proxy,
  and correctly passes ?notifyWatchers=false. The ADF to pass is produced by
  running the script with --dry-run and capturing the validated ADF output.
"""

import os
import sys
import json
import re
import uuid
import base64
import argparse
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

# ── LOAD .env FILE ────────────────────────────────────────────────────────────
# Reads ATLASSIAN_EMAIL and ATLASSIAN_TOKEN from .env in the same folder as this
# script. Does nothing if the file is absent (env vars may already be set).
_ENV_FILE = Path(__file__).parent / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# ── PATHS ────────────────────────────────────────────────────────────────────

# Skill folder — where project_current_sprint.md lives
SKILL_DIR = Path(__file__).parent / "daily-actions-report"
SPRINT_CONTEXT_FILE = SKILL_DIR / "project_current_sprint.md"

# Output folder — HTML previews land here (same dir as the script)
OUTPUT_DIR = Path(__file__).parent

# ── STATIC CONSTANTS (never change between sprints) ──────────────────────────

JIRA_BASE = "https://liferay.atlassian.net"
GITHUB_ORG = "liferay-headless"
GITHUB_REPO = "liferay-portal"

SPRINT_FILTER_ID = "54796"
SEV_BPR_FILTER_ID = "15069"

# ── EXCLUSION ACCOUNT IDs (permanently excluded individuals) ─────────────────

BRIAN_CHAN_ID = "5b0d62e6-05d8-4b82-ad47-ef75f0cf5da5"
PT_HEADLESS_ID = "6365999cf7ad721e785090ce"
# Designers — excluded via Discovery Task rule
ANTONIO_JIMENO_ID = "631866029796033b256d9338"
UGE_ORTIZ_ID = "5f86c6e78a2db000760ac740"

# ── TIER COLORS ───────────────────────────────────────────────────────────────
# Maps tier identifier → (category_text, sub_name, adf_color)
# adf_color values: "red" | "yellow" | "purple" | "blue" | "neutral"
# PR standalone uses key "PR".
# Tier numbers stored as strings to avoid float key issues (7.1 etc.).

TIER_COLORS: dict[str, tuple[str, str, str]] = {
    "PR":   ("Unplanned", "PR",                              "yellow"),
    "1.1":  ("Unplanned", "Critical SEV",                    "red"),
    "1.2":  ("Unplanned", "Critical LPP",                    "red"),
    "2":    ("Planned",   "Expedite",                        "purple"),
    "3":    ("Unplanned", "High Release Blockers",           "yellow"),
    "4":    ("Unplanned", "High SEV",                        "yellow"),
    "5":    ("Unplanned", "High SEV BPR",                    "yellow"),
    "6":    ("Unplanned", "High Release BPR",                "yellow"),
    "7.1":  ("Unplanned", "High LPP CI - Over Forecast (Update needed)", "yellow"),
    "7.2":  ("Unplanned", "High LPP CI - Over Forecast",    "yellow"),
    "7.3":  ("Unplanned", "High LPP Customer Issues",        "yellow"),
    "7.4":  ("Unplanned", "High LPP Customer Fix Mgmt",      "yellow"),
    "7.5":  ("Unplanned", "High LPP Customer Issue Analysis","yellow"),
    "8":    ("Unplanned", "High BPR",                        "yellow"),
    "9":    ("Unplanned", "Medium PTR",                      "blue"),
    "12":   ("Planned",   "Focus",                           "blue"),
    "13":   ("Planned",   "Regular",                         "neutral"),
}

# ── DAYS THRESHOLDS ───────────────────────────────────────────────────────────
# LPD orange/red thresholds by t-shirt size (days_active must EXCEED these to trigger)
# Spec says ">2d" means >2, i.e. >=3. We store the threshold value; caller uses strict >.

LPD_ORANGE_THRESHOLD: dict[str, int] = {
    "XS": 2,
    "S":  3,
    "M":  5,
    "L":  10,
    "XL": 14,
    "":   999,   # no t-shirt → no orange threshold
}

LPD_RED_THRESHOLD: dict[str, int] = {
    "XS": 14,
    "S":  14,
    "M":  14,
    "L":  14,
    "XL": 21,
    "":   14,
}

# LPP thresholds (same for all issue types)
LPP_ORANGE_THRESHOLD = 10
LPP_RED_THRESHOLD = 19


# ════════════════════════════════════════════════════════════════════════════════
# CHUNK 1 — Auth + API wrappers
# All HTTP calls go through these functions. No requests.get/post anywhere else.
# ════════════════════════════════════════════════════════════════════════════════

def _jira_headers() -> dict[str, str]:
    """Build Basic-auth headers from ATLASSIAN_EMAIL + ATLASSIAN_TOKEN env vars."""
    email = os.environ.get("ATLASSIAN_EMAIL", "")
    token = os.environ.get("ATLASSIAN_TOKEN", "")
    if not email or not token:
        raise RuntimeError(
            "Missing Atlassian credentials. "
            "Set ATLASSIAN_EMAIL and ATLASSIAN_TOKEN environment variables."
        )
    creds = base64.b64encode(f"{email}:{token}".encode()).decode()
    return {
        "Authorization": f"Basic {creds}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _github_headers() -> dict[str, str]:
    """Build Bearer-auth headers from GITHUB_TOKEN env var."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError(
            "Missing GitHub credentials. Set GITHUB_TOKEN environment variable."
        )
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def jira_post_search(jql: str, fields: list[str], max_results: int = 200) -> list[dict]:
    """
    POST to /rest/api/3/search/jql with pagination.
    Returns flat list of raw issue dicts.
    Uses POST (the old GET endpoint has been removed).
    Handles 429 with exponential backoff (3 retries).
    """
    url = f"{JIRA_BASE}/rest/api/3/search/jql"
    all_issues: list[dict] = []
    start_at = 0
    retries = 3

    while True:
        body = {
            "jql": jql,
            "fields": fields,
            "maxResults": min(100, max_results - len(all_issues)),
            "startAt": start_at,
        }
        print(f"  [jira_post_search] POST /rest/api/3/search/jql startAt={start_at} jql={jql[:80]}...")

        resp = None
        for attempt in range(retries):
            resp = requests.post(url, headers=_jira_headers(), json=body, timeout=30)
            if resp.status_code == 429:
                wait = 2 ** attempt
                print(f"    [429 rate-limit] waiting {wait}s (attempt {attempt + 1}/{retries})")
                time.sleep(wait)
                continue
            break

        if resp is None or resp.status_code == 429:
            raise RuntimeError(f"Failed after {retries} attempts: POST {url}")

        resp.raise_for_status()
        data = resp.json()

        issues = data.get("issues", [])
        all_issues.extend(issues)

        total = data.get("total", len(all_issues))
        print(f"    → fetched {len(all_issues)}/{total}")

        if len(all_issues) >= total or not issues or len(all_issues) >= max_results:
            break
        start_at += len(issues)

    return all_issues


def jira_get_issue(key: str, fields: list[str] | None = None, expand: str | None = None) -> dict:
    """
    GET a single Jira issue by key.
    Optional fields list and expand string (e.g. expand="changelog").
    """
    url = f"{JIRA_BASE}/rest/api/3/issue/{key}"
    params: dict = {}
    if fields:
        params["fields"] = ",".join(fields)
    if expand:
        params["expand"] = expand

    print(f"  [jira_get_issue] GET /rest/api/3/issue/{key}" +
          (f" expand={expand}" if expand else ""))

    retries = 3
    for attempt in range(retries):
        resp = requests.get(url, headers=_jira_headers(), params=params, timeout=30)
        if resp.status_code == 429:
            wait = 2 ** attempt
            print(f"    [429 rate-limit] waiting {wait}s (attempt {attempt + 1}/{retries})")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()

    raise RuntimeError(f"Failed after {retries} attempts: GET {url}")


def jira_get_confluence_version(page_id: str) -> int:
    """
    GET the current version number of a Confluence page.
    Used before every publish to compute new_version = current + 1.
    """
    url = f"{JIRA_BASE}/wiki/rest/api/content/{page_id}"
    params = {"expand": "version"}
    print(f"  [jira_get_confluence_version] GET /wiki/rest/api/content/{page_id}")

    retries = 3
    for attempt in range(retries):
        resp = requests.get(url, headers=_jira_headers(), params=params, timeout=30)
        if resp.status_code == 429:
            wait = 2 ** attempt
            print(f"    [429 rate-limit] waiting {wait}s")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        data = resp.json()
        version = data.get("version", {}).get("number", 1)
        print(f"    → current version: {version}")
        return version

    raise RuntimeError(f"Failed after {retries} attempts: GET {url}")


def jira_put_confluence(page_id: str, title: str, adf_json: dict, version_number: int) -> dict:
    """
    PUT a new version of a Confluence page using ADF body.
    ALWAYS includes ?notifyWatchers=false — callers cannot accidentally omit it.
    Raises on non-200.
    """
    # notifyWatchers=false is hardcoded here so no caller can forget it.
    url = f"{JIRA_BASE}/wiki/rest/api/content/{page_id}?notifyWatchers=false"
    print(f"  [jira_put_confluence] PUT /wiki/rest/api/content/{page_id}?notifyWatchers=false "
          f"version={version_number}")

    payload = {
        "type": "page",
        "title": title,
        "version": {"number": version_number, "minorEdit": True},
        "body": {
            "atlas_doc_format": {
                "value": json.dumps(adf_json, ensure_ascii=False),
                "representation": "atlas_doc_format",
            }
        },
    }

    resp = requests.put(url, headers=_jira_headers(), json=payload, timeout=60)
    if not resp.ok:
        raise RuntimeError(
            f"Confluence PUT failed: HTTP {resp.status_code}\n{resp.text[:500]}"
        )
    result = resp.json()
    new_ver = result.get("version", {}).get("number", "?")
    print(f"    → published: version {new_ver}")
    return result



# ════════════════════════════════════════════════════════════════════════════════
# CHUNK 2 — Sprint context loader
# ════════════════════════════════════════════════════════════════════════════════

@dataclass
class SprintContext:
    """
    All sprint-scoped data loaded from project_current_sprint.md.
    Downstream code reads only from this object — never re-reads the file.
    """
    sprint_label: str
    sprint_field: str
    start_date: date
    end_date: date
    actions_report_page_id: str

    # Optional fixed page title — if set, Confluence page title never changes
    # across sprint rollovers. If absent, falls back to sprint_label-based title.
    report_page_title: str = ""

    # Caches and snapshots — mutable dicts updated after each publish
    changelog_cache: dict[str, str] = field(default_factory=dict)
    state_snapshot: dict = field(default_factory=dict)
    testing_baseline: dict = field(default_factory=dict)
    account_ids: dict[str, str] = field(default_factory=dict)
    pr_snapshot: dict = field(default_factory=dict)

    # Pre-fetched changelogs injected from jira_data.json by Claude during data
    # collection.  Keyed by issue key → list of history dicts (same structure as
    # the Jira changelog.histories array).  When present, get_first_active_date
    # and _get_bpr_ofc_date read from here instead of making direct HTTPS calls,
    # which avoids proxy failures in the Claude sandbox.
    # Not persisted to project_current_sprint.md — rebuilt each run.
    changelogs: dict[str, list] = field(default_factory=dict)

    @property
    def days_remaining(self) -> int:
        """Days from today until end_date (can be negative if sprint is over)."""
        return (self.end_date - date.today()).days

    @property
    def confluence_page_title(self) -> str:
        # Use the fixed title if configured — keeps the Confluence page title
        # stable across sprint rollovers (permanent single-page approach).
        return self.report_page_title or f"{self.sprint_label} — Daily Actions Report"


def load_sprint_context(path: Path) -> "SprintContext":
    """
    Parse project_current_sprint.md and return a populated SprintContext.

    File format:
      ## Sprint Metadata
      - key: value
      ...

      ## Section Name
      ```json
      { ... }
      ```
    """
    if not path.exists():
        raise FileNotFoundError(f"Sprint context file not found: {path}")

    text = path.read_text(encoding="utf-8")

    # ── Parse Sprint Metadata (key-value lines) ───────────────────────────────
    metadata: dict[str, str] = {}
    meta_match = re.search(
        r"## Sprint Metadata\n(.*?)(?=\n## |\Z)",
        text,
        re.DOTALL,
    )
    if meta_match:
        for line in meta_match.group(1).splitlines():
            line = line.strip()
            if line.startswith("- "):
                line = line[2:]
            if ":" in line:
                k, _, v = line.partition(":")
                metadata[k.strip()] = v.strip()

    # ── Parse JSON sections ───────────────────────────────────────────────────
    # Pattern: ## SectionName (on a line of its own, not preceded by other content)
    # Uses a non-greedy section name that cannot span newlines.
    json_sections: dict[str, dict] = {}
    for section_match in re.finditer(
        r"^## ([^\n]+)\n```json\n(.*?)```",
        text,
        re.DOTALL | re.MULTILINE,
    ):
        section_name = section_match.group(1).strip()
        # Skip the Sprint Metadata section — it has no JSON block of its own
        if section_name == "Sprint Metadata":
            continue
        json_text = section_match.group(2).strip()
        try:
            json_sections[section_name] = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON parse error in section '{section_name}': {e}")

    # ── Validate required fields ──────────────────────────────────────────────
    required_meta = ["sprint_label", "start_date", "end_date", "actions_report_page_id"]
    for key in required_meta:
        if key not in metadata:
            raise ValueError(f"Missing required sprint metadata field: '{key}'")

    # ── Build SprintContext ───────────────────────────────────────────────────
    ctx = SprintContext(
        sprint_label=metadata["sprint_label"],
        sprint_field=metadata.get("sprint_field", metadata["sprint_label"]),
        start_date=date.fromisoformat(metadata["start_date"]),
        end_date=date.fromisoformat(metadata["end_date"]),
        actions_report_page_id=metadata["actions_report_page_id"],
        report_page_title=metadata.get("report_page_title", ""),
        changelog_cache=json_sections.get("Changelog Cache", {}),
        state_snapshot=json_sections.get("State Snapshot", {}),
        testing_baseline=json_sections.get("Testing Panel Baseline", {}),
        account_ids=json_sections.get("Account IDs", {}),
        pr_snapshot=json_sections.get("PR Snapshot", {}),
    )
    return ctx


def save_sprint_context(ctx: SprintContext, path: Path) -> None:
    """
    Write all sections back to project_current_sprint.md.
    Preserves the exact file format — only updates JSON block content.
    Sections not in the dataclass are passed through unchanged.
    """
    if not path.exists():
        raise FileNotFoundError(f"Sprint context file not found: {path}")

    original = path.read_text(encoding="utf-8")

    # Map section names to their new JSON content from ctx
    updates: dict[str, dict] = {
        "Changelog Cache":        ctx.changelog_cache,
        "State Snapshot":         ctx.state_snapshot,
        "Testing Panel Baseline": ctx.testing_baseline,
        "Account IDs":            ctx.account_ids,
        "PR Snapshot":            ctx.pr_snapshot,
    }

    def replace_json_block(text: str, section_name: str, new_data: dict) -> str:
        """Replace the ```json block under a given ## section heading."""
        pattern = re.compile(
            r"(## " + re.escape(section_name) + r"\n```json\n)(.*?)(```)",
            re.DOTALL,
        )
        replacement_json = json.dumps(new_data, ensure_ascii=False, indent=2)
        def replacer(m):
            return m.group(1) + replacement_json + "\n" + m.group(3)
        new_text, count = pattern.subn(replacer, text)
        if count == 0:
            # Section doesn't exist — append it
            new_text = text.rstrip("\n") + (
                f"\n\n## {section_name}\n```json\n"
                + json.dumps(new_data, ensure_ascii=False, indent=2)
                + "\n```\n"
            )
        return new_text

    result = original
    for section_name, data in updates.items():
        result = replace_json_block(result, section_name, data)

    path.write_text(result, encoding="utf-8")
    print(f"  [save_sprint_context] Saved → {path.name}")


# ════════════════════════════════════════════════════════════════════════════════
# CHUNK 3 — Data fetching
# All functions return raw/normalised dicts — no classification logic here.
# ════════════════════════════════════════════════════════════════════════════════

# Fields requested on every sprint-issue fetch
_SPRINT_ISSUE_FIELDS = [
    "key", "summary", "status", "assignee", "labels", "issuetype",
    "priority", "project", "updated", "created", "duedate", "comment",
    "customfield_10804",   # T-shirt Size
    "customfield_10168",   # Heat Score
    "parent",
    "customfield_10001",   # Team
    "customfield_10020",   # Sprint
    "issuelinks",
]


def load_jira_data(jira_data_file: "Path | None") -> "tuple[list[dict], set[str], set[str], set[str]]":
    """
    Load all Jira data from a JSON file written by Claude via the Jira MCP.

    Expected format — the file must be a JSON object with these keys:
    {
      "sprint_issues": [ ...raw Jira issue dicts... ],
      "sev_keys": [ "LPD-12345", ... ],
      "sev_zero_day_keys": [ ... ],
      "sev_bpr_keys": [ ... ],
      "changelogs": {                         # optional — pre-fetched changelogs
        "LPD-12345": [ ...history dicts... ], # same structure as changelog.histories
        ...
      }
    }

    The issue dicts use the same field structure as the Jira REST API
    (fields.status.name, fields.assignee.accountId, etc.) — parse_issue()
    consumes them unchanged.

    The optional "changelogs" dict allows Claude to pre-fetch all changelogs via
    the Jira MCP during data collection and inject them here, so the script never
    needs to make direct HTTPS calls for changelogs (which fail via the proxy in
    the Claude sandbox).  Each entry maps an issue key to its list of history dicts,
    matching the structure of the Jira API's changelog.histories array:
      [{"created": "2026-05-01T...", "items": [{"field": "status", "toString": "In Development"}]}, ...]

    Returns: (sprint_issues, sev_keys, sev_zero_day_keys, sev_bpr_keys, changelogs)

    If the file doesn't exist or is missing a key, prints a clear error and
    returns empty collections — does not crash, lets the rest of the pipeline
    show what it can.
    """
    print("\n[load_jira_data]")

    if jira_data_file is None or not jira_data_file.exists():
        print("  !! No Jira data file provided or file not found — returning empty Jira data.")
        print("     Pass --jira-data-file PATH to supply Jira data fetched by Claude via MCP.")
        return [], set(), set(), set(), {}

    print(f"  Loading Jira data from: {jira_data_file.name}")
    try:
        data = json.loads(jira_data_file.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  !! Failed to read Jira data file: {exc}")
        return [], set(), set(), set(), {}

    if not isinstance(data, dict):
        print(f"  !! Jira data file must contain a JSON object, got {type(data).__name__}")
        return [], set(), set(), set(), {}

    sprint_issues: list[dict] = data.get("sprint_issues", [])
    if not isinstance(sprint_issues, list):
        print("  !! 'sprint_issues' key missing or not a list — using empty list")
        sprint_issues = []

    raw_sev_keys = data.get("sev_keys", [])
    if not isinstance(raw_sev_keys, list):
        print("  !! 'sev_keys' key missing or not a list — using empty set")
        raw_sev_keys = []

    raw_sev_zero_day_keys = data.get("sev_zero_day_keys", [])
    if not isinstance(raw_sev_zero_day_keys, list):
        print("  !! 'sev_zero_day_keys' key missing or not a list — using empty set")
        raw_sev_zero_day_keys = []

    raw_sev_bpr_keys = data.get("sev_bpr_keys", [])
    if not isinstance(raw_sev_bpr_keys, list):
        print("  !! 'sev_bpr_keys' key missing or not a list — using empty set")
        raw_sev_bpr_keys = []

    changelogs: dict[str, list] = data.get("changelogs", {})
    if not isinstance(changelogs, dict):
        print("  !! 'changelogs' key is not a dict — ignoring")
        changelogs = {}

    sev_keys: set[str] = set(raw_sev_keys)
    sev_zero_day_keys: set[str] = set(raw_sev_zero_day_keys)
    sev_bpr_keys: set[str] = set(raw_sev_bpr_keys)

    print(f"  → {len(sprint_issues)} sprint issues, {len(sev_keys)} SEV keys, "
          f"{len(sev_zero_day_keys)} zero-day, {len(sev_bpr_keys)} SEV BPR keys, "
          f"{len(changelogs)} pre-fetched changelogs")
    return sprint_issues, sev_keys, sev_zero_day_keys, sev_bpr_keys, changelogs


def fetch_open_prs(ctx: "SprintContext", pr_data_file: "Path | None" = None) -> list[dict]:
    """
    Load open PRs from a JSON file produced by Claude via Chrome MCP.

    WHY: The GitHub repo (liferay-headless/liferay-portal) requires Liferay
    organisation membership to access via API. Instead, Claude opens the PR list
    in the user's browser (where they are already logged in), scrapes the data,
    and writes it to a JSON file. This function reads that file.

    Expected JSON format (list of PR objects):
    [
      {
        "pr_number": 123,
        "title": "LPD-12345 Fix something",
        "author": "some-github-login",
        "branch": "LPD-12345-fix-something",       # branch name, used for Jira key extraction
        "created_at": "2026-05-20",                 # YYYY-MM-DD or ISO datetime string
        "reviewer": "reviewer-login",               # null if no reviewer assigned
        "reviewer_status": "APPROVED",              # APPROVED | CHANGES_REQUESTED | PENDING | null
        "url": "https://github.com/...",            # full PR URL
        "parent_key": "LPD-99999",                  # pre-resolved parent key (REQUIRED — Claude
                                                    #   populates this from jira_data sprint issues
                                                    #   before writing the file; no jira_get_issue
                                                    #   calls are made here)
        "lpp_fix_key": "LPP-12345"                  # optional; null if not an LPP fix PR
      },
      ...
    ]

    This function:
      - Skips any PR already marked draft=true (if field present)
      - Extracts linked Jira key from branch name or title
      - Uses parent_key directly from the JSON (pre-resolved by Claude — no API calls)
      - Computes open_days from created_at
      - Returns the enriched dict structure for downstream merge_prs_to_issues

    If pr_data_file is None or the file doesn't exist, returns empty list and
    prints a warning. Use --no-github to intentionally skip.
    """
    print("\n[fetch_open_prs]")

    if pr_data_file is None or not pr_data_file.exists():
        print("  !! No PR data file provided — returning empty PR list.")
        print("     To include PRs: Claude will fetch them via Chrome MCP and pass --pr-data-file.")
        return []

    print(f"  Loading PR data from: {pr_data_file.name}")
    try:
        raw_prs: list[dict] = json.loads(pr_data_file.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  !! Failed to read PR data file: {exc}")
        return []

    if not isinstance(raw_prs, list):
        print(f"  !! PR data file must contain a JSON array, got {type(raw_prs).__name__}")
        return []

    print(f"  {len(raw_prs)} PRs in file")
    enriched: list[dict] = []
    today = date.today()

    for pr in raw_prs:
        # Skip drafts
        if pr.get("draft", False):
            print(f"  PR#{pr.get('pr_number', '?')}: skipping draft")
            continue

        pr_number = pr.get("pr_number") or pr.get("number")
        if not pr_number:
            print(f"  WARNING: PR entry missing pr_number, skipping: {pr}")
            continue

        pr_number = int(pr_number)
        title     = pr.get("title", "")
        author    = pr.get("author", "")
        branch    = pr.get("branch", "")
        url       = pr.get("url", f"https://github.com/{GITHUB_ORG}/{GITHUB_REPO}/pull/{pr_number}")
        # Parse reviewers list (preferred) or fall back to single reviewer field.
        # Bot names to ignore: liferay-headless, gemini-code-assist[bot], etc.
        _BOT_NAMES = {"liferay-headless", "gemini-code-assist[bot]", "gemini-code-assist"}
        reviewers_list = pr.get("reviewers") or []
        human_reviewers = [
            r for r in reviewers_list
            if isinstance(r, dict) and r.get("name", "").lower() not in _BOT_NAMES
        ]

        if human_reviewers:
            # Determine overall reviewer/reviewer_status from the list:
            # Priority: changes_requested > pending/requested > approved
            changes_req = [r for r in human_reviewers if r.get("status", "").lower() == "changes_requested"]
            approved    = [r for r in human_reviewers if r.get("status", "").lower() == "approved"]
            pending     = [r for r in human_reviewers if r.get("status", "").lower() in ("requested", "pending", "commented")]

            if changes_req:
                reviewer = ", ".join(r["name"] for r in changes_req)
                reviewer_status = "CHANGES_REQUESTED"
            elif approved and not pending:
                reviewer = ", ".join(r["name"] for r in approved)
                reviewer_status = "APPROVED"
            else:
                # Mix of approved+pending or all pending — show pending names
                show = pending if pending else approved
                reviewer = ", ".join(r["name"] for r in show)
                reviewer_status = "PENDING"
        else:
            # Fall back to legacy single-field values
            reviewer = pr.get("reviewer") or None
            if reviewer and reviewer.lower() in _BOT_NAMES:
                reviewer = None
            reviewer_status = pr.get("reviewer_status") or None

        # Compute open_days from created_at; fall back to pre-computed open_days in JSON
        created_at = pr.get("created_at", "")
        open_days = 0
        if created_at:
            try:
                # Accept either YYYY-MM-DD or full ISO datetime
                created_str = created_at[:10]
                created_date = date.fromisoformat(created_str)
                open_days = (today - created_date).days
            except ValueError:
                open_days = 0
        if not open_days:
            # created_at absent or unparseable — use pre-computed value from JSON
            open_days = int(pr.get("open_days") or 0)

        # Use jira_key from the JSON first (most reliable — pre-resolved by Claude).
        # Fall back to regex extraction from branch/title only when the JSON field
        # is absent or null.  This prevents a wrong title key (e.g. a subtask number)
        # from overriding the correct value that was explicitly set in pr_data.json.
        jira_key: str | None = pr.get("jira_key") or None
        if not jira_key:
            jira_key_match = (
                re.search(r"(LPD|LPP|BPR)-\d+", branch) or
                re.search(r"(LPD|LPP|BPR)-\d+", title)
            )
            jira_key = jira_key_match.group(0) if jira_key_match else None

        # Use pre-resolved parent_key and lpp_fix_key from the JSON.
        # Claude populates these from the jira_data sprint issues before writing
        # the pr_data.json file — no jira_get_issue calls are made here.
        parent_key: str | None = pr.get("parent_key") or None
        lpp_fix_key: str | None = pr.get("lpp_fix_key") or None

        if jira_key:
            print(f"  PR#{pr_number}: jira_key={jira_key} parent_key={parent_key}")
        else:
            print(f"  PR#{pr_number}: no Jira key found in branch={branch!r} title={title!r}")

        enriched.append({
            "pr_number":      pr_number,
            "title":          title,
            "author":         author,
            "jira_key":       jira_key,
            "parent_key":     parent_key,
            "lpp_fix_key":    lpp_fix_key,
            "reviewer":       reviewer,
            "reviewer_status": reviewer_status,
            "open_days":      open_days,
            "url":            url,
            "draft":          False,
        })

    print(f"  → {len(enriched)} open non-draft PRs")
    return enriched


def parse_issue(raw: dict) -> dict:
    """
    Normalise one raw Jira issue dict into a flat dict with clean field names.
    Never truncates the labels list — all label processing must use the full array.
    """
    fields = raw.get("fields", {})
    key = raw.get("key", "")
    project = key.split("-")[0] if "-" in key else ""

    # ── Status ────────────────────────────────────────────────────────────────
    status_raw = (fields.get("status") or {}).get("name", "")
    # Normalize internal whitespace (Jira sometimes returns "Original Fix  Committed")
    status = " ".join(status_raw.lower().split())

    # ── Assignee ─────────────────────────────────────────────────────────────
    assignee_field = fields.get("assignee") or {}
    assignee = assignee_field.get("displayName", "")
    assignee_id = assignee_field.get("accountId", "")

    # ── Labels — NEVER truncate ───────────────────────────────────────────────
    raw_labels = fields.get("labels") or []
    labels: list[str] = []
    for lbl in raw_labels:
        if isinstance(lbl, dict):
            labels.append(lbl.get("name", ""))
        else:
            labels.append(str(lbl))
    assert isinstance(labels, list), f"labels must be a list for {key}"

    # ── Issue type + priority ─────────────────────────────────────────────────
    issuetype = (fields.get("issuetype") or {}).get("name", "")
    priority = (fields.get("priority") or {}).get("name", "")

    # ── T-shirt size (customfield_10804) ─────────────────────────────────────
    tshirt_raw = fields.get("customfield_10804")
    if isinstance(tshirt_raw, dict):
        tshirt = tshirt_raw.get("value", "")
    elif isinstance(tshirt_raw, str):
        tshirt = tshirt_raw
    else:
        tshirt = ""

    # ── Heat score (customfield_10168) ────────────────────────────────────────
    heat_raw = fields.get("customfield_10168")
    heat_score = str(heat_raw) if heat_raw is not None else ""

    # ── Parent ────────────────────────────────────────────────────────────────
    parent_field = fields.get("parent") or {}
    parent_key = parent_field.get("key", "")
    parent_summary = (parent_field.get("fields") or {}).get("summary", "")

    # ── Team field (customfield_10001) ───────────────────────────────────────
    team_raw = fields.get("customfield_10001")
    if isinstance(team_raw, dict):
        team = team_raw.get("name", "") or team_raw.get("value", "")
    elif isinstance(team_raw, str):
        team = team_raw
    else:
        team = ""

    # ── Sprint field (customfield_10020) — last entry's name + earliest start ──
    sprint_list = fields.get("customfield_10020") or []
    sprint_name = ""
    sprint_start_date = ""   # earliest startDate across all sprints this issue has been in
    if sprint_list:
        last_sprint = sprint_list[-1]
        if isinstance(last_sprint, dict):
            sprint_name = last_sprint.get("name", "")
        elif isinstance(last_sprint, str):
            sprint_name = last_sprint
        # Walk all sprint entries to find the earliest startDate
        for sp in sprint_list:
            if isinstance(sp, dict):
                sd = sp.get("startDate", "") or ""
                if sd:
                    sd_short = sd[:10]   # "2026-05-18T00:00:00.000Z" → "2026-05-18"
                    if not sprint_start_date or sd_short < sprint_start_date:
                        sprint_start_date = sd_short

    # ── Dates ─────────────────────────────────────────────────────────────────
    updated = fields.get("updated", "")
    created = fields.get("created", "")
    duedate = fields.get("duedate", "") or ""

    # ── Comments — extract author_id + created for trigger evaluation ─────────
    comment_list = ((fields.get("comment") or {}).get("comments")) or []
    comments: list[dict] = []
    for c in comment_list:
        author_id = (c.get("author") or {}).get("accountId", "")
        created_ts = c.get("created", "")
        body = c.get("body", "")
        # Store body as plain text if it's a string, otherwise stringify
        if isinstance(body, dict):
            # ADF body — extract text nodes for simple comparison
            body_text = _adf_to_plain_text(body)
        else:
            body_text = str(body)
        comments.append({
            "author_id": author_id,
            "created": created_ts,
            "body": body_text,
        })

    # ── Issue links ───────────────────────────────────────────────────────────
    issuelinks = fields.get("issuelinks") or []

    return {
        "key": key,
        "project": project,
        "summary": fields.get("summary", ""),
        "status": status,
        "status_raw": status_raw,
        "assignee": assignee,
        "assignee_id": assignee_id,
        "labels": labels,           # full array — never truncate downstream
        "issuetype": issuetype,
        "priority": priority,
        "tshirt": tshirt,
        "heat_score": heat_score,
        "parent_key": parent_key,
        "parent_summary": parent_summary,
        "team": team,
        "sprint_name": sprint_name,
        "sprint_start_date": sprint_start_date,   # earliest sprint startDate (YYYY-MM-DD)
        "updated": updated,
        "created": created,
        "duedate": duedate,
        "comments": comments,
        "issuelinks": issuelinks,
    }


def _adf_to_plain_text(adf: dict) -> str:
    """
    Recursively extract plain text from an ADF (Atlassian Document Format) node.
    Used only for comment body comparison in trigger evaluation.
    """
    if not isinstance(adf, dict):
        return str(adf)
    node_type = adf.get("type", "")
    if node_type == "text":
        return adf.get("text", "")
    parts = []
    for child in adf.get("content", []):
        parts.append(_adf_to_plain_text(child))
    return " ".join(p for p in parts if p).strip()


# ════════════════════════════════════════════════════════════════════════════════
# CHUNK 4 — Exclusion rules
# One function: should_exclude(issue, sev_keys, ctx) -> str | None
# Returns None to keep the issue, or a reason string to exclude it.
# Rules are evaluated in order — first match wins.
# ════════════════════════════════════════════════════════════════════════════════

def should_exclude(issue: dict, sev_keys: set[str], ctx: "SprintContext") -> str | None:
    """
    Return None to keep the issue, or a reason string to exclude it.
    Rules are in strict priority order — first match wins.
    Applied before any classification or routing.
    """
    key = issue["key"]
    project = issue["project"]
    status = issue["status"]          # already lowercased by parse_issue
    labels = issue["labels"]          # full list, never truncated
    issuetype = issue["issuetype"]
    assignee_id = issue["assignee_id"]
    team = issue["team"]
    sprint_name = issue["sprint_name"]
    comments = issue["comments"]

    # ── Rule 1: headless-board-out label ─────────────────────────────────────
    if "headless-board-out" in labels:
        return "headless-board-out"

    # ── Rule 2: Discovery Task issuetype → always exclude ────────────────────
    if issuetype == "Discovery Task":
        return "Discovery Task"

    # ── Rule 3: LPD In Review — exclude when ball is NOT in the Headless team's court
    # Exclude when:
    #   (a) Assignee is Brian Chan (he owns the merge queue), OR
    #   (b) Assignee is NOT a known Headless team member (e.g. PT User Core Infrastructure)
    #       → the review is with another team; no Headless action needed.
    # LPD In Review issues assigned to a known Headless team member ARE kept —
    # they may need follow-up (PR trigger, stale, etc.).
    if project == "LPD" and status == "in review":
        if assignee_id == BRIAN_CHAN_ID:
            return "Brian Chan In Review"
        if assignee_id and assignee_id not in ctx.account_ids.values():
            return "LPD In Review — non-Headless assignee (waiting for merge)"

    # ── Rule 5: Non-Headless LPD (SEV issues bypass this check) ──────────────
    if project == "LPD" and key not in sev_keys:
        headless_team = team and "Headless" in team
        headless_sprint = sprint_name and sprint_name.startswith("HL")
        headless_assignee = assignee_id in ctx.account_ids.values()
        if not (headless_team or headless_sprint or headless_assignee):
            return "Non-Headless LPD"

    # ── Rule 6: LPP with comba-in label ──────────────────────────────────────
    if project == "LPP" and "comba-in" in labels:
        return "comba-in LPP"

    # ── Rule 6b: PTR not owned by Headless team ───────────────────────────────
    # PTR issues are pulled in by the sprint filter but have no Headless team
    # check elsewhere.  Exclude any PTR where customfield_10001 (Team) does not
    # contain "Headless".  This mirrors the non-Headless LPD rule (Rule 5).
    if project == "PTR":
        headless_team = team and "Headless" in team
        if not headless_team:
            return "Non-Headless PTR"

    # ── Rule 7: BPR status exclusions ────────────────────────────────────────
    if project == "BPR":
        _BPR_PRE_ACTIVE = {"open", "scheduled", "awaiting original fix"}
        _BPR_POST_ACTIVE = {"passed review", "closed", "resolved", "completed"}

        if status in _BPR_PRE_ACTIVE:
            return "BPR pre-active"
        if status == "in review":
            return "BPR In Review"
        if status in _BPR_POST_ACTIVE:
            return "BPR post-active"

        # ── Rule 8: BPR EE Fix Pack assignee → skip from Pick Up Next ────────
        # Only exclude a BPR in Original Fix Committed if the assignee is "EE Fix Pack".
        # (Previously used LBM comment detection — removed per team preference.)
        if status == "original fix committed" and issue.get("assignee") == "EE Fix Pack":
            return "BPR EE Fix Pack assignee"

    return None  # keep the issue


# ── Unit tests for exclusion rules ───────────────────────────────────────────
# Each function is self-contained and can be run in isolation.
# Call run_exclusion_tests() to execute all of them.

def _mock_issue(**overrides) -> dict:
    """Return a minimal parsed issue dict, with fields overrideable by kwargs."""
    base = {
        "key": "LPD-99999",
        "project": "LPD",
        "summary": "Test issue",
        "status": "in progress",
        "status_raw": "In Progress",
        "assignee": "Test User",
        "assignee_id": "test-account-id",
        "labels": [],
        "issuetype": "Bug",
        "priority": "Major",
        "tshirt": "M",
        "heat_score": "",
        "parent_key": "",
        "parent_summary": "",
        "team": "Headless",
        "sprint_name": "HL Sprint 1",
        "updated": "2026-05-20T10:00:00.000+0000",
        "created": "2026-05-01T10:00:00.000+0000",
        "duedate": "",
        "comments": [],
        "issuelinks": [],
    }
    base.update(overrides)
    return base


class _MockCtx:
    """Minimal SprintContext mock for exclusion tests."""
    account_ids = {"Test User": "test-account-id", "Other User": "other-account-id"}


def test_exclusion_board_out():
    issue = _mock_issue(labels=["headless-board-out", "some-other-label"])
    result = should_exclude(issue, set(), _MockCtx())
    assert result == "headless-board-out", f"Expected 'headless-board-out', got {result!r}"
    print("  ✓ test_exclusion_board_out")


def test_exclusion_discovery_task_type():
    issue = _mock_issue(issuetype="Discovery Task")
    result = should_exclude(issue, set(), _MockCtx())
    assert result == "Discovery Task", f"Expected 'Discovery Task', got {result!r}"
    print("  ✓ test_exclusion_discovery_task_type")


def test_exclusion_discovery_task_assignee():
    # Designer assigned to "in design" status with no other exclusion reason → keep
    issue = _mock_issue(assignee_id=ANTONIO_JIMENO_ID, status="in design")
    result = should_exclude(issue, set(), _MockCtx())
    assert result is None, f"Designer assignee no longer auto-excluded, got {result!r}"
    issue2 = _mock_issue(assignee_id=UGE_ORTIZ_ID, status="in design")
    result2 = should_exclude(issue2, set(), _MockCtx())
    assert result2 is None, f"Designer assignee no longer auto-excluded, got {result2!r}"
    print("  ✓ test_exclusion_discovery_task_assignee")


def test_exclusion_brian_chan_in_review():
    # Should exclude: LPD + in review + Brian Chan
    issue = _mock_issue(project="LPD", status="in review", assignee_id=BRIAN_CHAN_ID)
    result = should_exclude(issue, set(), _MockCtx())
    assert result == "Brian Chan In Review", f"Got {result!r}"
    # Should exclude: LPD + in review + non-Headless assignee (e.g. PT User Core Infrastructure)
    issue_non_hl = _mock_issue(project="LPD", status="in review", assignee_id="some-other-team-id",
                               team="Headless")
    result_non_hl = should_exclude(issue_non_hl, set(), _MockCtx())
    assert result_non_hl == "LPD In Review — non-Headless assignee (waiting for merge)", \
        f"Non-Headless In Review should be excluded, got {result_non_hl!r}"
    # Should NOT exclude: LPD + in review + known Headless team member
    issue2 = _mock_issue(project="LPD", status="in review", assignee_id="test-account-id",
                         team="Headless")
    result2 = should_exclude(issue2, set(), _MockCtx())
    assert result2 is None, f"Headless-assigned In Review should be kept, got {result2!r}"
    print("  ✓ test_exclusion_brian_chan_in_review")


def test_exclusion_in_design():
    # In Design with any assignee → keep (routes to Section 2)
    issue = _mock_issue(project="LPD", status="in design", assignee_id="some-dev-id")
    result = should_exclude(issue, set(), _MockCtx())
    assert result is None, f"In Design (non-designer) should be kept for Section 2, got {result!r}"
    # In Design assigned to Antonio → also kept now (designer exclusion rule removed)
    issue2 = _mock_issue(project="LPD", status="in design", assignee_id=ANTONIO_JIMENO_ID)
    result2 = should_exclude(issue2, set(), _MockCtx())
    assert result2 is None, f"Designer in In Design should now be kept, got {result2!r}"
    print("  ✓ test_exclusion_in_design")


def test_exclusion_non_headless_lpd():
    # No team, no HL sprint, no headless assignee → exclude
    issue = _mock_issue(project="LPD", team="", sprint_name="OTHER-1",
                        assignee_id="unknown-id", key="LPD-00001")
    result = should_exclude(issue, set(), _MockCtx())
    assert result == "Non-Headless LPD", f"Got {result!r}"
    # Has Headless team → keep
    issue2 = _mock_issue(project="LPD", team="Headless Portal", sprint_name="OTHER-1",
                         assignee_id="unknown-id", key="LPD-00002")
    result2 = should_exclude(issue2, set(), _MockCtx())
    assert result2 is None, f"Headless team issue should be kept, got {result2!r}"
    # HL sprint → keep
    issue3 = _mock_issue(project="LPD", team="", sprint_name="HL Sprint 5",
                         assignee_id="unknown-id", key="LPD-00003")
    result3 = should_exclude(issue3, set(), _MockCtx())
    assert result3 is None, f"HL sprint issue should be kept, got {result3!r}"
    # Headless assignee → keep
    issue4 = _mock_issue(project="LPD", team="", sprint_name="OTHER-1",
                         assignee_id="test-account-id", key="LPD-00004")
    result4 = should_exclude(issue4, set(), _MockCtx())
    assert result4 is None, f"Headless assignee issue should be kept, got {result4!r}"
    # SEV key bypasses this check entirely
    issue5 = _mock_issue(project="LPD", team="", sprint_name="OTHER-1",
                         assignee_id="unknown-id", key="LPD-00005")
    result5 = should_exclude(issue5, {"LPD-00005"}, _MockCtx())
    assert result5 is None, f"SEV key should bypass Non-Headless check, got {result5!r}"
    print("  ✓ test_exclusion_non_headless_lpd")


def test_exclusion_lpp_comba_in():
    issue = _mock_issue(project="LPP", key="LPP-99999", labels=["comba-in"])
    result = should_exclude(issue, set(), _MockCtx())
    assert result == "comba-in LPP", f"Got {result!r}"
    # Without the label → keep
    issue2 = _mock_issue(project="LPP", key="LPP-99998", labels=[])
    result2 = should_exclude(issue2, set(), _MockCtx())
    assert result2 is None, f"LPP without comba-in should be kept, got {result2!r}"
    print("  ✓ test_exclusion_lpp_comba_in")


def test_exclusion_bpr_statuses():
    ctx = _MockCtx()
    for s in ("open", "scheduled", "awaiting original fix"):
        issue = _mock_issue(project="BPR", key="BPR-1", status=s)
        result = should_exclude(issue, set(), ctx)
        assert result == "BPR pre-active", f"status={s!r} → got {result!r}"
    issue_ir = _mock_issue(project="BPR", key="BPR-2", status="in review")
    assert should_exclude(issue_ir, set(), ctx) == "BPR In Review"
    for s in ("passed review", "closed", "resolved", "completed"):
        issue = _mock_issue(project="BPR", key="BPR-3", status=s)
        result = should_exclude(issue, set(), ctx)
        assert result == "BPR post-active", f"status={s!r} → got {result!r}"
    print("  ✓ test_exclusion_bpr_statuses")


def test_exclusion_bpr_ee_fix_pack():
    ctx = _MockCtx()
    # BPR with EE Fix Pack assignee in Original Fix Committed → exclude
    issue_ee = _mock_issue(project="BPR", key="BPR-10", status="original fix committed", assignee="EE Fix Pack")
    assert should_exclude(issue_ee, set(), ctx) == "BPR EE Fix Pack assignee", f"Got {should_exclude(issue_ee, set(), ctx)!r}"
    # BPR with real assignee in Original Fix Committed → keep
    issue_real = _mock_issue(project="BPR", key="BPR-11", status="original fix committed", assignee="Some Person")
    assert should_exclude(issue_real, set(), ctx) is None, "Real assignee BPR should be kept"
    # BPR in progress (any assignee) → keep
    issue_inprog = _mock_issue(project="BPR", key="BPR-12", status="in progress", assignee="EE Fix Pack")
    assert should_exclude(issue_inprog, set(), ctx) is None, "In-progress BPR should not be excluded by EE Fix Pack rule"
    print("  ✓ test_exclusion_bpr_ee_fix_pack")


def test_exclusion_non_headless_ptr():
    ctx = _MockCtx()
    # PTR with no Headless team → exclude
    issue = _mock_issue(project="PTR", key="PTR-1", team="Portal Team", assignee_id="test-account-id")
    result = should_exclude(issue, set(), ctx)
    assert result == "Non-Headless PTR", f"Got {result!r}"
    # PTR with empty team → exclude
    issue2 = _mock_issue(project="PTR", key="PTR-2", team="", assignee_id="test-account-id")
    result2 = should_exclude(issue2, set(), ctx)
    assert result2 == "Non-Headless PTR", f"Got {result2!r}"
    # PTR with Headless team → keep
    issue3 = _mock_issue(project="PTR", key="PTR-3", team="Headless Portal", assignee_id="test-account-id")
    result3 = should_exclude(issue3, set(), ctx)
    assert result3 is None, f"Headless PTR should be kept, got {result3!r}"
    print("  ✓ test_exclusion_non_headless_ptr")


def run_exclusion_tests():
    """Run all exclusion rule unit tests. Call with: python3 headless_daily_report.py --test-exclusions"""
    print("\n[run_exclusion_tests]")
    test_exclusion_board_out()
    test_exclusion_discovery_task_type()
    test_exclusion_discovery_task_assignee()
    test_exclusion_brian_chan_in_review()
    test_exclusion_in_design()
    test_exclusion_non_headless_lpd()
    test_exclusion_lpp_comba_in()
    test_exclusion_bpr_statuses()
    test_exclusion_bpr_ee_fix_pack()
    test_exclusion_non_headless_ptr()
    print("  All exclusion tests passed ✓\n")


# ════════════════════════════════════════════════════════════════════════════════
# CHUNK 5 — Tier classification + LPP visibility
# classify_tier: given a parsed issue + key sets → (tier_num, tier_key)
# lpp_should_show: LPP Solution Proposed visibility gate
# ════════════════════════════════════════════════════════════════════════════════

def _last_comment_date(issue: dict) -> str:
    """
    Return the date portion (YYYY-MM-DD) of the last comment, or issue created date.
    Used by both classify_tier (for 7.1) and lpp_should_show.
    """
    comments = issue.get("comments") or []
    if comments:
        return comments[-1]["created"][:10]
    return issue["created"][:10]


def classify_tier(
    issue: dict,
    sev_keys: set[str],
    sev_zero_day_keys: set[str],
    sev_bpr_keys: set[str],
) -> tuple[float, str]:
    """
    Return (tier_num, tier_key) for the issue.
    tier_key is the string key into TIER_COLORS (e.g. "7.1", "13").
    tier_num is the numeric equivalent for sorting (7.1 → 7.1, etc.).

    Label overrides are applied FIRST before the tier table:
      - headless-expedite → always wins (tier 2), including over tier 1.x
      - headless-focus    → wins only over the tier 13 fallthrough (not over tiers 1–12)

    Then the tier table is evaluated top-to-bottom; first match wins.
    """
    key = issue["key"]
    project = issue["project"]
    priority = issue["priority"]
    labels = issue["labels"]      # full list — never truncate
    issuetype = issue["issuetype"]
    duedate = issue.get("duedate", "") or ""

    today_str = str(date.today())

    # ── Label override 1: headless-expedite → Tier 2 (LPD only) ─────────────
    # Applied before any tier evaluation, including before tier 1.x.
    # Only LPD issues use this label; BPR/LPP/PTR are never expedited this way.
    if project == "LPD" and "headless-expedite" in labels:
        return (2.0, "2")

    # ── Tier 1.1 — Zero-day SEV (LPD) ────────────────────────────────────────
    if project == "LPD" and key in sev_zero_day_keys:
        return (1.1, "1.1")

    # ── Tier 1.2 — Critical/Fire LPP ─────────────────────────────────────────
    if project == "LPP" and priority in ("Critical", "Fire"):
        return (1.2, "1.2")

    # ── Tier 2 — Expedite (already handled above via label override) ──────────
    # (headless-expedite was caught at the top; this branch is unreachable but
    #  listed for documentation completeness — no code needed)

    # ── Tier 3 — LPD release blockers ────────────────────────────────────────
    if project == "LPD" and (
        "7.4-blocker" in labels or "release-blocker" in labels
    ):
        return (3.0, "3")

    # ── Tier 4 — LPD SEV (non-zero-day) ──────────────────────────────────────
    # SEV classification comes from the sev_keys set (dedicated JQL query),
    # NOT from labels. An issue with empty labels can still be Tier 4.
    if project == "LPD" and key in sev_keys:
        # key not in sev_zero_day_keys is guaranteed (tier 1.1 already returned)
        return (4.0, "4")

    # ── Tier 5 — SEV BPR ─────────────────────────────────────────────────────
    if project == "BPR" and key in sev_bpr_keys:
        return (5.0, "5")

    # ── Tier 6 — Release BPR ─────────────────────────────────────────────────
    if project == "BPR" and "headless-release-bpr" in labels:
        return (6.0, "6")

    # ── Tiers 7.x — LPP customer issue types ─────────────────────────────────
    if project == "LPP" and "teg" not in labels:
        # Determine last comment date for 7.1 check
        lcd = _last_comment_date(issue)

        if issuetype == "Customer Issue":
            if duedate and duedate < today_str:
                # Over forecast — check whether update is also stale
                five_days_ago = str(date.today() - timedelta(days=5))
                if lcd < five_days_ago:
                    return (7.1, "7.1")   # Over forecast + no update in 5d
                return (7.2, "7.2")       # Over forecast (recent activity)
            return (7.3, "7.3")           # Customer Issue (not over forecast)

        if issuetype == "Customer Fix Management":
            return (7.4, "7.4")

        if issuetype == "Customer Issue Analysis":
            return (7.5, "7.5")

    # ── Tier 8 — BPR (non-SEV, non-release) ──────────────────────────────────
    if project == "BPR":
        return (8.0, "8")

    # ── Tier 9 — PTR ─────────────────────────────────────────────────────────
    if project == "PTR":
        return (9.0, "9")

    # ── Label override 2: headless-focus → Tier 12 (LPD only) ───────────────
    # Applied here, after all unplanned tiers, so it only promotes LPD issues
    # that would otherwise fall into tier 13 (Regular planned work).
    # BPR/LPP/PTR issues never use this label.
    if project == "LPD" and "headless-focus" in labels:
        return (12.0, "12")

    # ── Tier 13 — LPD regular planned work (fallthrough) ─────────────────────
    return (13.0, "13")


def lpp_should_show(issue: dict, ctx: "SprintContext") -> bool:
    """
    Gate for LPP issues in 'solution proposed' status.
    Returns True (show in Section 1) if either:
      - A new comment was added since the last snapshot run, OR
      - today − last_comment_date > 5 days
    Otherwise returns False (hide the issue entirely).

    Only called for LPP issues where status == 'solution proposed'.
    """
    key = issue["key"]
    lcd = _last_comment_date(issue)
    today = date.today()

    # Condition 1: new comment since last snapshot
    snapshot_date = (ctx.state_snapshot or {}).get("date", "")
    if snapshot_date and lcd > snapshot_date:
        return True

    # Condition 2: last comment is more than 5 days old
    try:
        lcd_date = date.fromisoformat(lcd)
        if (today - lcd_date).days > 5:
            return True
    except ValueError:
        # Malformed date — fail safe: show the issue
        print(f"  [lpp_should_show] WARNING: malformed last_comment_date {lcd!r} for {key}")
        return True

    return False


# ════════════════════════════════════════════════════════════════════════════════
# CHUNK 6 — Section routing
# Decides which section (1, 2a, 2b, or None) each classified issue belongs to.
# Also merges open PRs into their parent issue rows (or marks them standalone).
# ════════════════════════════════════════════════════════════════════════════════

# Section 1 statuses — issue must be in one of these to appear in "In Progress"
# All values are lowercase (matching parse_issue normalisation).
SECTION1_STATUSES: dict[str, frozenset[str]] = {
    "LPD": frozenset({
        "in progress",
        "in development",
        "escalated",
        "in product review",
        "ready for product review",
        # Note: "in review" is NOT here — Brian Chan In Review is excluded
        # entirely; other "in review" LPD issues survive exclusion but route
        # normally based on their actual Section 1 eligibility.
        "in review",
    }),
    "LPP": frozenset({
        "in analysis",
        "pending",
        "in progress",
        "escalated",
        "solution proposed",   # only shown when lpp_should_show() returns True
    }),
    "BPR": frozenset({
        # Statuses strictly AFTER Original Fix Committed (not OFC itself)
        "in progress",
        "verification",
    }),
    "PTR": frozenset({
        # PTR: any non-closed, non-not-started status is Section 1
        # We define the known active statuses; anything unlisted → None
        "in progress",
        "open",
        "in review",
        "in testing",
        "reopened",
    }),
}

# Section 2 statuses — issue is ready to be picked up
SECTION2_STATUSES: dict[str, frozenset[str]] = {
    "LPD": frozenset({
        "open",
        "selected for development",
        "ready for development",
        "in design",              # pre-development; routes to Section 2 (not Section 1)
        "ready for refinement",
        "in refinement",
        "ready for research",
    }),
    "LPP": frozenset({
        "in queue",
        "open",
        "new",
    }),
    "BPR": frozenset({
        "original fix committed",   # explicitly Section 2, not Section 1
    }),
    "PTR": frozenset(),             # PTR has no Section 2 items
}

# Account names/IDs that mean "effectively unassigned" for Section 2 routing
_UNASSIGNED_NAMES: frozenset[str] = frozenset({"EE Fix Pack"})


def route_issue(issue: dict, tier_num: float, lpp_visible: bool) -> str | None:
    """
    Decide which section the issue belongs to.
    Returns "1", "2a", "2b", or None (not shown).

    Rules applied in order:
      1. BPR 'original fix committed' → always Section 2 (never Section 1)
      2. LPP 'solution proposed' → Section 1 only if lpp_visible, else None
      3. Status in SECTION1_STATUSES[project] → "1"
      4. Status in SECTION2_STATUSES[project]:
           - real assignee (not PT User Headless, not empty, not EE Fix Pack) → "2a"
           - otherwise → "2b"
      5. Otherwise → None
    """
    project = issue["project"]
    status = issue["status"]       # already lowercased by parse_issue
    assignee = issue["assignee"]
    assignee_id = issue["assignee_id"]

    # ── Rule 1: BPR Original Fix Committed → Section 2 ───────────────────────
    if project == "BPR" and status == "original fix committed":
        return _section2_bucket(assignee, assignee_id)

    # ── Rule 2: LPP Solution Proposed → Section 1 only if visible ────────────
    if project == "LPP" and status == "solution proposed":
        if lpp_visible:
            return "1"
        return None

    # ── Rule 3: Section 1 ────────────────────────────────────────────────────
    section1 = SECTION1_STATUSES.get(project, frozenset())
    if status in section1:
        return "1"

    # ── Rule 4: Section 2 ────────────────────────────────────────────────────
    section2 = SECTION2_STATUSES.get(project, frozenset())
    if status in section2:
        return _section2_bucket(assignee, assignee_id)

    # ── Rule 5: Not shown ────────────────────────────────────────────────────
    return None


def _section2_bucket(assignee: str, assignee_id: str) -> str:
    """
    Return "2a" (assigned, real person) or "2b" (needs owner).
    "Needs owner" means: no assignee, PT User Headless, or EE Fix Pack.
    """
    if not assignee_id:
        return "2b"
    if assignee_id == PT_HEADLESS_ID:
        return "2b"
    if assignee in _UNASSIGNED_NAMES:
        return "2b"
    return "2a"


def merge_prs_to_issues(
    issues_dict: dict[str, dict],
    prs: list[dict],
    ctx: "SprintContext",
) -> tuple[list[dict], list[dict]]:
    """
    Attach each open PR to its matching issue row, or mark it as standalone.

    Match priority (stop at first match):
      1. parent_key in issues_dict → attach to parent row
      2. lpp_fix_key in issues_dict → attach to LPP row
      3. jira_key in issues_dict → direct match (e.g. the issue itself is in scope)
      4. jira_key is a subtask → live Jira lookup to resolve parent, then retry 1–3
      5. No match after all steps → standalone PR row

    Step 4 is the critical fallback: if parent_key was not pre-populated in the
    pr_data.json file, we call jira_get_issue on the linked jira_key to fetch
    its parent field. This prevents subtask-linked PRs from becoming standalone rows.

    Returns:
      - issues_with_prs: list of issue dicts, each with an 'attached_prs' list
      - standalone_prs:  list of PR dicts with no matching issue

    Side effect: adds 'attached_prs' key to every issue dict in issues_dict.
    """
    # Initialise attached_prs on every issue so callers can always iterate
    for issue in issues_dict.values():
        issue.setdefault("attached_prs", [])

    standalone_prs: list[dict] = []

    for pr in prs:
        parent_key = pr.get("parent_key")
        lpp_fix_key = pr.get("lpp_fix_key")
        jira_key = pr.get("jira_key")

        matched = False

        # Priority 1: parent issue in scope
        if parent_key and parent_key in issues_dict:
            issues_dict[parent_key]["attached_prs"].append(pr)
            print(f"  [merge_prs] PR#{pr['pr_number']} → attached to parent {parent_key}")
            matched = True

        # Priority 2: linked LPP issue in scope
        elif lpp_fix_key and lpp_fix_key in issues_dict:
            issues_dict[lpp_fix_key]["attached_prs"].append(pr)
            print(f"  [merge_prs] PR#{pr['pr_number']} → attached to LPP fix {lpp_fix_key}")
            matched = True

        # Priority 3: linked Jira key is itself in scope (top-level issue)
        elif jira_key and jira_key in issues_dict:
            issues_dict[jira_key]["attached_prs"].append(pr)
            print(f"  [merge_prs] PR#{pr['pr_number']} → direct match {jira_key}")
            matched = True

        # Priority 4: live parent lookup for subtasks
        # If parent_key was missing/null from pr_data.json AND jira_key is not
        # itself in scope, do a live Jira call to resolve the parent.
        elif jira_key and not matched:
            print(f"  [merge_prs] PR#{pr['pr_number']}: no match yet — fetching parent of {jira_key}")
            try:
                raw = jira_get_issue(jira_key, fields=["parent", "issuetype", "issuelinks"])
                fields = raw.get("fields", {})
                resolved_parent = (fields.get("parent") or {}).get("key", "")

                # Also check LPP→LPD fix link: look for linked LPP in issuelinks
                resolved_lpp = None
                for link in fields.get("issuelinks") or []:
                    inward_key  = (link.get("inwardIssue")  or {}).get("key", "")
                    outward_key = (link.get("outwardIssue") or {}).get("key", "")
                    for lk in (inward_key, outward_key):
                        if lk and lk.startswith("LPP-") and lk in issues_dict:
                            resolved_lpp = lk
                            break
                    if resolved_lpp:
                        break

                if resolved_parent and resolved_parent in issues_dict:
                    # Update the PR dict so downstream code has the correct parent_key
                    pr["parent_key"] = resolved_parent
                    issues_dict[resolved_parent]["attached_prs"].append(pr)
                    print(f"  [merge_prs] PR#{pr['pr_number']} → live-resolved parent {resolved_parent}")
                    matched = True
                elif resolved_lpp:
                    pr["lpp_fix_key"] = resolved_lpp
                    issues_dict[resolved_lpp]["attached_prs"].append(pr)
                    print(f"  [merge_prs] PR#{pr['pr_number']} → live-resolved LPP fix {resolved_lpp}")
                    matched = True
                else:
                    print(f"  [merge_prs] PR#{pr['pr_number']}: live lookup found "
                          f"parent={resolved_parent!r} — not in scope → standalone")
            except Exception as exc:
                print(f"  [merge_prs] PR#{pr['pr_number']}: live lookup failed: {exc} → standalone")

        if not matched:
            print(f"  [merge_prs] PR#{pr['pr_number']} → standalone "
                  f"(parent={parent_key}, lpp_fix={lpp_fix_key}, jira={jira_key})")
            standalone_prs.append(pr)

    return list(issues_dict.values()), standalone_prs


# ════════════════════════════════════════════════════════════════════════════════
# CHUNK 7 — Days calculation + cache
# get_first_active_date: reads/writes ctx.changelog_cache, fetches changelog
# compute_days_active_cell: Section 1 "Days in Progress" cell string
# compute_days_queue_cell: Section 2 "Days in Queue" cell string
# ════════════════════════════════════════════════════════════════════════════════

# Statuses that count as "actively worked on" for LPD changelog scanning.
_LPD_ACTIVE_STATUSES: frozenset[str] = frozenset({"in development", "in progress"})

# Statuses that follow "Original Fix Committed" in BPR workflow.
_BPR_POST_OFC_STATUSES: frozenset[str] = frozenset({"in progress", "verification"})

# Sentinel written to cache when a changelog was fetched but no matching
# transition was found.  Distinct from None, which means "not yet looked up".
_NO_TRANSITION = "NO_TRANSITION"


def get_first_active_date(issue: dict, ctx: "SprintContext") -> str | None:
    """
    Return the first_active_date string (YYYY-MM-DD) for the issue, or
    _NO_TRANSITION if the changelog was checked but no qualifying transition
    was found.

    Cache semantics
    ───────────────
    - Cache hit (any value, including _NO_TRANSITION) → return immediately,
      UNLESS the LPD cache-invalidation rule fires (see below).
    - Cache miss → fetch changelog, compute date, write to cache, return.

    LPD cache invalidation
    ──────────────────────
    If ALL of these are true, re-fetch and recompute:
      1. project == "LPD"
      2. Cached date is not _NO_TRANSITION
      3. Cached date predates sprint start by > 30 days
      4. Current status is "in progress" or "in development"
    (The issue may have been sent back to Open and restarted; we need the
    most-recent transition, not the first one from a previous sprint cycle.)

    Project-specific logic
    ──────────────────────
    LPD : most-recent transition TO "In Development" or "In Progress"
          (scan reversed changelog — first match in reverse order is the latest)
    LPP : earliest transition TO "In Queue"
          permitted fallback: issue["created"][:10] if no transition found
    BPR : earliest transition TO any status after "Original Fix Committed"
          (i.e. in _BPR_POST_OFC_STATUSES)

    CRITICAL: never write today's date, the run date, or issue["created"] for
    LPD or BPR.  The only permitted fallback is LPP → issue.created.
    """
    key = issue["key"]
    project = issue["project"]
    status = issue["status"]   # already lowercased

    cached = ctx.changelog_cache.get(key)

    # ── Cache invalidation check for LPD ─────────────────────────────────────
    need_fetch = False
    if cached is None:
        need_fetch = True
    elif (
        project == "LPD"
        and cached != _NO_TRANSITION
        and status in _LPD_ACTIVE_STATUSES
    ):
        try:
            cached_date = date.fromisoformat(cached)
            days_before_sprint = (ctx.start_date - cached_date).days
            if days_before_sprint > 30:
                print(f"  [get_first_active_date] {key}: cache invalidated "
                      f"(cached={cached}, sprint_start={ctx.start_date}, "
                      f"delta={days_before_sprint}d) — re-fetching")
                need_fetch = True
        except ValueError:
            pass  # malformed cached date — treat as cache miss

    if not need_fetch:
        return cached  # may be a date string or _NO_TRANSITION

    # ── Fetch changelog (pre-fetched data takes priority over live HTTPS) ─────
    # ctx.changelogs is populated from jira_data.json when Claude pre-fetches all
    # changelogs via the Jira MCP during data collection.  This avoids proxy
    # failures in the Claude sandbox and is faster than individual HTTPS calls.
    if key in ctx.changelogs:
        print(f"  [get_first_active_date] {key}: using pre-fetched changelog")
        histories = ctx.changelogs[key]
    else:
        print(f"  [get_first_active_date] {key}: fetching changelog via HTTPS")
        try:
            raw = jira_get_issue(key, expand="changelog")
        except Exception as exc:
            print(f"    WARNING: changelog fetch failed for {key}: {exc}")
            # Do not write anything to cache — leave for retry next run
            return None
        histories = (raw.get("changelog") or {}).get("histories") or []

    # ── LPD: most-recent transition to In Development / In Progress ───────────
    if project == "LPD":
        result = None
        # Scan in reverse to find the latest qualifying transition
        for history in reversed(histories):
            created_str = history.get("created", "")[:10]
            for item in (history.get("items") or []):
                if item.get("field", "").lower() == "status":
                    to_val = (item.get("toString") or "").lower()
                    if to_val in _LPD_ACTIVE_STATUSES:
                        result = created_str
                        break  # first match in reverse = most recent
            if result:
                break

        stored = result if result else _NO_TRANSITION
        ctx.changelog_cache[key] = stored
        print(f"    {key}: LPD first_active_date = {stored}")
        return stored

    # ── LPP: earliest transition to In Queue ─────────────────────────────────
    if project == "LPP":
        result = None
        for history in histories:   # forward order → first match = earliest
            created_str = history.get("created", "")[:10]
            for item in (history.get("items") or []):
                if item.get("field", "").lower() == "status":
                    to_val = (item.get("toString") or "").lower()
                    if to_val == "in queue":
                        result = created_str
                        break
            if result:
                break

        if result is None:
            # Only permitted fallback: use issue.created
            result = issue["created"][:10]
            print(f"    {key}: LPP no In Queue transition — falling back to created={result}")
        else:
            print(f"    {key}: LPP first_active_date (In Queue) = {result}")

        ctx.changelog_cache[key] = result
        return result

    # ── BPR: earliest transition to a post-OFC active status ─────────────────
    if project == "BPR":
        result = None
        for history in histories:   # forward order → first match = earliest
            created_str = history.get("created", "")[:10]
            for item in (history.get("items") or []):
                if item.get("field", "").lower() == "status":
                    to_val = (item.get("toString") or "").lower()
                    if to_val in _BPR_POST_OFC_STATUSES:
                        result = created_str
                        break
            if result:
                break

        stored = result if result else _NO_TRANSITION
        ctx.changelog_cache[key] = stored
        print(f"    {key}: BPR first_active_date = {stored}")
        return stored

    # ── Unknown project — return None without writing to cache ────────────────
    print(f"    {key}: unknown project {project!r} — skipping cache write")
    return None


def compute_days_active_cell(issue: dict, first_active_date: str | None) -> str:
    """
    Build the Section 1 "Days in Progress / T-shirt Size" cell string.

    Rules per project:
      LPD, date found : "{N}d in progress ({tshirt}) 🟠/🔴"  (emoji only if crossed)
      LPD, NO_TRANSITION: "{Status}" (status name only — no number)
      LPP, date found : "{N}d in progress 🟠/🔴"
      BPR, date found : "{N}d in progress"
      BPR, NO_TRANSITION: "{Status}"
      PR standalone   : "PR · {N}d open"   (caller passes open_days as int via
                         a synthetic first_active_date — see compute_pr_days_cell)

    Threshold comparisons use strict >  (">2d" means days > 2, i.e. ≥ 3).
    Red takes precedence over orange.
    """
    project = issue.get("project", "")
    tshirt = issue.get("tshirt", "")
    today = date.today()

    # Helper: compute days from a YYYY-MM-DD string
    def _days_since(date_str: str) -> int:
        try:
            return max(0, (today - date.fromisoformat(date_str)).days)
        except ValueError:
            return 0

    # NO_TRANSITION or None → show status name only
    if not first_active_date or first_active_date == _NO_TRANSITION:
        return issue.get("status_raw", issue.get("status", ""))

    days = _days_since(first_active_date)

    if project == "LPD":
        size = tshirt.upper() if tshirt else ""
        orange_t = LPD_ORANGE_THRESHOLD.get(size, LPD_ORANGE_THRESHOLD[""])
        red_t = LPD_RED_THRESHOLD.get(size, LPD_RED_THRESHOLD[""])

        emoji = ""
        if days > red_t:
            emoji = " 🔴"
        elif days > orange_t:
            emoji = " 🟠"

        size_part = f" ({tshirt})" if tshirt else ""
        return f"{days}d in progress{size_part}{emoji}"

    if project == "LPP":
        # LPP Days in Progress = days since creation (not first_active_date)
        lpp_days = _days_since(issue["created"][:10]) if issue.get("created") else days
        emoji = ""
        if lpp_days > LPP_RED_THRESHOLD:
            emoji = " 🔴"
        elif lpp_days > LPP_ORANGE_THRESHOLD:
            emoji = " 🟠"
        return f"{lpp_days}d in progress{emoji}"

    if project == "BPR":
        return f"{days}d in progress"

    # Fallback for any other project
    return f"{days}d in progress"


def compute_pr_days_active_cell(open_days: int) -> str:
    """
    Build the Section 1 Days cell for a standalone PR row.
    Kept separate so compute_days_active_cell stays issue-only.
    """
    return f"PR · {open_days}d open"


def compute_days_queue_cell(issue: dict, ctx: "SprintContext", section: str = "") -> str:
    """
    Build the Section 2 "Days in Queue" cell string.

    section: pass "2b" to enable LPP Needs Owner queue-time emoji highlighting.

    Rules per project:
      LPD regular : days since first added to any sprint (from sprint field)
                    Format: "{N}d in sprint" or "New" if 0 days
      LPD SEV     : days since issue.created → "{N}d since creation"
      LPP         : days since first In Queue transition (via get_first_active_date)
                    Format: "{N}d in queue"
                    Section 2b only: append 🟠 if >3d and ≤7d, 🔴 if >7d
      BPR         : days since first transition to Original Fix Committed
                    Format: "{N}d since committed"
    """
    project = issue["project"]
    key = issue["key"]
    today = date.today()

    def _days_since_str(date_str: str) -> int:
        try:
            return max(0, (today - date.fromisoformat(date_str[:10])).days)
        except ValueError:
            return 0

    # ── LPP ──────────────────────────────────────────────────────────────────
    if project == "LPP":
        # get_first_active_date returns the In Queue transition date for LPP
        fad = get_first_active_date(issue, ctx)
        if fad and fad != _NO_TRANSITION:
            days = _days_since_str(fad)
        else:
            days = _days_since_str(issue["created"])

        emoji = ""
        if section == "2b":
            if days > 7:
                emoji = " 🔴"
            elif days > 3:
                emoji = " 🟠"

        return f"{days}d in queue{emoji}"

    # ── BPR ──────────────────────────────────────────────────────────────────
    if project == "BPR":
        # Find earliest transition TO "Original Fix Committed" in changelog
        ofc_date = _get_bpr_ofc_date(issue, ctx)
        if ofc_date:
            days = _days_since_str(ofc_date)
            return f"{days}d since committed"
        # Fallback: use created date
        days = _days_since_str(issue["created"])
        return f"{days}d since committed"

    # ── LPD ──────────────────────────────────────────────────────────────────
    if project == "LPD":
        # SEV issues: days since creation
        # We detect "is SEV" via the calling context by checking the cache key
        # directly isn't reliable here, so the caller passes a flag via
        # issue["_is_sev"] if applicable.
        if issue.get("_is_sev"):
            days = _days_since_str(issue["created"])
            return f"{days}d since creation"

        # Regular LPD: days since first added to any sprint
        sprint_days = _get_lpd_sprint_days(issue)
        if sprint_days == 0:
            return "New"
        return f"{sprint_days}d in sprint"

    # ── Fallback ──────────────────────────────────────────────────────────────
    days = _days_since_str(issue["created"])
    return f"{days}d in queue"


def _get_bpr_ofc_date(issue: dict, ctx: "SprintContext") -> str | None:
    """
    Return the YYYY-MM-DD of the earliest transition TO 'Original Fix Committed'
    for a BPR issue.  Fetches changelog if not already in cache (keyed as
    '{key}:ofc').  Returns None if not found.
    """
    key = issue["key"]
    cache_key = f"{key}:ofc"
    cached = ctx.changelog_cache.get(cache_key)
    if cached is not None:
        return cached if cached != _NO_TRANSITION else None

    # Use pre-fetched changelog if available (avoids proxy failures in sandbox)
    if key in ctx.changelogs:
        print(f"  [_get_bpr_ofc_date] {key}: using pre-fetched changelog")
        histories = ctx.changelogs[key]
    else:
        print(f"  [_get_bpr_ofc_date] {key}: fetching changelog via HTTPS")
        try:
            raw = jira_get_issue(key, expand="changelog")
        except Exception as exc:
            print(f"    WARNING: changelog fetch failed for {key}: {exc}")
            return None
        histories = (raw.get("changelog") or {}).get("histories") or []
    result = None
    for history in histories:
        created_str = history.get("created", "")[:10]
        for item in (history.get("items") or []):
            if item.get("field", "").lower() == "status":
                to_val = (item.get("toString") or "").lower()
                if to_val == "original fix committed":
                    result = created_str
                    break
        if result:
            break

    stored = result if result else _NO_TRANSITION
    ctx.changelog_cache[cache_key] = stored
    return result


def _get_lpd_sprint_days(issue: dict) -> int:
    """
    Return days since the issue was first added to any sprint.

    Uses sprint_start_date extracted from customfield_10020 in parse_issue —
    the earliest startDate across all sprint entries on this issue.  This is the
    correct value for "days in sprint": it reflects when the issue actually
    entered a sprint, not when it was created.

    Falls back to issue.created only if no sprint startDate was available in the
    API response (rare — some sprint objects may lack the field).
    """
    today = date.today()
    sprint_start = issue.get("sprint_start_date", "")
    date_str = sprint_start if sprint_start else issue.get("created", "")[:10]
    if not date_str:
        return 0
    try:
        return max(0, (today - date.fromisoformat(date_str)).days)
    except ValueError:
        return 0


# ════════════════════════════════════════════════════════════════════════════════
# CHUNK 8 — Trigger evaluation + action text
# evaluate_triggers: returns list[(trigger_num, action_text)] for all firing triggers
# build_action_text: assembles final Section 1 action cell string
# build_section2_action: Section 2 action cell string
# ════════════════════════════════════════════════════════════════════════════════

def evaluate_triggers(
    issue: dict,
    ctx: "SprintContext",
    days_active: int = 0,
) -> list[tuple[int, str]]:
    """
    Evaluate all Section 1 triggers for the issue.
    Returns a list of (trigger_number, action_text) tuples for every trigger
    that fires.  The caller joins them with ' · '.

    Parameters
    ──────────
    issue      : fully parsed + classified issue dict (must have 'attached_prs')
    ctx        : SprintContext (provides state_snapshot for Trigger 1)
    days_active: precomputed days in active status (for Trigger 7)
    """
    results: list[tuple[int, str]] = []
    key = issue["key"]
    project = issue["project"]
    status = issue["status"]
    issuetype = issue["issuetype"]
    assignee = issue["assignee"]
    assignee_id = issue["assignee_id"]
    labels = issue["labels"]
    tshirt = issue.get("tshirt", "")
    tier_key = issue.get("_tier_key", "")   # set by caller during classification
    duedate = issue.get("duedate", "") or ""
    heat_score = issue.get("heat_score", "")
    today = date.today()
    today_str = str(today)

    def _days_ago(date_str: str) -> int:
        """Days between date_str (YYYY-MM-DD prefix) and today. 0 if invalid."""
        try:
            return max(0, (today - date.fromisoformat(date_str[:10])).days)
        except ValueError:
            return 0

    # ── Trigger 1: Recent real change ────────────────────────────────────────
    # Compare current state against the saved snapshot from the previous run.
    # This snapshot-based approach naturally excludes RemoteWorkItemLink noise:
    # the snapshot records only real field values (status, assignee), so only
    # genuine status/assignee changes show up as differences.  New comments are
    # detected by comparing the last comment's date against the snapshot date.
    # RemoteWorkItemLink changelog entries never affect these fields, so they
    # can never produce a false Trigger 1 fire.
    snapshot_issues = (ctx.state_snapshot or {}).get("issues", {})
    snapshot_date = (ctx.state_snapshot or {}).get("date", "")
    prev = snapshot_issues.get(key, {})

    if prev:
        # Status changed?
        prev_status = prev.get("status", "").lower()
        if status != prev_status and status:
            results.append((1, f"Status changed to {issue.get('status_raw', status)}"))

        # Assignee changed?
        prev_assignee = prev.get("assignee", "")
        if assignee != prev_assignee:
            name = assignee if assignee else "(unassigned)"
            results.append((1, f"Assignee changed to @{name}"))

    # New comment since last snapshot?
    comments = issue.get("comments") or []
    if comments and snapshot_date:
        last_comment_date = comments[-1]["created"][:10]
        if last_comment_date > snapshot_date:
            comment_author_id = comments[-1].get("author_id", "")
            # Resolve display name from account_ids dict (reverse lookup)
            author_display = _resolve_display_name(comment_author_id, ctx)
            results.append((1, f"New comment from @{author_display}"))

    # ── Trigger 2: Lost assignee on active issue ──────────────────────────────
    # Not shown for LPP — LPP action column has its own rules.
    no_assignee = not assignee_id or assignee_id == PT_HEADLESS_ID
    if no_assignee and project != "LPP":
        results.append((2, "No assignee — assign owner"))

    # ── Trigger 3: LPP Solution Proposed stale / Pending stale ───────────────
    if project == "LPP":
        if status == "solution proposed":
            lcd = _last_comment_date(issue)
            if _days_ago(lcd) > 5:
                n = _days_ago(lcd)
                results.append((3, f"Solution Proposed for {n}d with no update — consider closing"))
        elif status == "pending":
            lcd = _last_comment_date(issue)
            if _days_ago(lcd) > 5:
                n = _days_ago(lcd)
                results.append((3, f"Pending for {n}d with no update — consider closing"))

    # ── Trigger 4: LPP over forecast — suppressed; overdue is shown in Days column
    # (LPP action column only shows: new comment, status change, 3d stale, 5d pending, LPD link, heat)

    # ── Trigger 5: PR needs action ────────────────────────────────────────────
    attached_prs = issue.get("attached_prs") or []
    for pr in attached_prs:
        pr_texts = _evaluate_pr_trigger(pr, issue)
        for text in pr_texts:
            results.append((5, text))

    # ── Trigger 6: Stale — no update for N days ───────────────────────────────
    # Does NOT apply to planned LPD Stories/Tasks in tiers 12/13.
    # LPP: 3-day threshold; BPR + LPD Bug: 5-day threshold; PTR: 3-day threshold.
    # LPP uses its own stale text (no assignee mention).
    _stale_exempt_types = {"Story", "Task", "Sub-task"}
    _stale_exempt_tiers = {"12", "13"}
    is_stale_exempt = (
        project == "LPD"
        and issuetype in _stale_exempt_types
        and tier_key in _stale_exempt_tiers
    )

    if not is_stale_exempt:
        updated_str = issue.get("updated", "")[:10] if issue.get("updated") else ""

        if project == "LPP":
            stale_days = 3
        elif project == "PTR":
            stale_days = 3
        else:
            stale_days = 5

        stale_threshold = today - timedelta(days=stale_days)

        is_stale_candidate = False
        if project == "LPP":
            is_stale_candidate = True
        elif project in ("BPR", "PTR"):
            is_stale_candidate = True
        elif project == "LPD" and issuetype == "Bug":
            is_stale_candidate = True  # covers both SEV (6) and non-SEV (6b)

        if is_stale_candidate and updated_str:
            try:
                updated_date = date.fromisoformat(updated_str)
                if updated_date <= stale_threshold:
                    n = (today - updated_date).days
                    if project == "LPP":
                        results.append((6, f"No update in {n}d — check status"))
                    else:
                        name = assignee if assignee else "assignee"
                        results.append((6, f"No update for {n}d — follow up with {name}"))
            except ValueError:
                pass

    # ── Trigger 7: Over orange/red threshold ─────────────────────────────────
    # Only for LPD — LPP threshold info already shown in Days column.
    if days_active > 0 and project == "LPD":
        size = tshirt.upper() if tshirt else ""
        orange_t = LPD_ORANGE_THRESHOLD.get(size, LPD_ORANGE_THRESHOLD[""])
        red_t = LPD_RED_THRESHOLD.get(size, LPD_RED_THRESHOLD[""])

        if days_active > red_t:
            size_part = f" ({tshirt})" if tshirt else ""
            results.append((7, f"{days_active}d in development{size_part} — check for blockers"))
        elif days_active > orange_t:
            size_part = f" ({tshirt})" if tshirt else ""
            results.append((7, f"{days_active}d in development{size_part} — check for blockers"))

    return results


def _resolve_display_name(account_id: str, ctx: "SprintContext") -> str:
    """
    Reverse-lookup a display name from ctx.account_ids (name → id dict).
    Returns the display name if found, otherwise the account_id itself.
    """
    if not account_id:
        return "unknown"
    for name, aid in ctx.account_ids.items():
        if aid == account_id:
            return name
    return account_id


def _evaluate_pr_trigger(pr: dict, issue: dict) -> list[str]:
    """
    Evaluate Trigger 5 for a single PR attached to an issue.
    Returns a list of action text strings (usually 0 or 1 item).

    PR action text (non-standalone):
      No reviewer, open >1d   : "PR#{N} — no reviewer assigned; sender must assign reviewer and update ticket"
      Reviewer idle >1d       : "PR#{N} — waiting for review from {reviewer} ({N}d)"
      Changes requested >1d   : "PR#{N} — {author} needs to address review comments ({N}d)"
      Subtask PR prefix       : "PR#{N} (subtask {KEY}) — ..."
      LPP→LPD fix PR prefix   : "PR#{N} (LPD-XXXXX) — ..."
    """
    pr_number = pr.get("pr_number", "?")
    author = pr.get("author", "")
    reviewer = pr.get("reviewer")
    reviewer_status = pr.get("reviewer_status") or ""
    open_days = pr.get("open_days", 0)
    jira_key = pr.get("jira_key", "")
    lpp_fix_key = pr.get("lpp_fix_key", "")

    texts: list[str] = []

    # Build prefix for subtask or LPP→LPD fix PRs
    prefix = f"PR#{pr_number}"
    if jira_key and jira_key != issue.get("key", "") and jira_key.startswith("LPD-"):
        # PR linked to a subtask/Technical Task
        prefix = f"PR#{pr_number} (subtask {jira_key})"
    elif lpp_fix_key:
        prefix = f"PR#{pr_number} ({lpp_fix_key})"

    # All open PRs always appear — no open_days threshold suppression.
    if not reviewer:
        texts.append(
            f"{prefix} — no reviewer assigned"
        )
    elif reviewer_status.upper() == "CHANGES_REQUESTED":
        texts.append(
            f"{prefix} — changes requested by {reviewer} — author must address ({open_days}d)"
        )
    elif reviewer_status.upper() in ("", "COMMENTED", "PENDING"):
        texts.append(
            f"{prefix} — waiting for review from {reviewer} ({open_days}d)"
        )
    # APPROVED → no action needed; don't emit trigger text

    return texts


def _evaluate_standalone_pr_trigger(pr: dict) -> str:
    """
    Build the action cell text for a standalone PR row (no matching issue).
    Standalone rows use slightly different phrasing — no 'PR#{N}' prefix
    because the whole row IS the PR.
    """
    author = pr.get("author", "")
    reviewer = pr.get("reviewer")
    reviewer_status = pr.get("reviewer_status") or ""
    open_days = pr.get("open_days", 0)

    if not reviewer:
        return "No reviewer assigned"
    elif reviewer_status.upper() == "CHANGES_REQUESTED":
        return f"Changes requested by {reviewer} — author must address ({open_days}d)"
    elif reviewer_status.upper() in ("", "COMMENTED", "PENDING"):
        return f"Waiting for review from {reviewer} ({open_days}d)"
    elif reviewer_status.upper() == "APPROVED":
        return "Approved — ready to merge"
    return ""


def build_action_text(
    issue: dict,
    triggers: list[tuple[int, str]],
    lpp_fix_keys: list[str] | None = None,
) -> str:
    """
    Assemble the full Section 1 Action cell text string.

    PR trigger texts (trigger 5) are placed first, followed by a double-newline
    separator, then the remaining action texts joined by ' · '.

    The '\n\n' separator is rendered as <br><br> in HTML and as a paragraph
    break in ADF, giving a visual blank line between PR status and issue status.

    Append ' · Fix: {LPD-KEY}' for each LPP fix link (LPP rows only).
    Append ' · Heat: {score}' if heat_score has a value (all LPP rows).

    Note: actual ADF inlineCard conversion of Jira keys and PR references
    happens in the ADF builder (Chunk 9) — this function returns plain text.
    """
    pr_parts: list[str] = [text for (n, text) in triggers if n == 5]
    other_parts: list[str] = [text for (n, text) in triggers if n != 5]

    # LPP fix links
    if lpp_fix_keys:
        for fix_key in lpp_fix_keys:
            if fix_key:
                other_parts.append(f"Fix: {fix_key}")

    # Heat score (LPP rows)
    if issue.get("project") == "LPP":
        heat = issue.get("heat_score", "")
        if heat:
            other_parts.append(f"Heat: {heat}")

    pr_str = " · ".join(pr_parts)
    other_str = " · ".join(other_parts)

    if pr_str and other_str:
        return f"{pr_str}\n\n{other_str}"
    return pr_str or other_str


def build_section2_action(issue: dict) -> str:
    """
    Build the Section 2 Action cell text string.

    Rules:
      LPD + assigned   : "Start"
      LPD + unassigned : "Assign & start"
      LPP In Queue     : "Assign & investigate"
      LPP (all)        : append ' · Heat: {score}' if heat_score exists
    """
    project = issue["project"]
    assignee_id = issue["assignee_id"]
    status = issue["status"]
    heat = issue.get("heat_score", "")

    base = ""

    if project == "LPD":
        has_real_assignee = bool(assignee_id) and assignee_id != PT_HEADLESS_ID
        base = "Start" if has_real_assignee else "Assign & start"

    elif project == "LPP":
        base = "Assign & investigate"

    elif project == "BPR":
        # BPR section 2 = Original Fix Committed; same logic as LPD
        has_real_assignee = bool(assignee_id) and assignee_id != PT_HEADLESS_ID
        base = "Start" if has_real_assignee else "Assign & start"

    else:
        base = "Start"

    # Append heat score for LPP rows
    if project == "LPP" and heat:
        base = f"{base} · Heat: {heat}"

    return base


# ════════════════════════════════════════════════════════════════════════════════
# CHUNK 9 — ADF builder
# Pure JSON structure — zero business logic.
# Takes fully classified report_data and builds a valid ADF document for Confluence.
#
# report_data shape expected by build_adf_document:
#   {
#     "section1":  [row, ...],   # sorted: standalone PR rows first, then issues by tier
#     "section2a": [row, ...],
#     "section2b": [row, ...],
#     "testing_panel": {
#       "date": "YYYY-MM-DD",
#       "investigation": {"count": int|None, "delta": int|None},
#       "acceptance":    {"count": int|None, "delta": int|None},
#       "all_bugs":      {"count": int|None, "delta": int|None},
#       "fp4_fp5":       {"count": int|None, "delta": int|None},
#       "no_fp":         {"count": int|None, "delta": int|None},
#     }
#   }
#
# Each row dict:
#   {
#     "type":        "issue" | "pr",   # "pr" = standalone PR row
#     "issue":       dict,             # parsed+classified issue (type="issue")
#     "pr":          dict,             # PR dict (type="pr")
#     "tier_key":    str,              # e.g. "7.3", "PR"
#     "section":     str,              # "1", "2a", or "2b"
#     "days_cell":   str,              # precomputed cell string from Chunk 7
#     "action_text": str,              # precomputed plain-text string from Chunk 8
#   }
# ════════════════════════════════════════════════════════════════════════════════


# ── ADF node helpers ──────────────────────────────────────────────────────────
# All return plain dicts.  No state, no side effects except adf_status (uuid4).

def adf_text(text: str, bold: bool = False) -> dict:
    """Plain text node, optionally bold."""
    node: dict = {"type": "text", "text": text}
    if bold:
        node["marks"] = [{"type": "strong"}]
    return node


def adf_strong(text: str) -> dict:
    """Shorthand for bold text node."""
    return adf_text(text, bold=True)


def adf_mention(account_id: str, display_name: str) -> dict:
    """
    Mention node.  display_name should include the @ prefix.
    accessLevel must be "APPLICATION" — that is what Confluence requires.
    """
    return {
        "type": "mention",
        "attrs": {
            "id": account_id,
            "text": display_name if display_name.startswith("@") else f"@{display_name}",
            "accessLevel": "APPLICATION",
        },
    }


def adf_inline_card(url: str) -> dict:
    """
    inlineCard node.  NEVER use plain text for issue or PR links.
    Callers must wrap this in adf_paragraph (or use the cell builders which
    handle the wrapping automatically).
    """
    return {"type": "inlineCard", "attrs": {"url": url}}


def adf_status(text: str, color: str) -> dict:
    """
    Status macro node.  Generates a fresh uuid4 for localId on every call —
    NEVER reuse a localId.  color must be one of:
    "red" | "yellow" | "purple" | "blue" | "neutral"
    """
    return {
        "type": "status",
        "attrs": {
            "text": text,
            "color": color,
            "localId": str(uuid.uuid4()),
            "style": "bold",
        },
    }


def adf_paragraph(*nodes) -> dict:
    """
    Paragraph block node.  Accepts any number of inline nodes as positional args.
    Filters out None values so callers can conditionally include nodes.
    """
    content = [n for n in nodes if n is not None]
    return {"type": "paragraph", "content": content}


def adf_heading(text: str, level: int) -> dict:
    """Heading block node (level 1–6)."""
    return {
        "type": "heading",
        "attrs": {"level": level},
        "content": [adf_text(text)],
    }


def adf_rule() -> dict:
    """Horizontal rule (thematic break)."""
    return {"type": "rule"}


def adf_bullet_list(*items) -> dict:
    """
    Bullet list node.  Each item is a list (or single node) of inline nodes
    that will be wrapped in a paragraph inside a listItem.
    Example: adf_bullet_list([adf_text("Hello"), adf_text(" world")])
    """
    list_items = []
    for item_nodes in items:
        if not isinstance(item_nodes, (list, tuple)):
            item_nodes = [item_nodes]
        list_items.append({
            "type": "listItem",
            "content": [adf_paragraph(*item_nodes)],
        })
    return {"type": "bulletList", "content": list_items}


def adf_table(*rows, full_width: bool = True) -> dict:
    """
    Table block node.
    ALWAYS outputs "layout": "full-width" — the full_width parameter exists only
    for documentation purposes; passing False is silently ignored because the
    Confluence page breaks if layout is anything other than "full-width".
    isNumberColumnEnabled is always False.
    """
    # full_width parameter is deliberately ignored — always full-width.
    return {
        "type": "table",
        "attrs": {
            "isNumberColumnEnabled": False,
            "layout": "full-width",
        },
        "content": list(rows),
    }


def adf_table_row(*cells) -> dict:
    """Table row node."""
    return {"type": "tableRow", "content": list(cells)}


def adf_table_cell(*nodes, header: bool = False) -> dict:
    """
    Table cell node.  header=True produces a tableHeader instead of tableCell.
    Each positional arg should be a block node (paragraph, bulletList, etc.).
    Raw inline nodes (text, mention, inlineCard, status) are automatically
    wrapped in a paragraph.
    """
    cell_type = "tableHeader" if header else "tableCell"
    content = []
    for node in nodes:
        if node is None:
            continue
        # Wrap raw inline nodes in a paragraph
        if node.get("type") in ("text", "mention", "inlineCard", "status", "hardBreak"):
            content.append(adf_paragraph(node))
        else:
            content.append(node)
    # A cell must never be empty — add an empty paragraph if needed
    if not content:
        content = [adf_paragraph(adf_text(""))]
    return {"type": cell_type, "attrs": {}, "content": content}


# ── Cell builders ─────────────────────────────────────────────────────────────

def build_priority_cell(tier_key: str) -> dict:
    """
    Builds the Priority table cell.
    Looks up TIER_COLORS[tier_key] → (category, sub_name, color).
    Produces: tableCell containing paragraph([text("{category} | "), status(sub_name, color)])
    Falls back gracefully if tier_key is unknown.
    """
    entry = TIER_COLORS.get(tier_key)
    if entry is None:
        print(f"  [build_priority_cell] WARNING: unknown tier_key {tier_key!r}")
        return adf_table_cell(adf_paragraph(adf_text(f"? | {tier_key}")))

    category, sub_name, color = entry
    para = adf_paragraph(
        adf_text(f"{category} | "),
        adf_status(sub_name, color),
    )
    return adf_table_cell(para)


def build_topic_cell(issue: dict, tier_key: str) -> dict:
    """
    Builds the Topic table cell.
    Planned LPD tiers (2, 12, 13): show parent.summary as plain text.
    All other tiers: empty cell.
    """
    _planned_tiers = {"2", "12", "13"}
    if tier_key in _planned_tiers:
        parent_summary = issue.get("parent_summary", "") or ""
        return adf_table_cell(adf_paragraph(adf_text(parent_summary)))
    return adf_table_cell(adf_paragraph(adf_text("")))


def build_issue_cell(issue_key: str) -> dict:
    """
    Builds the Issue table cell.  ALWAYS an inlineCard — never plain text.
    """
    url = f"{JIRA_BASE}/browse/{issue_key}"
    return adf_table_cell(adf_paragraph(adf_inline_card(url)))


def build_pr_cell(pr_number: int) -> dict:
    """
    Builds the Issue/PR table cell for a standalone PR row.
    inlineCard with GitHub PR URL.
    """
    url = f"https://github.com/{GITHUB_ORG}/{GITHUB_REPO}/pull/{pr_number}"
    return adf_table_cell(adf_paragraph(adf_inline_card(url)))


def build_assignee_cell(assignee_name: str, assignee_id: str, account_ids: dict) -> dict:
    """
    Builds the Assignee table cell.
    Uses mention node if account_id is known.
    Falls back to plain text and logs a warning if account_id is empty or unknown.
    """
    if assignee_id:
        display = assignee_name if assignee_name else assignee_id
        return adf_table_cell(adf_paragraph(adf_mention(assignee_id, display)))

    # No account_id directly — try reverse lookup from display name
    if assignee_name and assignee_name in account_ids:
        aid = account_ids[assignee_name]
        return adf_table_cell(adf_paragraph(adf_mention(aid, assignee_name)))

    if assignee_name:
        print(f"  [build_assignee_cell] WARNING: no account ID for {assignee_name!r} — using plain text")
        return adf_table_cell(adf_paragraph(adf_text(assignee_name)))

    # Truly unassigned
    return adf_table_cell(adf_paragraph(adf_text("—")))


def build_days_cell(days_text: str) -> dict:
    """Builds the Days in Progress / Days in Queue table cell from a precomputed string."""
    return adf_table_cell(adf_paragraph(adf_text(days_text or "")))


def build_action_cell(action_text: str) -> dict:
    """
    Builds the Action table cell.
    Parses the plain-text action string (from Chunk 8) and converts inline:
      - PR#N references        → inlineCard with GitHub PR URL
      - LPD/LPP/BPR/PTR-NNNN  → inlineCard with Jira browse URL
    All other text remains as adf_text nodes.

    '\n\n' (inserted by build_action_text between PR lines and issue lines)
    is rendered as a blank paragraph break so the cell has visual separation.
    """
    if not action_text:
        return adf_table_cell(adf_paragraph(adf_text("")))

    _TOKEN_RE = re.compile(r"(PR#\d+)|((LPD|LPP|BPR|PTR)-\d+)")

    def _segment_to_inline_nodes(segment: str) -> list[dict]:
        """Convert one text segment to ADF inline nodes."""
        inline_nodes: list[dict] = []
        last_end = 0
        for m in _TOKEN_RE.finditer(segment):
            start, end = m.start(), m.end()
            before = segment[last_end:start]
            if before:
                inline_nodes.append(adf_text(before))
            if m.group(1):
                pr_num = int(m.group(1)[3:])
                url = f"https://github.com/{GITHUB_ORG}/{GITHUB_REPO}/pull/{pr_num}"
                inline_nodes.append(adf_inline_card(url))
            else:
                jira_key = m.group(2)
                url = f"{JIRA_BASE}/browse/{jira_key}"
                inline_nodes.append(adf_inline_card(url))
            last_end = end
        tail = segment[last_end:]
        if tail:
            inline_nodes.append(adf_text(tail))
        return inline_nodes or [adf_text("")]

    segments = action_text.split("\n\n")
    paragraphs: list[dict] = []
    for seg in segments:
        paragraphs.append(adf_paragraph(*_segment_to_inline_nodes(seg)))

    return adf_table_cell(*paragraphs)


# ── Table row and section builders ────────────────────────────────────────────

def _build_header_row(days_label: str) -> dict:
    """
    Build the header row for a section table.
    days_label: "Days in Progress / T-shirt Size" (Section 1)
                or "Days in Queue" (Section 2).
    """
    headers = ["Priority", "Topic", "Issue", "Assignee", days_label, "Action"]
    cells = [adf_table_cell(adf_paragraph(adf_strong(h)), header=True) for h in headers]
    return adf_table_row(*cells)


def _build_data_row(row: dict, account_ids: dict) -> dict:
    """
    Build one data row for a section table from a row dict.
    Handles type="issue" and type="pr" (standalone PR) rows.
    """
    tier_key = row.get("tier_key", "13")
    days_cell_text = row.get("days_cell", "")
    action_text = row.get("action_text", "")

    if row.get("type") == "pr":
        # Standalone PR row
        pr = row["pr"]
        pr_number = pr.get("pr_number", 0)
        author = pr.get("author", "")

        priority_cell = build_priority_cell("PR")
        topic_cell    = adf_table_cell(adf_paragraph(adf_text("")))
        issue_cell    = build_pr_cell(pr_number)
        assignee_cell = adf_table_cell(adf_paragraph(adf_text(author or "—")))
        days_cell     = build_days_cell(days_cell_text)
        action_cell   = build_action_cell(action_text)
    else:
        # Regular issue row
        issue = row["issue"]
        issue_key    = issue["key"]
        assignee_name = issue.get("assignee", "")
        assignee_id   = issue.get("assignee_id", "")

        priority_cell = build_priority_cell(tier_key)
        topic_cell    = build_topic_cell(issue, tier_key)
        issue_cell    = build_issue_cell(issue_key)
        assignee_cell = build_assignee_cell(assignee_name, assignee_id, account_ids)
        days_cell     = build_days_cell(days_cell_text)
        action_cell   = build_action_cell(action_text)

    return adf_table_row(
        priority_cell,
        topic_cell,
        issue_cell,
        assignee_cell,
        days_cell,
        action_cell,
    )


def _build_section_table(rows: list[dict], days_label: str, account_ids: dict) -> dict:
    """
    Build a full ADF table for a section (header row + data rows).
    Returns the table node (always full-width).
    """
    table_rows = [_build_header_row(days_label)]
    for row in rows:
        table_rows.append(_build_data_row(row, account_ids))
    return adf_table(*table_rows)


# ── Testing panel ─────────────────────────────────────────────────────────────

# Canonical filter order — never change the order or URLs.
# investigation and acceptance link to Testray (Failed count from the two latest builds).
# all_bugs, fp4_fp5, no_fp link to Jira filters.
_TESTING_FILTERS = [
    ("investigation", "Investigation", "https://testray.liferay.com/web/testray#/project/35392/routines/994140"),
    ("acceptance",    "Acceptance",    "https://testray.liferay.com/web/testray#/project/35392/routines/994140"),
    ("all_bugs",      "All bugs",      "https://liferay.atlassian.net/issues/?filter=15065"),
    ("fp4_fp5",       "FP4/FP5",       "https://liferay.atlassian.net/issues/?filter=45383"),
    ("no_fp",         "No FP",         "https://liferay.atlassian.net/issues/?filter=45384"),
]


def _format_delta(delta: int | None) -> str:
    """
    Format a delta integer as "(+2)", "(−3)", or "(=)".
    Uses − (Unicode minus sign U+2212), not hyphen-minus.
    Returns "(–)" if delta is None (baseline unknown / N/A).
    """
    if delta is None:
        return "(–)"
    if delta == 0:
        return "(=)"
    if delta > 0:
        return f"(+{delta})"
    return f"(−{abs(delta)})"   # U+2212 = −


def _build_testing_panel_bullet(
    label: str,
    filter_url: str,
    count: int | None,
    delta: int | None,
) -> list:
    """
    Build the inline node list for one testing panel bullet item.
    Format: "{label}: {N} ({delta}) [inlineCard]"
    If count is None → "{label}: N/A (–) [inlineCard]"
    """
    if count is None:
        count_str = "N/A"
        delta_str = "(–)"   # en-dash for N/A indicator
    else:
        count_str = str(count)
        delta_str = _format_delta(delta)

    return [
        adf_text(f"{label}: {count_str} {delta_str} "),
        adf_inline_card(filter_url),
    ]


def _build_testing_section(testing_panel: dict) -> list[dict]:
    """
    Build the testing section block nodes:
      h2: 🧪 Test
      bold paragraph: "Testing Panel (YYYY-MM-DD):"
      bullet list (5 items, one per filter)

    Returns a list of block nodes ready to extend the document content list.
    """
    today_str = testing_panel.get("date", str(date.today()))

    nodes: list[dict] = [
        adf_heading("\U0001f9ea Test", level=2),
        adf_paragraph(adf_strong(f"Testing Panel ({today_str}):")),
    ]

    bullet_items = []
    for field_key, label, filter_url in _TESTING_FILTERS:
        entry = (testing_panel.get(field_key) or {})
        count = entry.get("count")   # int or None
        delta = entry.get("delta")   # int or None
        bullet_items.append(_build_testing_panel_bullet(label, filter_url, count, delta))

    nodes.append(adf_bullet_list(*bullet_items))
    return nodes


# ── Main ADF document assembler ───────────────────────────────────────────────

def build_adf_document(report_data: dict, ctx: "SprintContext") -> dict:
    """
    Assemble the complete ADF document from fully classified report_data.

    Document structure:
      sprint info paragraph
      rule
      h2: 🔴 In Progress — Needs Attention
      Section 1 table (or "No active issues." paragraph)
      rule
      h2: 📋 Pick Up Next
      h3: 2a. Assigned
      Section 2a table (or "No assigned items." paragraph)
      h3: 2b. Needs Owner
      Section 2b table (or "No unassigned items." paragraph)
      rule
      🧪 Test section (h2 + bold paragraph + bullet list)
    """
    account_ids = ctx.account_ids

    section1  = report_data.get("section1",  [])
    section2a = report_data.get("section2a", [])
    section2b = report_data.get("section2b", [])
    testing_panel = report_data.get("testing_panel", {})

    today_str = str(date.today())
    sprint_info = (
        f"{ctx.sprint_label}  ·  "
        f"{ctx.days_remaining}d remaining  ·  "
        f"{today_str}"
    )

    content: list[dict] = []

    # ── Sprint header ─────────────────────────────────────────────────────────
    content.append(adf_paragraph(adf_text(sprint_info)))
    content.append(adf_rule())

    # ── Section 1: In Progress ────────────────────────────────────────────────
    content.append(adf_heading("\U0001f534 In Progress — Needs Attention", level=2))
    if section1:
        content.append(_build_section_table(
            section1,
            "Days in Progress / T-shirt Size",
            account_ids,
        ))
    else:
        content.append(adf_paragraph(adf_text("No active issues.")))

    content.append(adf_rule())

    # ── Section 2: Pick Up Next ───────────────────────────────────────────────
    content.append(adf_heading("\U0001f4cb Pick Up Next", level=2))

    content.append(adf_heading("2a. Assigned", level=3))
    if section2a:
        content.append(_build_section_table(section2a, "Days in Queue", account_ids))
    else:
        content.append(adf_paragraph(adf_text("No assigned items.")))

    content.append(adf_heading("2b. Needs Owner", level=3))
    if section2b:
        content.append(_build_section_table(section2b, "Days in Queue", account_ids))
    else:
        content.append(adf_paragraph(adf_text("No unassigned items.")))

    content.append(adf_rule())

    # ── Testing section ───────────────────────────────────────────────────────
    content.extend(_build_testing_section(testing_panel))

    return {
        "version": 1,
        "type": "doc",
        "content": content,
    }


# ── ADF validator ─────────────────────────────────────────────────────────────

def validate_adf(adf: dict) -> None:
    """
    Walk the ADF tree and assert structural correctness.
    Raises AssertionError on any violation.

    Checks:
      1. Every table node has attrs.layout == "full-width"
      2. Every data tableRow's 3rd cell (index 2, the Issue column) contains
         an inlineCard node.  Header rows (tableHeader cells) are exempt.
      3. No localId appears more than once across all status nodes.
    """
    seen_local_ids: set[str] = set()
    violations: list[str] = []

    def _walk(node: dict, path: str = "doc") -> None:
        if not isinstance(node, dict):
            return

        node_type = node.get("type", "")

        # Check 1: table layout
        if node_type == "table":
            layout = (node.get("attrs") or {}).get("layout")
            if layout != "full-width":
                violations.append(
                    f"Table at {path}: layout={layout!r} — must be 'full-width'"
                )

        # Check 2: issue cell must contain inlineCard (data rows only)
        if node_type == "tableRow":
            cells = node.get("content") or []
            # Data rows have tableCell; header rows have tableHeader — skip headers
            if cells and cells[0].get("type") == "tableCell":
                if len(cells) > 2:
                    issue_cell = cells[2]
                    if not _cell_contains_inline_card(issue_cell):
                        cell_text = _extract_text_from_cell(issue_cell)
                        violations.append(
                            f"tableRow at {path}: Issue cell (index 2) has no inlineCard "
                            f"— content: {cell_text!r}"
                        )

        # Check 3: unique localIds
        if node_type == "status":
            local_id = (node.get("attrs") or {}).get("localId", "")
            if local_id:
                if local_id in seen_local_ids:
                    violations.append(
                        f"Duplicate localId {local_id!r} at {path}"
                    )
                seen_local_ids.add(local_id)

        # Recurse
        for i, child in enumerate(node.get("content") or []):
            _walk(child, path=f"{path}/{node_type}[{i}]")

    _walk(adf)

    if violations:
        msg = "\n  ".join(violations)
        raise AssertionError(
            f"ADF validation failed ({len(violations)} violation(s)):\n  {msg}"
        )

    print(f"  [validate_adf] ✓ ADF valid — {len(seen_local_ids)} status nodes, "
          f"no duplicate localIds, all tables full-width")


def _cell_contains_inline_card(cell: dict) -> bool:
    """Return True if the cell or any descendant node is an inlineCard."""
    if not isinstance(cell, dict):
        return False
    if cell.get("type") == "inlineCard":
        return True
    for child in cell.get("content") or []:
        if _cell_contains_inline_card(child):
            return True
    return False


def _extract_text_from_cell(cell: dict) -> str:
    """Extract a short plain-text representation from a cell (for error messages)."""
    texts: list[str] = []

    def _collect(node: dict) -> None:
        if isinstance(node, dict):
            if node.get("type") == "text":
                texts.append(node.get("text", ""))
            for child in node.get("content") or []:
                _collect(child)

    _collect(cell)
    return " ".join(texts)[:80]




# ════════════════════════════════════════════════════════════════════════════════
# CHUNK 10 — HTML preview generator
# generate_html_preview: writes a fully self-contained HTML review file.
# Reads from the same report_data dict used by build_adf_document.
# ════════════════════════════════════════════════════════════════════════════════

# Row background colours per tier (CSS colour strings)
_HTML_TIER_COLORS: dict[str, str] = {
    "PR":  "#fff8e1",   # light amber
    "1.1": "#ffcdd2",   # red-100
    "1.2": "#ffcdd2",
    "2":   "#e8d5f5",   # purple-100
    "3":   "#fff3cd",   # yellow-100
    "4":   "#fff3cd",
    "5":   "#fff3cd",
    "6":   "#fff3cd",
    "7.1": "#fff3cd",
    "7.2": "#fff3cd",
    "7.3": "#fff3cd",
    "7.4": "#fff3cd",
    "7.5": "#fff3cd",
    "8":   "#fff3cd",
    "9":   "#dbeafe",   # blue-100
    "12":  "#dbeafe",
    "13":  "#f5f5f5",   # grey-100
}


def _html_esc(s: str) -> str:
    """Minimal HTML escaping for plain text values."""
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


def _jira_link(key: str) -> str:
    """Return an HTML anchor tag for a Jira issue key."""
    if not key:
        return ""
    url = f"{JIRA_BASE}/browse/{key}"
    return f'<a href="{url}" target="_blank">{_html_esc(key)}</a>'


def _gh_pr_link(pr_number: int, label: str | None = None) -> str:
    """Return an HTML anchor tag for a GitHub PR."""
    url = f"https://github.com/{GITHUB_ORG}/{GITHUB_REPO}/pull/{pr_number}"
    display = label if label else f"PR#{pr_number}"
    return f'<a href="{url}" target="_blank">{_html_esc(display)}</a>'


def _html_action_text(action_text: str) -> str:
    """
    Convert plain action text to HTML, linkifying PR#N and Jira key references.
    '\n\n' (PR/issue separator from build_action_text) renders as <br><br>.
    Escapes everything else so injection is impossible.
    """
    if not action_text:
        return ""

    def _linkify_segment(segment: str) -> str:
        """Linkify one segment (no \n\n inside)."""
        _TOKEN_RE = re.compile(r"(PR#(\d+))|((LPD|LPP|BPR|PTR)-\d+)")
        parts: list[str] = []
        last_end = 0
        for m in _TOKEN_RE.finditer(segment):
            start, end = m.start(), m.end()
            before = segment[last_end:start]
            if before:
                parts.append(_html_esc(before))
            if m.group(1):
                pr_num = int(m.group(2))
                parts.append(_gh_pr_link(pr_num))
            else:
                jira_key = m.group(3)
                parts.append(_jira_link(jira_key))
            last_end = end
        tail = segment[last_end:]
        if tail:
            parts.append(_html_esc(tail))
        return "".join(parts)

    segments = action_text.split("\n\n")
    return "<br><br>".join(_linkify_segment(s) for s in segments)


def _html_section_table(rows: list[dict], days_header: str, ctx: "SprintContext") -> str:
    """
    Build an HTML <table> for a report section.
    Handles both type='issue' and type='pr' rows.
    """
    if not rows:
        return "<p><em>No items.</em></p>"

    cols = ["Priority", "Topic", "Issue", "Assignee", days_header, "Action"]
    th_cells = "".join(f"<th>{_html_esc(c)}</th>" for c in cols)
    html = f"<table><thead><tr>{th_cells}</tr></thead><tbody>\n"

    for row in rows:
        tier_key = row.get("tier_key", "13")
        bg = _HTML_TIER_COLORS.get(tier_key, "#ffffff")
        days_text = row.get("days_cell", "")
        action_text = row.get("action_text", "")

        # Priority cell
        entry = TIER_COLORS.get(tier_key)
        if entry:
            category, sub_name, _ = entry
            priority_html = f"{_html_esc(category)} | <strong>{_html_esc(sub_name)}</strong>"
        else:
            priority_html = _html_esc(tier_key)

        if row.get("type") == "pr":
            pr = row["pr"]
            pr_num = pr.get("pr_number", 0)
            author = pr.get("author", "")
            topic_html = ""
            issue_html = _gh_pr_link(pr_num)
            assignee_html = _html_esc(author)
        else:
            issue = row["issue"]
            key = issue.get("key", "")
            parent_summary = issue.get("parent_summary", "")
            _planned = {"2", "12", "13"}
            topic_html = _html_esc(parent_summary) if tier_key in _planned else ""
            issue_html = _jira_link(key)
            assignee_html = _html_esc(issue.get("assignee", "") or "—")

        action_html = _html_action_text(action_text)

        html += (
            f'<tr style="background:{bg}">'
            f"<td>{priority_html}</td>"
            f"<td>{topic_html}</td>"
            f"<td>{issue_html}</td>"
            f"<td>{assignee_html}</td>"
            f"<td>{_html_esc(days_text)}</td>"
            f"<td>{action_html}</td>"
            f"</tr>\n"
        )

    html += "</tbody></table>"
    return html


def _html_testing_panel(testing_panel: dict) -> str:
    """Build the HTML Testing Panel section."""
    if not testing_panel:
        return "<p><em>No testing panel data.</em></p>"

    today_str = testing_panel.get("date", str(date.today()))
    html = f"<p><strong>Testing Panel ({_html_esc(today_str)}):</strong></p><ul>\n"

    for field_key, label, filter_url in _TESTING_FILTERS:
        entry = testing_panel.get(field_key) or {}
        count = entry.get("count")
        delta = entry.get("delta")

        count_str = "N/A" if count is None else str(count)
        delta_str = _format_delta(delta)
        html += (
            f'<li>{_html_esc(label)}: <strong>{count_str}</strong> {_html_esc(delta_str)} '
            f'— <a href="{filter_url}" target="_blank">open filter</a></li>\n'
        )

    html += "</ul>"
    return html


def _html_exclusions(excluded: list[tuple[str, str]]) -> str:
    """Build the collapsible Exclusions section."""
    if not excluded:
        return "<details><summary>Exclusions (0)</summary><p>None.</p></details>"

    rows = ""
    for key, reason in excluded:
        rows += (
            f"<tr><td>{_jira_link(key)}</td><td>{_html_esc(reason)}</td></tr>\n"
        )

    return (
        f"<details><summary>Exclusions ({len(excluded)})</summary>"
        f"<table><thead><tr><th>Key</th><th>Reason</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></details>"
    )


def _html_cache_preview(report_data: dict, ctx: "SprintContext") -> str:
    """
    Show what will be written to project_current_sprint.md after publish.
    """
    lines: list[str] = []

    cache_preview = report_data.get("cache_preview", {})
    new_cl = cache_preview.get("changelog_updates", {})
    if new_cl:
        lines.append("<h4>Changelog cache updates</h4><ul>")
        for k, v in sorted(new_cl.items()):
            lines.append(f"<li>{_jira_link(k)} → {_html_esc(str(v))}</li>")
        lines.append("</ul>")
    else:
        lines.append("<p><em>No changelog cache changes.</em></p>")

    new_snap = cache_preview.get("state_snapshot_keys", [])
    lines.append(f"<p>State snapshot will cover <strong>{len(new_snap)}</strong> issues.</p>")

    new_prs = cache_preview.get("pr_snapshot_keys", [])
    lines.append(f"<p>PR snapshot will cover <strong>{len(new_prs)}</strong> open PRs.</p>")

    return "\n".join(lines)


def generate_html_preview(
    report_data: dict,
    ctx: "SprintContext",
    output_path: "Path",
) -> None:
    """
    Write a fully self-contained HTML preview of the daily actions report.

    Mirrors exactly what build_adf_document will publish to Confluence,
    plus extra debugging sections (exclusions, cache preview).

    Saved to output_path (caller passes OUTPUT_DIR / f"daily_actions_report_{today}.html").
    """
    today_str = str(date.today())
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    section1      = report_data.get("section1",  [])
    section2a     = report_data.get("section2a", [])
    section2b     = report_data.get("section2b", [])
    testing_panel = report_data.get("testing_panel", {})
    excluded      = report_data.get("excluded", [])

    # INCOMPLETE banner — shown when all testing panel values are N/A
    tp = testing_panel or {}
    testing_na = all(
        (tp.get(fk) or {}).get("count") is None
        for fk, _, _ in _TESTING_FILTERS
    )
    incomplete_banner = ""
    if testing_na:
        incomplete_banner = (
            '<div class="incomplete-banner">'
            "&#9888; INCOMPLETE — Testing panel values are all N/A. "
            "Fetch them via Chrome before publishing."
            "</div>"
        )

    s1_html    = _html_section_table(section1,  "Days in Progress / T-shirt Size", ctx)
    s2a_html   = _html_section_table(section2a, "Days in Queue", ctx)
    s2b_html   = _html_section_table(section2b, "Days in Queue", ctx)
    tp_html    = _html_testing_panel(testing_panel)
    excl_html  = _html_exclusions(excluded)
    cache_html = _html_cache_preview(report_data, ctx)

    sprint_info = (
        f"{_html_esc(ctx.sprint_label)}  ·  "
        f"{ctx.days_remaining}d remaining  ·  "
        f"{today_str}"
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Daily Actions Report — {_html_esc(today_str)}</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 13px;
    margin: 0;
    padding: 16px 24px;
    color: #1a1a1a;
    background: #fff;
  }}
  .sprint-bar {{
    background: #1e3a5f;
    color: #fff;
    padding: 10px 16px;
    border-radius: 6px;
    margin-bottom: 16px;
    font-size: 14px;
    font-weight: 600;
  }}
  .incomplete-banner {{
    background: #fff3cd;
    border: 2px solid #f59e0b;
    color: #92400e;
    padding: 10px 16px;
    border-radius: 6px;
    margin-bottom: 16px;
    font-weight: 600;
  }}
  .timestamp {{
    color: #666;
    font-size: 11px;
    margin-bottom: 20px;
  }}
  h2 {{ margin: 24px 0 8px; font-size: 15px; border-bottom: 2px solid #e5e7eb; padding-bottom: 4px; }}
  h3 {{ margin: 16px 0 6px; font-size: 13px; color: #374151; }}
  h4 {{ margin: 12px 0 4px; font-size: 12px; color: #6b7280; }}
  table {{
    border-collapse: collapse;
    width: 100%;
    margin-bottom: 16px;
    font-size: 12px;
  }}
  th {{
    background: #f3f4f6;
    border: 1px solid #d1d5db;
    padding: 5px 8px;
    text-align: left;
    font-weight: 600;
    white-space: nowrap;
  }}
  td {{
    border: 1px solid #e5e7eb;
    padding: 4px 8px;
    vertical-align: top;
    line-height: 1.4;
  }}
  a {{ color: #2563eb; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  details {{ margin-bottom: 16px; }}
  summary {{
    cursor: pointer;
    font-weight: 600;
    padding: 6px 10px;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 4px;
    user-select: none;
  }}
  details[open] summary {{ border-bottom-left-radius: 0; border-bottom-right-radius: 0; }}
  details > table, details > p, details > ul, details > div {{
    margin: 0;
    padding: 8px 10px;
    border: 1px solid #e5e7eb;
    border-top: none;
    border-radius: 0 0 4px 4px;
  }}
  ul {{ margin: 6px 0; padding-left: 20px; }}
  li {{ margin: 3px 0; }}
  hr {{ border: none; border-top: 1px solid #e5e7eb; margin: 20px 0; }}
  .section-count {{ color: #6b7280; font-weight: normal; font-size: 12px; }}
  .cache-section {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px 16px; margin-bottom: 16px; }}
</style>
</head>
<body>

<div class="sprint-bar">{sprint_info}</div>
{incomplete_banner}
<div class="timestamp">Generated: {_html_esc(fetched_at)}</div>

<h2>&#128308; In Progress &#8212; Needs Attention <span class="section-count">({len(section1)} items)</span></h2>
{s1_html}

<hr>

<h2>&#128203; Pick Up Next</h2>
<h3>2a. Assigned <span class="section-count">({len(section2a)} items)</span></h3>
{s2a_html}

<h3>2b. Needs Owner <span class="section-count">({len(section2b)} items)</span></h3>
{s2b_html}

<hr>

<h2>&#129514; Tests</h2>
{tp_html}

<hr>

{excl_html}

<details>
<summary>Cache preview (what will be written after publish)</summary>
<div class="cache-section">{cache_html}</div>
</details>

</body>
</html>
"""

    output_path.write_text(html, encoding="utf-8")
    print(f"  [generate_html_preview] Saved → {output_path}")


# ════════════════════════════════════════════════════════════════════════════════
# CHUNK 11 — Publish + cache update
# publish_report: PUTs ADF to Confluence (or dry-runs it)
# update_caches: called ONLY after HTTP 200 — updates all sprint context sections
# ════════════════════════════════════════════════════════════════════════════════

def publish_report(adf: dict, ctx: "SprintContext", dry_run: bool = False) -> dict:
    """
    Publish the ADF document to the actions report Confluence page.

    dry_run=True: skip the PUT entirely, just print what would be sent.
    Returns the Confluence API response dict (or a synthetic dict for dry-run).
    Raises RuntimeError on non-200 response.
    """
    page_id = ctx.actions_report_page_id
    title   = ctx.confluence_page_title

    if dry_run:
        adf_preview = json.dumps(adf)[:500]
        print(
            f"\n[publish_report] DRY RUN — would PUT to page {page_id}\n"
            f"  title: {title}\n"
            f"  ADF preview (first 500 chars): {adf_preview}..."
        )
        return {"dry_run": True, "page_id": page_id, "title": title}

    print(f"\n[publish_report] Publishing to Confluence page {page_id} ...")

    # Save ADF to disk before attempting the network call.
    # If the PUT fails (e.g. ProxyError), the fallback javascript_tool publish
    # reads this file directly — no chunking required.
    adf_output_path = OUTPUT_DIR / "adf_output.json"
    adf_output_path.write_text(json.dumps(adf, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [publish_report] ADF saved → {adf_output_path}")

    current_version = jira_get_confluence_version(page_id)
    new_version = current_version + 1

    result = jira_put_confluence(page_id, title, adf, new_version)
    print(f"  [publish_report] ✓ Published: version {new_version} → {page_id}")
    return result


def update_caches(
    report_data: dict,
    ctx: "SprintContext",
    sprint_context_path: "Path",
) -> None:
    """
    Update all cache sections in ctx and write them back to project_current_sprint.md.

    MUST only be called after a successful (HTTP 200) publish.
    Never called in dry_run mode.

    Updates:
      - changelog_cache  : merge in new/changed entries from this run
      - state_snapshot   : replace issues dict with current statuses/assignees
      - pr_snapshot      : replace prs dict with only open PRs seen this run
      - testing_baseline : update counts where count is not None / "N/A"
      - account_ids      : merge any newly resolved account IDs
    """
    today_str = str(date.today())

    # ── 1. Changelog cache ────────────────────────────────────────────────────
    # ctx.changelog_cache was already written to during the run (by
    # get_first_active_date and _get_bpr_ofc_date). Just confirm the count.
    cl_count = len(ctx.changelog_cache)
    print(f"  [update_caches] changelog_cache: {cl_count} entries")

    # ── 2. State snapshot ─────────────────────────────────────────────────────
    # Collect all in-scope issues from section1, section2a, section2b.
    new_issues: dict[str, dict] = {}
    for section_key in ("section1", "section2a", "section2b"):
        for row in report_data.get(section_key, []):
            if row.get("type") == "pr":
                continue
            issue = row.get("issue", {})
            key = issue.get("key")
            if key:
                new_issues[key] = {
                    "status":   issue.get("status", ""),
                    "assignee": issue.get("assignee", ""),
                }

    ctx.state_snapshot = {
        "date":   today_str,
        "issues": new_issues,
    }
    print(f"  [update_caches] state_snapshot: {len(new_issues)} issues, date={today_str}")

    # ── 3. PR snapshot ────────────────────────────────────────────────────────
    # Record only currently open PRs (standalone + attached).
    new_prs: dict[str, str] = {}

    # Standalone PR rows
    for row in report_data.get("section1", []):
        if row.get("type") == "pr":
            pr = row.get("pr", {})
            pr_num = str(pr.get("pr_number", ""))
            if pr_num:
                new_prs[pr_num] = "open"

    # Attached PRs on issue rows
    for section_key in ("section1", "section2a", "section2b"):
        for row in report_data.get(section_key, []):
            if row.get("type") == "issue":
                for pr in row.get("issue", {}).get("attached_prs", []):
                    pr_num = str(pr.get("pr_number", ""))
                    if pr_num:
                        new_prs[pr_num] = "open"

    ctx.pr_snapshot = {
        "date": today_str,
        "prs":  new_prs,
    }
    print(f"  [update_caches] pr_snapshot: {len(new_prs)} open PRs, date={today_str}")

    # ── 4. Testing baseline ───────────────────────────────────────────────────
    # Only update fields where count is an int (not None and not "N/A").
    tp = report_data.get("testing_panel") or {}
    updated_fields: list[str] = []

    baseline = dict(ctx.testing_baseline)  # copy before mutating
    baseline["date"] = today_str

    for field_key, _, _ in _TESTING_FILTERS:
        entry = tp.get(field_key) or {}
        count = entry.get("count")
        if count is not None and count != "N/A":
            baseline[field_key] = {"count": count}
            updated_fields.append(field_key)

    ctx.testing_baseline = baseline
    if updated_fields:
        print(f"  [update_caches] testing_baseline updated: {updated_fields}")
    else:
        print(f"  [update_caches] testing_baseline: no new counts (all N/A) — baseline unchanged")

    # ── 5. Account IDs ────────────────────────────────────────────────────────
    # Merge any new name→id mappings gathered during the run.
    new_account_ids = report_data.get("account_ids_seen", {})
    if new_account_ids:
        merged = 0
        for name, aid in new_account_ids.items():
            if name not in ctx.account_ids:
                ctx.account_ids[name] = aid
                merged += 1
        if merged:
            print(f"  [update_caches] account_ids: merged {merged} new entries")

    # ── 6. Persist ────────────────────────────────────────────────────────────
    save_sprint_context(ctx, sprint_context_path)
    print(f"  [update_caches] ✓ All caches saved to {sprint_context_path.name}")


# ════════════════════════════════════════════════════════════════════════════════
# CHUNK 12 — Main orchestrator + CLI
# Wires all chunks together into a runnable pipeline.
# _TODAY / _today(): module-level date that respects --date override.
# ════════════════════════════════════════════════════════════════════════════════

# Module-level "today" — set once in main() to respect --date override.
# All code should call _today() rather than date.today() when the report date matters.
_TODAY: date | None = None


def _today() -> date:
    """Return the effective report date (--date override or real today)."""
    return _TODAY if _TODAY is not None else date.today()


def _build_testing_panel_data(
    ctx: "SprintContext",
    skip: bool,
    counts_file: "Path | None" = None,
) -> dict:
    """
    Build the testing_panel sub-dict for report_data.

    If skip=True (--no-testing-panel), all counts are None (HTML shows N/A).

    If counts_file is provided (--testing-panel-file), load counts from that JSON.
    Expected format:
      {"investigation": 42, "acceptance": 15, "all_bugs": 103, "fp4_fp5": 7, "no_fp": 96}
    Key names must match the _TESTING_FILTERS field keys.

    *** HOW TO GENERATE THE COUNTS FILE ***

    investigation and acceptance — from Testray (read via Chrome MCP):
      Routine: https://testray.liferay.com/web/testray#/project/35392/routines/994140

      1. Navigate to the routine page and find the two latest builds:
         - "Whole run" = latest [master] ci:test:headless build
         - "Acceptance" = latest EE Development Acceptance (master) build
           filtered by Headless team (testrayTeamIds=[45740])

      2. For each build, read the "Total test cases" chart and take the FAILED count.
         - investigation = Failed count from the whole run build
         - acceptance    = Failed count from the Acceptance build (Headless team filter)

    all_bugs, fp4_fp5, no_fp — from Jira via browser JavaScript fetch from a
    liferay.atlassian.net Chrome tab (uses the user's authenticated session):

      (async () => {
        const filters = [
          [15065, "all_bugs"], [45383, "fp4_fp5"], [45384, "no_fp"]
        ];
        const counts = {};
        for (const [id, key] of filters) {
          let total = 0, cursor = undefined, isLast = false, pages = 0;
          while (!isLast && pages < 50) {
            const body = {jql: `filter=${id}`, maxResults: 5000, fields: ["key"]};
            if (cursor) body.nextPageToken = cursor;
            const resp = await fetch("/rest/api/3/search/jql", {
              method: "POST", headers: {"Content-Type": "application/json"},
              body: JSON.stringify(body)
            });
            const data = await resp.json();
            total += (data.issues || []).length;
            isLast = data.isLast ?? true;
            cursor = data.nextPageToken;
            pages++;
          }
          counts[key] = total;
        }
        return JSON.stringify(counts);
      })()

    Combine Testray and Jira counts into testing_panel.json:
      {"investigation": 101, "acceptance": 18, "all_bugs": 186, "fp4_fp5": 2, "no_fp": 12}

    Pass with --testing-panel-file testing_panel.json.

    NOTE: NEVER use Atlassian MCP searchJiraIssuesUsingJql for all_bugs/fp4_fp5/no_fp —
    it uses service credentials and returns wrong totals.

    Computes deltas from ctx.testing_baseline where available.
    """
    today_str = str(_today())

    if skip:
        return {
            "date": today_str,
            **{fk: {"count": None, "delta": None} for fk, _, _ in _TESTING_FILTERS},
        }

    live_counts: dict[str, int | None] = {}
    if counts_file and counts_file.exists():
        try:
            raw = json.loads(counts_file.read_text(encoding="utf-8"))
            for fk, _, _ in _TESTING_FILTERS:
                v = raw.get(fk)
                live_counts[fk] = int(v) if v is not None else None
            print(f"  [testing_panel] Loaded counts from {counts_file.name}: {live_counts}")
        except Exception as exc:
            print(f"  [testing_panel] !! Failed to load counts file: {exc}")

    result: dict = {"date": today_str}
    baseline = ctx.testing_baseline or {}
    for fk, _, _ in _TESTING_FILTERS:
        count = live_counts.get(fk)
        if count is not None:
            prev = baseline.get(fk)
            delta = (count - prev) if isinstance(prev, int) else None
        else:
            delta = None
        result[fk] = {"count": count, "delta": delta}

    return result


def _sort_section1(rows: list[dict]) -> list[dict]:
    """
    Sort Section 1 rows:
      1. Standalone PR rows first (tier_key == "PR")
      2. Then issues by tier_num ascending
      3. Secondary: for planned tiers (12, 13) by days ascending; others by days descending
    """
    def _sort_key(row: dict) -> tuple:
        is_pr = 1 if row.get("type") == "pr" else 2
        tier_num = row.get("_tier_num", 99.0)
        tier_key = row.get("tier_key", "13")
        days_cell = row.get("days_cell", "")

        # Extract numeric days from cell string for secondary sort
        days_match = re.search(r"^(\d+)d", days_cell)
        days = int(days_match.group(1)) if days_match else 0

        planned = tier_key in ("12", "13")
        # planned: ascending days (oldest first for catch-up); unplanned: descending
        days_sort = days if planned else -days

        return (is_pr, tier_num, days_sort)

    return sorted(rows, key=_sort_key)


def _sort_section2(rows: list[dict]) -> list[dict]:
    """
    Sort Section 2 rows by tier ascending, secondary by heat_score descending (LPP)
    or days ascending (others).
    """
    def _sort_key(row: dict) -> tuple:
        tier_num = row.get("_tier_num", 99.0)
        issue = row.get("issue", {})
        project = issue.get("project", "")
        days_cell = row.get("days_cell", "")

        days_match = re.search(r"^(\d+)d", days_cell)
        days = int(days_match.group(1)) if days_match else 0

        # LPP: sort by heat score descending; others by days ascending
        heat_str = issue.get("heat_score", "") or ""
        try:
            heat = float(heat_str)
        except ValueError:
            heat = 0.0

        heat_sort = -heat if project == "LPP" else days

        return (tier_num, heat_sort)

    return sorted(rows, key=_sort_key)


def main() -> None:
    """Full pipeline: fetch → classify → route → HTML preview → optional publish."""

    # ── 1. Parse CLI args ─────────────────────────────────────────────────────
    parser = argparse.ArgumentParser(
        description="Headless Daily Actions Report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--publish",          action="store_true",
                        help="Publish to Confluence (default: HTML preview only)")
    parser.add_argument("--dry-run",          action="store_true",
                        help="Build + validate ADF but skip publish and cache update")
    parser.add_argument("--date",             default=None, metavar="YYYY-MM-DD",
                        help="Override today's date (for testing)")
    parser.add_argument("--no-github",        action="store_true",
                        help="Skip GitHub PR fetch (use empty PR list)")
    parser.add_argument("--jira-data-file",   default=None, metavar="PATH",
                        help="Path to JSON file with Jira data fetched by Claude via Jira MCP")
    parser.add_argument("--pr-data-file",     default=None, metavar="PATH",
                        help="Path to JSON file with PR data fetched by Claude via Chrome MCP")
    parser.add_argument("--no-testing-panel", action="store_true",
                        help="Skip testing panel fetch (show N/A for all counts)")
    parser.add_argument("--testing-panel-file", default=None, metavar="PATH",
                        help=(
                            "Path to JSON file with testing panel counts. "
                            "MUST be generated via browser JS fetch (see _build_testing_panel_data docstring). "
                            "NEVER use the Atlassian MCP searchJiraIssuesUsingJql tool — it returns wrong totals "
                            "because it uses different credentials than the user's Jira session. "
                            'Expected format: {"investigation": N, "acceptance": N, "all_bugs": N, "fp4_fp5": N, "no_fp": N}'
                        ))
    parser.add_argument("--test-exclusions",  action="store_true",
                        help="Run exclusion rule unit tests and exit")
    args = parser.parse_args()

    # ── Set global report date ────────────────────────────────────────────────
    global _TODAY
    if args.date:
        try:
            _TODAY = date.fromisoformat(args.date)
        except ValueError:
            print(f"ERROR: Invalid --date value {args.date!r}. Use YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)
    else:
        _TODAY = date.today()

    today_str = str(_TODAY)

    if args.test_exclusions:
        run_exclusion_tests()
        sys.exit(0)

    print(f"\n{'='*60}")
    print(f"Headless Daily Actions Report — {today_str}")
    if args.dry_run:
        print("MODE: dry-run (ADF will be built + validated, not published)")
    elif args.publish:
        print("MODE: publish (HTML + Confluence publish)")
    else:
        print("MODE: preview only (HTML only, no Confluence publish)")
    print(f"{'='*60}\n")

    # ── 2. Load sprint context ────────────────────────────────────────────────
    print("[Step 1] Loading sprint context ...")
    ctx = load_sprint_context(SPRINT_CONTEXT_FILE)
    print(f"  Sprint: {ctx.sprint_label}  |  {ctx.days_remaining}d remaining")
    print(f"  Page ID: {ctx.actions_report_page_id}")

    # ── 3. Load Jira data from file ───────────────────────────────────────────
    print("\n[Step 2] Loading data from files ...")
    fetch_errors: list[str] = []

    jira_file = Path(args.jira_data_file) if args.jira_data_file else None
    raw_sprint_issues, sev_keys, sev_zero_day_keys, sev_bpr_keys, changelogs = load_jira_data(jira_file)

    # Inject pre-fetched changelogs into ctx so get_first_active_date can use them
    # without making direct HTTPS calls (which fail via the proxy in the sandbox).
    ctx.changelogs = changelogs

    # Load PR data
    if args.no_github:
        print("  [fetch_open_prs] --no-github: skipping")
        open_prs: list[dict] = []
    else:
        pr_file = Path(args.pr_data_file) if args.pr_data_file else None
        open_prs = fetch_open_prs(ctx, pr_data_file=pr_file)

    # ── Supplement: fetch full data for SEV BPRs not in sprint filter ────────
    # filter=15069 only gives us the set of SEV BPR keys; their full issue
    # data may not be in filter=54796 (sprint filter). Fetch any that are missing
    # so they appear in the report (Tier 5 classification requires full issue data).
    sprint_keys_set = {r.get("key", "") for r in raw_sprint_issues}
    missing_sev_bpr_keys = sev_bpr_keys - sprint_keys_set
    if missing_sev_bpr_keys:
        print(f"\n  Fetching {len(missing_sev_bpr_keys)} SEV BPR issue(s) not in sprint filter ...")
        for bpr_key in sorted(missing_sev_bpr_keys):
            try:
                raw_bpr = jira_get_issue(bpr_key, fields=[
                    "key", "summary", "status", "assignee", "labels", "issuetype",
                    "priority", "project", "updated", "created", "duedate", "comment",
                    "customfield_10804", "customfield_10168", "parent",
                    "customfield_10001", "customfield_10020", "issuelinks",
                ])
                raw_sprint_issues.append(raw_bpr)
                print(f"    + {bpr_key} added from SEV BPR set")
            except Exception as exc:
                print(f"    !! Failed to fetch {bpr_key}: {exc}")
                fetch_errors.append(f"SEV BPR fetch failed: {bpr_key}: {exc}")

    print(f"\n  Sprint issues: {len(raw_sprint_issues)}")
    print(f"  SEV keys: {len(sev_keys)}  zero-day: {len(sev_zero_day_keys)}")
    print(f"  SEV BPR keys: {len(sev_bpr_keys)}")
    print(f"  Open PRs: {len(open_prs)}")

    # ── 4. Parse all issues ───────────────────────────────────────────────────
    print("\n[Step 3] Parsing issues ...")
    parsed_issues = [parse_issue(r) for r in raw_sprint_issues]
    print(f"  Parsed {len(parsed_issues)} issues")

    # ── 5. Apply exclusions ───────────────────────────────────────────────────
    print("\n[Step 4] Applying exclusions ...")
    kept: list[dict] = []
    excluded: list[tuple[str, str]] = []  # (key, reason)

    for issue in parsed_issues:
        reason = should_exclude(issue, sev_keys, ctx)
        if reason:
            excluded.append((issue["key"], reason))
        else:
            kept.append(issue)

    print(f"  Kept: {len(kept)}  Excluded: {len(excluded)}")

    # ── 6+7. Classify tiers + LPP visibility ─────────────────────────────────
    print("\n[Step 5] Classifying tiers ...")
    for issue in kept:
        tier_num, tier_key = classify_tier(issue, sev_keys, sev_zero_day_keys, sev_bpr_keys)
        issue["_tier_num"] = tier_num
        issue["_tier_key"] = tier_key

        # LPP Solution Proposed visibility
        if issue["project"] == "LPP" and issue["status"] == "solution proposed":
            issue["_lpp_visible"] = lpp_should_show(issue, ctx)
        else:
            issue["_lpp_visible"] = True  # non-SP issues always show if in scope

        # Mark SEV issues for compute_days_queue_cell
        issue["_is_sev"] = issue["key"] in sev_keys

    # ── 8. Fetch first_active_dates for Section 1 candidates ─────────────────
    print("\n[Step 6] Fetching first_active_dates (changelog cache) ...")
    section1_candidates = [
        i for i in kept
        if route_issue(i, i["_tier_num"], i["_lpp_visible"]) == "1"
    ]
    print(f"  Section 1 candidates: {len(section1_candidates)}")

    changelog_updates: dict[str, str] = {}
    for issue in section1_candidates:
        key = issue["key"]
        old_val = ctx.changelog_cache.get(key)
        fad = get_first_active_date(issue, ctx)
        new_val = ctx.changelog_cache.get(key)
        if new_val != old_val:
            changelog_updates[key] = new_val or ""
        issue["_first_active_date"] = fad

    print(f"  Changelog cache: {len(changelog_updates)} new/updated entries")

    # ── 9. Route to sections ──────────────────────────────────────────────────
    print("\n[Step 7] Routing issues to sections ...")
    issues_dict: dict[str, dict] = {}
    section2_issues: list[dict] = []

    for issue in kept:
        section = route_issue(issue, issue["_tier_num"], issue["_lpp_visible"])
        issue["_section"] = section
        if section in ("1", "2a", "2b"):
            issues_dict[issue["key"]] = issue
        if section in ("2a", "2b"):
            section2_issues.append(issue)

    # ── 10. Merge PRs to issues ───────────────────────────────────────────────
    print("\n[Step 8] Merging PRs to issues ...")
    issues_with_prs, standalone_prs = merge_prs_to_issues(issues_dict, open_prs, ctx)

    # ── LPD suppression: skip LPD sprint issues whose PR(s) already route to LPP ──
    # When a PR has lpp_fix_key set it gets attached to the LPP row (merge priority 2).
    # The LPD sprint issue the PR originally linked to would otherwise appear as an
    # independent row, duplicating the context already visible under the LPP row.
    # Build the set of LPD keys to suppress, then mark them so the row builder skips them.
    _lpp_claimed_lpd_keys: set[str] = set()
    for pr in open_prs:
        if pr.get("lpp_fix_key"):
            # Collect the LPD key this PR was linked to (parent_key or jira_key)
            for candidate in (pr.get("parent_key"), pr.get("jira_key")):
                if candidate and candidate.startswith("LPD-") and candidate in issues_dict:
                    _lpp_claimed_lpd_keys.add(candidate)
                    print(f"  [lpp_suppression] {candidate} suppressed — PR#{pr['pr_number']} routes to {pr['lpp_fix_key']}")

    for key in _lpp_claimed_lpd_keys:
        issues_dict[key]["_suppressed_by_lpp"] = True

    # ── 11. Build days cells + action text ───────────────────────────────────
    print("\n[Step 9] Building days cells and action text ...")

    # Collect all in-scope account IDs seen during this run (for cache merge)
    account_ids_seen: dict[str, str] = {}

    section1_rows: list[dict] = []
    section2a_rows: list[dict] = []
    section2b_rows: list[dict] = []

    # Standalone PR rows go to Section 1
    for pr in standalone_prs:
        row = {
            "type":        "pr",
            "pr":          pr,
            "tier_key":    "PR",
            "_tier_num":   0.0,
            "section":     "1",
            "days_cell":   compute_pr_days_active_cell(pr.get("open_days", 0)),
            "action_text": _evaluate_standalone_pr_trigger(pr),
        }
        section1_rows.append(row)

    # Issue rows
    for issue in issues_with_prs:
        section = issue.get("_section")
        if section not in ("1", "2a", "2b"):
            continue

        # Skip LPD issues suppressed because their PR already routes to an LPP row
        if issue.get("_suppressed_by_lpp"):
            print(f"  [lpp_suppression] {issue['key']}: skipping row — merged under LPP")
            excluded.append((issue["key"], "Suppressed — PR routes to LPP row"))
            continue

        tier_key  = issue["_tier_key"]
        tier_num  = issue["_tier_num"]

        # Collect account ID for cache
        aname = issue.get("assignee", "")
        aid   = issue.get("assignee_id", "")
        if aname and aid:
            account_ids_seen[aname] = aid

        if section == "1":
            fad = issue.get("_first_active_date")
            days_cell = compute_days_active_cell(issue, fad)

            # Compute numeric days_active for Trigger 7
            days_active = 0
            if fad and fad != _NO_TRANSITION:
                try:
                    days_active = max(0, (_today() - date.fromisoformat(fad)).days)
                except ValueError:
                    pass

            triggers = evaluate_triggers(issue, ctx, days_active=days_active)

            # ── Trigger gate (skill §13): only show in Section 1 if ≥1 trigger fires ──
            # Issues with no actionable trigger are silently skipped.
            # Attached PRs count as triggers independently (Trigger 5) — if a PR
            # triggered but the issue itself has no other trigger, it still shows.
            # PTR issues always show in Section 1 regardless of triggers — they are
            # medium-priority unplanned work that always needs visibility.
            _gate_exempt = issue.get("project") == "PTR"
            if not triggers and not issue.get("attached_prs") and not _gate_exempt:
                print(f"  [section1_gate] {issue['key']}: no triggers — skipping from Section 1")
                continue
            if _gate_exempt and not triggers and not issue.get("attached_prs"):
                print(f"  [section1_gate] {issue['key']}: PTR — showing despite no triggers")

            # Gather LPD fix keys for LPP rows: look at issue's own issuelinks
            # to find LPD issues that are fixing this LPP. This is what appears
            # as "Fix: LPD-XXXXX" in the Action column.
            # Do NOT use pr.lpp_fix_key here — that field is the LPP key as seen
            # from an LPD PR, and using it would duplicate the LPP key itself.
            lpp_fix_keys: list[str] = []
            if issue.get("project") == "LPP":
                for link in issue.get("issuelinks") or []:
                    # "is fixed by" / "fixes" / "is caused by" / "relates to"
                    link_type = (link.get("type") or {}).get("name", "").lower()
                    inward = (link.get("inwardIssue") or {}).get("key", "")
                    outward = (link.get("outwardIssue") or {}).get("key", "")
                    for linked_key in (inward, outward):
                        if linked_key and linked_key.startswith("LPD-"):
                            lpp_fix_keys.append(linked_key)

            action_text = build_action_text(issue, triggers, lpp_fix_keys=lpp_fix_keys)
            # PTR with no triggers: show a default "Review progress" prompt
            if not action_text and issue.get("project") == "PTR":
                action_text = "Review progress"

            row = {
                "type":        "issue",
                "issue":       issue,
                "tier_key":    tier_key,
                "_tier_num":   tier_num,
                "section":     "1",
                "days_cell":   days_cell,
                "action_text": action_text,
            }
            section1_rows.append(row)

        else:
            days_cell   = compute_days_queue_cell(issue, ctx, section=section)
            action_text = build_section2_action(issue)

            row = {
                "type":        "issue",
                "issue":       issue,
                "tier_key":    tier_key,
                "_tier_num":   tier_num,
                "section":     section,
                "days_cell":   days_cell,
                "action_text": action_text,
            }
            if section == "2a":
                section2a_rows.append(row)
            else:
                section2b_rows.append(row)

    # ── 12. Sort ──────────────────────────────────────────────────────────────
    print("\n[Step 10] Sorting sections ...")
    section1_rows  = _sort_section1(section1_rows)
    section2a_rows = _sort_section2(section2a_rows)
    section2b_rows = _sort_section2(section2b_rows)

    print(f"  Section 1: {len(section1_rows)} rows")
    print(f"  Section 2a: {len(section2a_rows)} rows")
    print(f"  Section 2b: {len(section2b_rows)} rows")

    # ── 13. Build report_data ─────────────────────────────────────────────────
    tp_file = Path(args.testing_panel_file) if args.testing_panel_file else None
    testing_panel_data = _build_testing_panel_data(ctx, skip=args.no_testing_panel, counts_file=tp_file)

    report_data: dict = {
        "section1":          section1_rows,
        "section2a":         section2a_rows,
        "section2b":         section2b_rows,
        "testing_panel":     testing_panel_data,
        "excluded":          excluded,
        "account_ids_seen":  account_ids_seen,
        "cache_preview": {
            "changelog_updates":   changelog_updates,
            "state_snapshot_keys": list(issues_dict.keys()),
            "pr_snapshot_keys":    [str(pr["pr_number"]) for pr in open_prs],
        },
    }

    # ── 14. Generate HTML preview ─────────────────────────────────────────────
    print("\n[Step 11] Generating HTML preview ...")
    html_path = OUTPUT_DIR / f"daily_actions_report_{today_str}.html"
    generate_html_preview(report_data, ctx, html_path)
    print(f"  HTML saved: {html_path}")

    # ── 15. Terminal summary ──────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"SUMMARY — {today_str}")
    print(f"  Section 1 (In Progress):  {len(section1_rows)} rows")
    print(f"  Section 2a (Assigned):    {len(section2a_rows)} rows")
    print(f"  Section 2b (Needs Owner): {len(section2b_rows)} rows")
    print(f"  Excluded:                 {len(excluded)}")
    print(f"  Open PRs (total):         {len(open_prs)}")
    print(f"  Standalone PRs:           {len(standalone_prs)}")
    if fetch_errors:
        print(f"  !! Fetch errors:          {len(fetch_errors)}")
    print(f"{'─'*60}")

    # ── 16. Publish or dry-run ────────────────────────────────────────────────
    if args.publish or args.dry_run:
        print("\n[Step 12] Building ADF document ...")
        adf = build_adf_document(report_data, ctx)

        print("[Step 13] Validating ADF ...")
        validate_adf(adf)

        if args.dry_run:
            publish_report(adf, ctx, dry_run=True)
            print("\n[dry-run complete] Caches NOT updated.")
        else:
            print("[Step 14] Publishing to Confluence ...")
            result = publish_report(adf, ctx, dry_run=False)
            print("[Step 15] Updating caches ...")
            update_caches(report_data, ctx, SPRINT_CONTEXT_FILE)
            print("\n✓ Publish complete.")
    else:
        print("\n(No --publish flag — Confluence publish skipped. Use --publish to publish.)")

    print(f"\nHTML report: file://{html_path.resolve()}")


if __name__ == "__main__":
    main()
