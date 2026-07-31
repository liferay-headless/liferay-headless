#!/usr/bin/env python3
"""
assemble_slack_data.py — turn Chrome-scraped Slack text into slack_data.json
for headless_daily_report.py's "Needs Owner" Slack rows.

WHY THIS SCRIPT EXISTS
Claude drives the browser (Chrome MCP) because there is no Slack connector
available in this org. Everything that can be a judgment call has been moved
OUT of prose instructions and INTO this script: window filtering, date
parsing, reply-author matching against the team roster, sorting, dismiss
persistence. Claude's job is reduced to two mechanical scrapes — nothing
here should require Claude to reason about which threads count as answered.

WORKFLOW (see SKILL.md for the exact tool calls)
  1. scan      Claude scrapes the channel's message list (get_page_text, no
               thread opened) and saves it verbatim to a text file. This
               script parses it into candidate [Title] threads inside the
               lookback window and writes candidates.json.

  2. (Claude)  For every candidate in candidates.json with reply_count > 0,
               Claude opens that thread and appends one record to a JSON
               array file (permalink + raw get_page_text of the open thread
               panel). Candidates with reply_count == 0 still need a
               permalink (found via the `find` tool) but never need the
               thread opened — there are no replies to check.

  3. classify  This script joins those detail records back onto the scan
               candidates by title, classifies each as answered/unanswered
               by checking reply authors against the roster stored in
               project_current_sprint.md's "Team Slack Names" section,
               applies any "dismissed" overrides from the existing "Slack
               Thread Snapshot" section, sorts unanswered threads oldest
               first, and writes slack_data.json — the exact shape
               headless_daily_report.py's --slack-data-file expects.
               It also rewrites the Slack Thread Snapshot section in place.

  4. dismiss   Ad hoc: mark one thread as handled outside Slack so it stops
               reappearing even though nobody ever replied in-thread. Clears
               automatically the next time that thread's reply count changes
               (a bump reopens the question).

Usage:
  python3 assemble_slack_data.py scan --channel-text channel.txt \
      --window-days 7 --out candidates.json

  python3 assemble_slack_data.py classify --candidates candidates.json \
      --details thread_details.json --sprint-context project_current_sprint.md \
      --out slack_data.json

  python3 assemble_slack_data.py dismiss --title-contains "some phrase" \
      --sprint-context project_current_sprint.md

Exit codes: 0 = OK, 1 = validation/data-quality failure, 2 = usage/IO error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────

# Bumped in lockstep with headless_daily_report.py and assemble_jira_data.py.
# See CHANGELOG.md for what changed at each version.
SKILL_VERSION = "2.1.1"


MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10, "November": 11,
    "December": 12,
}

# A date-separator line, e.g. "Monday, June 29th" (no year — Slack omits it
# for the current year).
_DATE_SEP_RE = re.compile(
    r"^\w+day,\s+(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2})(?:st|nd|rd|th)$"
)
# A per-message time line, e.g. "4:29 PM" (12-hour, no seconds).
_TIME_LINE_RE = re.compile(r"^(\d{1,2}):(\d{2})\s?(AM|PM)$", re.IGNORECASE)
# Bracketed thread title, on its own line.
_TITLE_LINE_RE = re.compile(r"^\[(.+)\]\s*(?:\(edited\))?$")
# "N replies" / "1 reply"
_REPLY_COUNT_RE = re.compile(r"^(\d+)\s+repl(?:y|ies)$")
# A reply-thread author header, e.g. "Alejandro Tardín" followed by a line
# like "Yesterday at 3:43 PM" / "Today at 3:43 PM" / "Tuesday at 3:43 PM".
_THREAD_AUTHOR_TIME_RE = re.compile(
    r"^(?:Today|Yesterday|\w+day)\s+at\s+\d{1,2}:\d{2}\s?(AM|PM)$", re.IGNORECASE
)
# A plausible "person name" line — used to keep the author-block scan honest
# (avoids matching stray short lines as names). Liferay names include
# accented Latin characters and multi-part surnames.
_NAME_LINE_RE = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ.'\-]*(?:\s+[A-Za-zÀ-ÖØ-öø-ÿ.'\-]+)+$")


def fail(msg: str) -> None:
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(1)


def usage_fail(msg: str) -> None:
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(2)


# ── Sprint-context md helpers (deliberately duplicated from
#    headless_daily_report.py rather than imported — this script must stay
#    runnable standalone, same as assemble_jira_data.py). ────────────────────

def _read_md_json_section(text: str, section_name: str) -> dict | list | None:
    m = re.search(
        r"^## " + re.escape(section_name) + r"\n+```json\n(.*?)```",
        text,
        re.DOTALL | re.MULTILINE,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1).strip())
    except json.JSONDecodeError as e:
        fail(f"JSON parse error in '## {section_name}' of the sprint context file: {e}")


def _write_md_json_section(path: Path, section_name: str, data: dict | list) -> None:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(^## " + re.escape(section_name) + r"\n+```json\n)(.*?)(```)",
        re.DOTALL | re.MULTILINE,
    )
    replacement_json = json.dumps(data, ensure_ascii=False, indent=2)

    def _replacer(m):
        return m.group(1) + replacement_json + "\n" + m.group(3)

    new_text, count = pattern.subn(_replacer, text)
    if count == 0:
        new_text = text.rstrip("\n") + (
            f"\n\n## {section_name}\n```json\n{replacement_json}\n```\n"
        )
    path.write_text(new_text, encoding="utf-8")


def load_roster(sprint_context_path: Path) -> dict[str, str]:
    """Return {display_name: slack_name} from '## Team Slack Names'. Empty
    dict (with a warning) if the section is missing — every reply would then
    be treated as non-team, which is the safer failure direction (over-
    flagging, not silently hiding real unanswered questions)."""
    text = sprint_context_path.read_text(encoding="utf-8")
    raw = _read_md_json_section(text, "Team Slack Names")
    if raw is None:
        print("  ⚠ No '## Team Slack Names' section found — every reply will be "
              "treated as a non-team reply (threads may be over-flagged).",
              file=sys.stderr)
        return {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items() if v}
    fail("'## Team Slack Names' must be a JSON object of {display name: slack name}.")


def roster_slack_names_lower(roster: dict[str, str]) -> set[str]:
    return {v.strip().lower() for v in roster.values() if v.strip()}


def load_snapshot(sprint_context_path: Path) -> dict:
    text = sprint_context_path.read_text(encoding="utf-8")
    raw = _read_md_json_section(text, "Slack Thread Snapshot")
    if raw is None:
        return {"date": "", "threads": {}}
    if not isinstance(raw, dict):
        fail("'## Slack Thread Snapshot' must be a JSON object.")
    raw.setdefault("threads", {})
    return raw


def save_snapshot(sprint_context_path: Path, snapshot: dict) -> None:
    _write_md_json_section(sprint_context_path, "Slack Thread Snapshot", snapshot)


# ── Date helpers ───────────────────────────────────────────────────────────

def _resolve_separator_date(label: str, as_of: date) -> date | None:
    """Turn a date-separator label ('Today', 'Yesterday', 'Monday, June 29th')
    into an absolute date, assuming it refers to the same year as `as_of`
    unless that would put it in the future (year-boundary rollover)."""
    if label == "Today":
        return as_of
    if label == "Yesterday":
        return as_of - timedelta(days=1)
    m = _DATE_SEP_RE.match(label)
    if not m:
        return None
    month = MONTHS.get(m.group("month"))
    if not month:
        return None
    day = int(m.group("day"))
    try:
        candidate = date(as_of.year, month, day)
    except ValueError:
        return None
    if candidate > as_of:
        candidate = date(as_of.year - 1, month, day)
    return candidate


# ── Mode 1: scan ─────────────────────────────────────────────────────────────

def parse_channel_text(text: str, as_of: date) -> list[dict]:
    """
    Parse a get_page_text dump of the channel's message list (thread panel
    must NOT be open — scrape the plain channel view) into a list of
    candidate threads:
      {title, author, created_date (YYYY-MM-DD or None), reply_count}

    Only messages whose first content line is a bracketed [Title] are
    candidates — plain messages (GitHub/Jira bot relays, etc.) are ignored
    entirely, per the team's convention of asking questions with a
    bracketed subject line.
    """
    lines = [ln.rstrip() for ln in text.splitlines()]
    candidates: list[dict] = []
    current_date: date | None = None
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i].strip()

        # Date separator ("Today" / "Yesterday" / "Monday, June 29th")
        if line in ("Today", "Yesterday") or _DATE_SEP_RE.match(line):
            resolved = _resolve_separator_date(line, as_of)
            if resolved:
                current_date = resolved
            i += 1
            continue

        # Candidate pattern: Name line, then a bare time line, then (usually)
        # a blank line, then somewhere within the next few lines a
        # "[Title]" line. Scan forward with a bounded lookahead so stray
        # reaction badges/blank lines in between don't break the match.
        if _NAME_LINE_RE.match(line) and i + 1 < n and _TIME_LINE_RE.match(lines[i + 1].strip()):
            author = line
            title = None
            title_offset = None
            for look in range(2, min(8, n - i)):
                cand = lines[i + look].strip()
                if not cand:
                    continue
                tm = _TITLE_LINE_RE.match(cand)
                if tm:
                    title = tm.group(1).strip()
                    title_offset = look
                    break
                # Anything else non-blank before we find a title means this
                # message doesn't open with a bracketed title — bail out of
                # the lookahead (not a candidate).
                break

            if title is None:
                i += 1
                continue

            # Look forward (bounded) for the "N replies / Last reply .../
            # View thread" trio that ends this message's block. If it is
            # never found before the next Name+Time header (or a date
            # separator, or end of text), the message has zero replies.
            reply_count = 0
            j = i + title_offset + 1
            limit = min(n, j + 60)
            while j < limit:
                cand = lines[j].strip()
                rm = _REPLY_COUNT_RE.match(cand)
                if rm:
                    reply_count = int(rm.group(1))
                    break
                # Stop looking once we clearly hit the next message header
                # or a date separator — this message had 0 replies.
                if cand in ("Today", "Yesterday") or _DATE_SEP_RE.match(cand):
                    break
                if (_NAME_LINE_RE.match(cand) and j + 1 < n
                        and _TIME_LINE_RE.match(lines[j + 1].strip())):
                    break
                j += 1

            candidates.append({
                "title": title,
                "author": author,
                "created_date": current_date.isoformat() if current_date else None,
                "reply_count": reply_count,
            })
            i += 1
            continue

        i += 1

    return candidates


def run_scan(args: argparse.Namespace) -> None:
    as_of = date.fromisoformat(args.as_of_date) if args.as_of_date else date.today()
    path = Path(args.channel_text)
    if not path.exists():
        usage_fail(f"--channel-text file not found: {path}")
    text = path.read_text(encoding="utf-8")

    all_candidates = parse_channel_text(text, as_of)
    print(f"  Parsed {len(all_candidates)} bracketed-title message(s) from the channel dump")

    window_start = as_of - timedelta(days=args.window_days)
    in_window: list[dict] = []
    undated = 0
    for c in all_candidates:
        if c["created_date"] is None:
            undated += 1
            continue
        if date.fromisoformat(c["created_date"]) >= window_start:
            in_window.append(c)

    if undated:
        print(f"  ⚠ {undated} message(s) had no resolvable date separator and were "
              f"dropped — if this number looks high, check that --channel-text was "
              f"scraped from the top of the channel (date separators intact).",
              file=sys.stderr)

    print(f"  {len(in_window)} candidate thread(s) within the last {args.window_days} day(s) "
          f"(as of {as_of.isoformat()})")

    needs_detail = sum(1 for c in in_window if c["reply_count"] > 0)
    zero_reply = len(in_window) - needs_detail
    print(f"    {needs_detail} need their thread opened (reply_count > 0)")
    print(f"    {zero_reply} have zero replies (no team reply possible — unanswered by definition)")

    out_path = Path(args.out)
    out_path.write_text(json.dumps(in_window, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ candidates written: {out_path} ({len(in_window)} threads)")


# ── Mode 2: classify ─────────────────────────────────────────────────────────

def _extract_reply_authors(raw_thread_text: str) -> list[str]:
    """
    From a get_page_text dump of an OPEN thread panel, return the list of
    distinct authors who posted in the replies (excluding the original
    parent message, which is restated at the top of the panel before the
    "N replies" divider).
    """
    lines = [ln.rstrip() for ln in raw_thread_text.splitlines()]
    n = len(lines)

    # Find the "N replies" divider — everything before it is the parent
    # message (skip), everything after is actual replies.
    start = None
    for idx, ln in enumerate(lines):
        if _REPLY_COUNT_RE.match(ln.strip()):
            start = idx + 1
            break
    if start is None:
        return []

    # Stop at the reply composer ("Reply…") if present.
    end = n
    for idx in range(start, n):
        if lines[idx].strip() == "Reply…":
            end = idx
            break

    authors: list[str] = []
    seen: set[str] = set()
    i = start
    while i < end:
        line = lines[i].strip()
        if (_NAME_LINE_RE.match(line) and i + 1 < end
                and _THREAD_AUTHOR_TIME_RE.match(lines[i + 1].strip())):
            key = line.lower()
            if key not in seen:
                seen.add(key)
                authors.append(line)
            i += 2
            continue
        i += 1
    return authors


def run_classify(args: argparse.Namespace) -> None:
    as_of = date.fromisoformat(args.as_of_date) if args.as_of_date else date.today()

    candidates_path = Path(args.candidates)
    if not candidates_path.exists():
        usage_fail(f"--candidates file not found: {candidates_path}")
    candidates: list[dict] = json.loads(candidates_path.read_text(encoding="utf-8"))

    details_path = Path(args.details)
    if not details_path.exists():
        usage_fail(f"--details file not found: {details_path}")
    details_raw: list[dict] = json.loads(details_path.read_text(encoding="utf-8"))
    details_by_title = {d["title"]: d for d in details_raw}

    sprint_context_path = Path(args.sprint_context)
    if not sprint_context_path.exists():
        usage_fail(f"--sprint-context file not found: {sprint_context_path}")
    roster = load_roster(sprint_context_path)
    roster_names = roster_slack_names_lower(roster)
    if not roster_names:
        print("  ⚠ Team roster is empty — no reply will ever count as a team reply, "
              "so every thread with any replies at all will still show as unanswered. "
              "Fix '## Team Slack Names' in project_current_sprint.md.", file=sys.stderr)

    snapshot = load_snapshot(sprint_context_path)
    prev_threads: dict = snapshot.get("threads", {})

    # ── Reliability guard: every candidate that needed its thread opened
    # (reply_count > 0) MUST have a matching detail record. A missing one
    # means Claude skipped a thread during scraping — hard stop rather than
    # silently under-reporting Needs Owner.
    missing = [c["title"] for c in candidates
               if c["reply_count"] > 0 and c["title"] not in details_by_title]
    if missing:
        fail("Missing thread detail record(s) for candidate(s) with replies: "
             + "; ".join(missing[:5])
             + (f" (+{len(missing) - 5} more)" if len(missing) > 5 else "")
             + ". Every candidate with reply_count > 0 must be opened and appended "
               "to the details file before running classify.")

    results: list[dict] = []
    new_snapshot_threads: dict = {}

    for c in candidates:
        title = c["title"]
        detail = details_by_title.get(title)
        permalink = (detail or {}).get("permalink", "")
        if not permalink:
            print(f"  ⚠ No permalink recorded for {title!r} — row will be skipped "
                  f"(cannot produce a Slack link).", file=sys.stderr)
            continue

        thread_id = _thread_id_from_permalink(permalink) or title

        if c["reply_count"] == 0:
            reply_authors: list[str] = []
            answered = False
        else:
            raw_text = detail.get("raw_thread_text", "") or ""
            reply_authors = _extract_reply_authors(raw_text)
            answered = any(a.strip().lower() in roster_names for a in reply_authors)

        prev = prev_threads.get(thread_id, {})
        dismissed = bool(prev.get("dismissed")) and prev.get("reply_count_at_dismiss") == c["reply_count"]

        status = "answered" if answered else ("dismissed" if dismissed else "unanswered")

        created_date = c.get("created_date")
        age_days = (as_of - date.fromisoformat(created_date)).days if created_date else None

        new_snapshot_threads[thread_id] = {
            "title": title,
            "reply_count": c["reply_count"],
            "status": status,
            "dismissed": bool(prev.get("dismissed")) and dismissed,
            "reply_count_at_dismiss": prev.get("reply_count_at_dismiss") if dismissed else None,
            "last_checked": as_of.isoformat(),
        }

        if status == "unanswered":
            results.append({
                "permalink": permalink,
                "title": title,
                "author": c.get("author", ""),
                "created_date": created_date,
                "age_days": age_days if age_days is not None else 0,
                "reply_count": c["reply_count"],
            })

    results.sort(key=lambda r: -(r["age_days"] or 0))

    out_path = Path(args.out)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    snapshot["date"] = as_of.isoformat()
    snapshot["threads"] = new_snapshot_threads
    save_snapshot(sprint_context_path, snapshot)

    answered_n = sum(1 for t in new_snapshot_threads.values() if t["status"] == "answered")
    dismissed_n = sum(1 for t in new_snapshot_threads.values() if t["status"] == "dismissed")
    print(f"✅ slack_data.json written: {out_path}")
    print(f"   {len(results)} unanswered  |  {answered_n} answered  |  {dismissed_n} dismissed")
    print(f"   Snapshot updated in {sprint_context_path.name} ({len(new_snapshot_threads)} threads tracked)")


def _thread_id_from_permalink(permalink: str) -> str | None:
    m = re.search(r"/(p\d+)$", permalink.strip())
    return m.group(1) if m else None


# ── Mode 3: dismiss ──────────────────────────────────────────────────────────

def run_dismiss(args: argparse.Namespace) -> None:
    sprint_context_path = Path(args.sprint_context)
    if not sprint_context_path.exists():
        usage_fail(f"--sprint-context file not found: {sprint_context_path}")

    snapshot = load_snapshot(sprint_context_path)
    threads = snapshot.get("threads", {})

    matches = [
        (tid, t) for tid, t in threads.items()
        if args.title_contains.lower() in t.get("title", "").lower()
    ]
    if not matches:
        fail(f"No tracked thread title contains {args.title_contains!r}. "
             f"Run `classify` at least once first so the thread is in the snapshot.")
    if len(matches) > 1:
        fail("Multiple tracked threads match that text — be more specific:\n"
             + "\n".join(f"  - {t['title']}" for _, t in matches))

    thread_id, thread = matches[0]
    thread["dismissed"] = True
    thread["status"] = "dismissed"
    thread["reply_count_at_dismiss"] = thread.get("reply_count", 0)
    threads[thread_id] = thread
    snapshot["threads"] = threads
    save_snapshot(sprint_context_path, snapshot)
    print(f"✅ Dismissed: {thread['title']!r} — will stay hidden until its reply count "
          f"changes (currently {thread.get('reply_count', 0)}).")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)

    p_scan = sub.add_parser("scan", help="Parse a channel-text dump into candidate threads")
    p_scan.add_argument("--channel-text", required=True, help="Path to get_page_text dump of the channel")
    p_scan.add_argument("--window-days", type=int, default=7)
    p_scan.add_argument("--as-of-date", default=None, metavar="YYYY-MM-DD")
    p_scan.add_argument("--out", default="candidates.json")

    p_classify = sub.add_parser("classify", help="Classify candidates against the roster and write slack_data.json")
    p_classify.add_argument("--candidates", required=True)
    p_classify.add_argument("--details", required=True)
    p_classify.add_argument("--sprint-context", required=True)
    p_classify.add_argument("--as-of-date", default=None, metavar="YYYY-MM-DD")
    p_classify.add_argument("--out", default="slack_data.json")

    p_dismiss = sub.add_parser("dismiss", help="Mark one tracked thread as handled outside Slack")
    p_dismiss.add_argument("--title-contains", required=True)
    p_dismiss.add_argument("--sprint-context", required=True)

    args = ap.parse_args()
    print(f"assemble_slack_data.py -- skill v{SKILL_VERSION}", file=sys.stderr)

    if args.mode == "scan":
        run_scan(args)
    elif args.mode == "classify":
        run_classify(args)
    elif args.mode == "dismiss":
        run_dismiss(args)


if __name__ == "__main__":
    main()
