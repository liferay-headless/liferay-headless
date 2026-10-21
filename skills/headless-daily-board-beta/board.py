#!/usr/bin/env python3
"""
Headless Daily Board (BETA) — builds the tabbed board page.

board.py itself makes no network calls and never writes caches or the shared
Confluence context page. The only output is one self-contained HTML file.

Commands (all deterministic, so they can be "always allowed"):
  python3 board.py --find-inputs            locate today's stable preview + jira_data.json
  python3 board.py --plan                   print the exact Jira/Confluence calls for step 2
  python3 board.py --plan --epic-keys K1,K2 ...plus the per-epic count calls and slow-story query
  python3 board.py --build --work-dir DIR   build DIR/board_<date>.html (inputs auto-found; checks counts)
  python3 board.py --self-test              parser/unit checks

What the board shows
  Top: Iteration bar (filter done/total vs schedule) and Milestone bar weighted by epic T-shirt size
  (person-months, SIZE_PM below; share done = done/total stories; an epic with no stories = 0% done).
  Tabs: 1a Needs Attention (all unplanned + planned with a PR action) · 1b Not in Iteration (stable 1b) ·
  1c High Cycle Time (other planned with 🔴/🟠 or "check for blockers"; Story → Task → other → Spike, then
  cycle time desc) · 2a Pick Up Next · Needs Owner (stable Open PRs + 2a) · 2b Pick Up Next · Assigned
  (stable 2b) · 3 Milestone status · 4 Tests. Planned rows with no PR action and normal cycle time are
  listed in a folded box; exclusions folded below.
  Rows: Jira issue-type colours, topic links to the parent epic, cycle-time colours (stories red > 14d,
  orange > 7d; epics red > 65d, orange > 45d), PRs & review and Other updates in separate columns.
  Milestone status: Headless epics only, Size column, (1) committed = milestone Fix Version, (2) active but
  not committed (discovery excluded), each sorted by cycle time desc, with flags.
  AVD tiles (goals 15d / 65d / 24d / WIP 18) show "?" until an avd.json is supplied:
  {"story":{"value":57,"basis":"85th pct · 8 iterations","outliers":[{"key":"LPD-1","days":40}]},
   "epic":{...}, "handoff":{...}, "wip":{"value":13}}
"""
import argparse, html, json, re, sys
from datetime import date
from pathlib import Path

BOARD_VERSION = "0.17.4-beta"
HERE = Path(__file__).parent

# ── Configuration (edit here, not in SKILL.md) ─────────────────────────────
CLOUD_ID = "liferay.atlassian.net"
TEAM_CLAUSE = '"Team[Team]" = 81233281-c987-401d-8d68-85d8ad1ec2fc'
MILESTONE = {"name": "2026 M4 Delivery Milestone", "start": "2026-10-05", "end": "2027-01-01"}  # update each milestone
ITERATION_FILTER = 54796
TESTRAY_PAGE_ID = "5096669324"
TSHIRT_FIELD = "customfield_10804"
MAX_EPICS = 25            # token gate: stop and ask above this
SEARCH_ROOTS = ["/root/.claude/skills", "/mnt/user-data", "/tmp/claude-0", str(Path.home()), "."]

# Team roster for the Assign picker (edit here if the team changes). v0.16.0: this list now decides who is
# in the picker; Jira account IDs and GitHub logins are looked up in the context file. The context file's
# "Account IDs" roster is wider on purpose (it also drives ownership/exclusion rules), so it is not used as-is.
TEAM = ["Adolfo Pérez", "Alberto Moreno Lage", "Alejandro Tardín", "Antonio Jimeno Cordero", "Beni Herrero Lorenzo",
        "Carlos Correa García", "Daniel Raposo Sánchez", "Gábor Komáromi", "Jaime León Rosado", "Jorge González",
        "Jose Luis Navarro", "Magdalena Jedraszak", "Nóra Szél", "Petteri Karttunen", "Vendel Töreki",
        "PT User Headless"]
ITERATION_FILTER_URL = f"https://liferay.atlassian.net/issues/?filter={ITERATION_FILTER}"
# Epic T-shirt size → person-months (roadmap: "XL = 1 month/person"; others scaled from it — edit if needed)
SIZE_PM = {"XS": 0.1, "S": 0.15, "M": 0.25, "L": 0.5, "XL": 1, "2XL": 2, "3XL": 3, "4XL": 4, "5XL": 5}
MON = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}

# ── 1. Parse the stable preview ────────────────────────────────────────────
ROW_RE = re.compile(r'<tr(?: style="background:(#\w+)")?>(.*?)</tr>', re.S)
SEC_RE = re.compile(r'<h3>(.*?)<span class="section-count">.*?</h3>\s*<table>(.*?)</table>', re.S)


def _txt(s):
    return html.unescape(re.sub(r"<.*?>", "", s)).strip()


def parse_rows(table_html):
    rows = []
    for m in ROW_RE.finditer(table_html):
        tds = re.findall(r"<td>(.*?)</td>", m.group(2), re.S)
        if len(tds) < 6:
            continue  # header row
        pr = _txt(tds[0]).split("|", 1)
        link = re.search(r'href="([^"]+)"[^>]*>([^<]+)</a>', tds[2])
        rows.append({
            "kind": pr[0].strip(), "tier": (pr[1] if len(pr) > 1 else pr[0]).strip(),
            "topic": _txt(tds[1]), "url": link.group(1) if link else "",
            "key": html.unescape(link.group(2)) if link else _txt(tds[2]),
            "assignee": _txt(tds[3]), "days": _txt(tds[4]), "action": tds[5].strip(),
        })
    return rows


def parse_report(src):
    secs = {}
    for m in SEC_RE.finditer(src):
        secs[_txt(m.group(1))] = parse_rows(m.group(2))

    def pick(prefix):
        for name, rows in secs.items():
            if name.startswith(prefix):
                return rows
        return []

    bar = re.search(r'<div class="sprint-bar">(.*?)</div>', src, re.S)
    parts = [p.strip() for p in _txt(bar.group(1)).split("·")] if bar else []
    excl = [{"url": u, "key": html.unescape(k), "why": _txt(w)} for u, k, w in
            re.findall(r'<tr><td><a href="([^"]+)"[^>]*>([^<]+)</a></td><td>(.*?)</td></tr>', src, re.S)]
    return {
        "sprint_label": parts[0] if parts else "",
        "days_remaining": int(re.sub(r"\D", "", parts[1]) or 0) if len(parts) > 1 else 0,
        "date": parts[2] if len(parts) > 2 else str(date.today()),
        "s1a": pick("1a."), "s1b": pick("1b."),
        "s2pr": pick("Open PRs"), "s2a_needs_owner": pick("2a."), "s2b_assigned": pick("2b."),
        "excl": excl, "found_sections": list(secs.keys()),
    }


PR_RE = re.compile(r"github\.com/[^\"']+/pull/|PR#\d+")
TYPE_ORDER = {"story": 0, "task": 1}          # everything else = 2, spike = 3


def has_pr_action(row):
    """Planned row qualifies for 1a only when a PR needs something (reviewer, review, merge, changes)."""
    return bool(PR_RE.search(row["action"]))


def high_cycle_time(row):
    return "\U0001F534" in row["days"] or "\U0001F7E0" in row["days"] or "check for blockers" in row["action"]


def classify_1(rows):
    """1a = all unplanned + planned with PR action; 1c = remaining planned with high cycle time;
    hidden = remaining planned (no PR action, normal cycle time)."""
    s1a, s1c, hidden = [], [], []
    for r in rows:
        if r["kind"] != "Planned" or has_pr_action(r):
            s1a.append(r)
        elif high_cycle_time(r):
            s1c.append(r)
        else:
            hidden.append(r)
    return s1a, s1c, hidden


def sort_1c(rows):
    def rank(r):
        t = (r.get("type") or "").lower()
        tr = 3 if "spike" in t else TYPE_ORDER.get(t, 2)
        m = re.match(r"\s*(\d+)", r["days"])
        return (tr, -(int(m.group(1)) if m else 0))
    return sorted(rows, key=rank)


def iteration_dates(label, today):
    m = re.search(r"([A-Z][a-z]{2})(\d{1,2})-([A-Z][a-z]{2})(\d{1,2})\s*$", label)
    if not m:
        return None, None
    y = int(today[:4])
    s = date(y, MON[m.group(1)], int(m.group(2)))
    e = date(y, MON[m.group(3)], int(m.group(4)))
    if e < s:  # Dec → Jan
        e = date(y + 1, e.month, e.day)
    if s > date.fromisoformat(today):
        s, e = date(y - 1, s.month, s.day), date(y - 1 if e.year == y else y, e.month, e.day)
    return str(s), str(e)


# ── 2. Enrichment ──────────────────────────────────────────────────────────
def summaries_from_jira_data(path):
    out = {}
    if not path or not Path(path).exists():
        return out

    def walk(o):
        if isinstance(o, dict):
            if "key" in o and isinstance(o.get("fields"), dict):
                f = o["fields"]
                p = f.get("parent") or {}
                pf = p.get("fields") or {}
                rec = {"summary": f.get("summary") or "",
                       "type": (f.get("issuetype") or {}).get("name", ""),
                       "parent_key": p.get("key", ""), "parent_summary": pf.get("summary", ""),
                       "parent_type": (pf.get("issuetype") or {}).get("name", ""),
                       "status": (f.get("status") or {}).get("name", ""),
                       "status_cat": ((f.get("status") or {}).get("statusCategory") or {}).get("key", "")}
                # merge: an issue can appear several times (top level, as a parent, in issuelinks);
                # keep every non-empty value instead of letting a sparse nested reference win
                # v0.17.3: open "is blocked by" links (Jira link type "Blocked", inward side)
                blk = []
                for l in f.get("issuelinks") or []:
                    if ((l.get("type") or {}).get("name") == "Blocked") and l.get("inwardIssue"):
                        bi = l["inwardIssue"]; bf = bi.get("fields") or {}; st = bf.get("status") or {}
                        blk.append({"key": bi.get("key", ""), "summary": bf.get("summary", ""),
                                    "status": st.get("name", ""),
                                    "statusCat": (st.get("statusCategory") or {}).get("key", "")})
                if blk:
                    rec["blocked_by"] = blk
                cur = out.setdefault(o["key"], {})
                for k2, v2 in rec.items():
                    if v2 and not cur.get(k2):
                        cur[k2] = v2
                    cur.setdefault(k2, v2)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(json.loads(Path(path).read_text()))
    return out


def days_since(d, today):
    if not d:
        return 0
    return max(0, (date.fromisoformat(today) - date.fromisoformat(d[:10])).days)


def build_epics(path, today):
    if not path or not Path(path).exists():
        return None, None, []
    E = json.loads(Path(path).read_text())
    ms = E.get("milestone") or MILESTONE
    name = ms.get("name", "")
    disc = name.replace("Delivery", "Discovery") if name else None
    slow = {}
    for s in E.get("slowStories", []):
        d = days_since(s.get("since"), today)
        b = slow.setdefault(s.get("epic"), {"slow14": 0, "stale100": 0})
        if d > 100:
            b["stale100"] += 1
        elif d > 14:
            b["slow14"] += 1
    epics = []
    for e in E.get("epics", []):
        fv = e.get("fixVersions") or []
        cat = e.get("statusCategory", "")
        epics.append({
            "key": e["key"], "summary": e.get("summary", ""), "status": e.get("status", ""), "cat": cat,
            "size": e.get("size") or "", "pm": SIZE_PM.get((e.get("size") or "").upper()),
            "fixVersions": fv, "committed": name in fv, "discovery": bool(disc) and disc in fv and name not in fv,
            "days": days_since(e.get("inProgressSince"), today) if cat == "indeterminate" else 0,
            "total": e.get("total"), "done": e.get("done"), "inProgress": e.get("inProgress"),
            **slow.get(e["key"], {"slow14": 0, "stale100": 0}),
        })
    it = E.get("iteration") or {}
    milestone = {"label": name, "start": ms.get("start"), "end": ms.get("end")} if name else None
    return milestone, it, epics


def clean_testray(path):
    if not path or not Path(path).exists():
        return '<p class="sec-sub">Testray snapshot not collected in this run.</p>'
    tr = Path(path).read_text()
    tr = re.sub(r"<(script|style)[\s\S]*?</\1>", "", tr)

    def keep(m):
        tag, attrs = m.group(1), m.group(2) or ""
        k = " ".join(re.findall(r'\b(?:href|colspan|rowspan)="[^"]*"', attrs))
        if tag.lower() == "a":
            k += ' target="_blank" rel="noopener"'
        return "<" + tag + (" " + k if k else "") + ">"
    tr = re.sub(r"<([a-zA-Z0-9]+)(\s[^>]*)?>", keep, tr)
    return re.sub(r"<h2>Methodology</h2>[\s\S]*$", "", tr)


# ── 3. Render ──────────────────────────────────────────────────────────────
def load_roster(context_path):
    """{name: {"aid": Jira accountId, "gh": GitHub login}} from the context file's Account IDs + Team GitHub Logins."""
    if not context_path or not Path(context_path).exists():
        return {}
    text = Path(context_path).read_text()

    def section(name):
        m = re.search(r"## " + re.escape(name) + r"\s*\n+```json\n(.*?)```", text, re.S)
        try:
            return json.loads(m.group(1)) if m else {}
        except Exception:
            return {}
    aids = {**section("Designer Account IDs"), **section("Account IDs")}
    # GitHub roster keys can carry notes, e.g. "Adolfo Pérez (confirmed Headless contributor 2026-07-09)"
    ghs = {re.sub(r"\s*\(.*\)\s*$", "", n).strip(): g for n, g in section("Team GitHub Logins").items()}
    roster, missing = {}, []
    for n in TEAM:
        if n in aids:
            roster[n] = {"aid": aids[n], "gh": ghs.get(n, "")}
        else:
            missing.append(n)
    if missing:
        print(f"⚠ Assign picker: no Jira account ID in the context file for {', '.join(missing)} — left out")
    return roster


GH_PR_RE = re.compile(r'https://github\.com/[\w.-]+/[\w.-]+/pull/\d+')


def render(rep, info, milestone, it, epics, testray_html, avd, roster=None, prs=None):
    epic_by_name = {e["summary"].strip(): e["key"] for e in (epics or []) if e.get("summary")}

    def enrich(rows):
        for r in rows:
            r["prUrls"] = sorted(set(GH_PR_RE.findall(r["action"] + " " + r["url"])))
            i = info.get(r["key"], {})
            r["summary"], r["type"] = i.get("summary", ""), i.get("type", "")
            r["status"], r["statusCat"] = i.get("status", ""), i.get("status_cat", "")
            # v0.17.3: show every "is blocked by" issue with its live status, so we see when work can start
            blk = i.get("blocked_by") or []
            if blk:
                r["blockedBy"] = blk
                notes = []
                for b in blk:
                    done = b.get("statusCat") == "done"
                    notes.append(("✅ Unblocked — " if done else "🔒 Blocked by ") +
                                 f'<a href="https://liferay.atlassian.net/browse/{html.escape(b["key"])}" target="_blank" rel="noopener">{html.escape(b["key"])}</a> '
                                 + html.escape(b.get("summary", "")) + f' ({html.escape(b.get("status", "?"))})'
                                 + (" — can start" if done else ""))
                if r["action"].strip() == "Start" and any(b.get("statusCat") != "done" for b in blk):
                    r["action"] = "Wait — blocked"
                r["action"] = (r["action"] + "<br><br>" if r["action"] else "") + "<br><br>".join(notes)
            # Standalone PR rows (v0.15.0): PR title + linked Jira key (and its status when known)
            mpr = re.match(r"PR#(\d+)$", r["key"])
            if mpr and prs and int(mpr.group(1)) in prs:
                pr = prs[int(mpr.group(1))]
                title = (pr.get("title") or "").strip()
                jk = pr.get("jira_key") or ""
                if jk and title.startswith(jk):
                    title = title[len(jk):].lstrip(" :-|")
                r["summary"] = title or r["summary"]
                if jk:
                    ji = info.get(jk, {})
                    r["prJira"] = {"key": jk, "status": ji.get("status", ""), "statusCat": ji.get("status_cat", ""),
                                   "summary": ji.get("summary", "")}
            # Topic = parent epic: prefer the parent from jira_data, else match the epic name
            if i.get("parent_key") and (i.get("parent_type") == "Epic" or i.get("parent_summary", "").strip() == r["topic"]):
                r["epicKey"] = i["parent_key"]
            elif r["topic"] and r["topic"].strip() in epic_by_name:
                r["epicKey"] = epic_by_name[r["topic"].strip()]
        return rows
    s1a, s1c, hidden = classify_1(enrich(rep["s1a"]))
    sections = {
        "s1a": s1a,
        "s1b": enrich(rep["s1b"]),
        "s1h": sort_1c(s1c),
        "s2a": enrich(rep["s2pr"] + rep["s2a_needs_owner"]),
        "s2b": enrich(rep["s2b_assigned"]),
        "hidden": hidden,
    }
    start, end = iteration_dates(rep["sprint_label"], rep["date"])
    iteration = None
    if start:
        lbl = rep["sprint_label"].split("|")[1] if "|" in rep["sprint_label"] else rep["sprint_label"]
        iteration = {"label": lbl, "start": start, "end": end, "url": ITERATION_FILTER_URL,
                     "total": (it or {}).get("total", 0), "done": (it or {}).get("done", 0)}
    D = {"meta": {"date": rep["date"], "sprint_label": rep["sprint_label"], "version": BOARD_VERSION},
         "iteration": iteration, "milestone": milestone, "sections": sections, "excl": rep["excl"],
         "epics": epics or [], "avd": avd, "team": [n for n in TEAM if n in roster] if roster else TEAM, "roster": roster or {}}
    body = (HERE / "board_body.html").read_text()
    body = (body.replace("__SPRINT__", html.escape(rep["sprint_label"]))
                .replace("__REMAINING__", str(rep["days_remaining"]))
                .replace("__DATE__", html.escape(rep["date"]))
                .replace("__TESTRAY__", testray_html))
    data = json.dumps(D, ensure_ascii=False).replace("</", "<\\/")
    page = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Headless Daily — {html.escape(rep["date"])}</title>'
            '<script>try{var t=localStorage.getItem("headless-board-theme");'
            'if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t);}catch(e){}</script>'
            '<style>\n'
            + (HERE / "base.css").read_text() + "</style></head><body>\n" + body
            + "<script>\nwindow.D=" + data + ";\n" + (HERE / "board_app.js").read_text()
            + "</script></body></html>")
    return page, sections


def validate_epics(path):
    """Friendly schema check for the epics.json Claude writes in step 2."""
    E = json.loads(Path(path).read_text())
    errs = []
    if not isinstance(E.get("epics"), list):
        errs.append('"epics" must be a list')
    for i, e in enumerate(E.get("epics") or []):
        for k in ("key", "summary", "status", "statusCategory", "fixVersions"):
            if k not in e:
                errs.append(f"epics[{i}] missing {k}")
        if e.get("statusCategory") not in ("new", "indeterminate", "done"):
            errs.append(f"epics[{i}] statusCategory must be new/indeterminate/done (got {e.get('statusCategory')!r})")
    if len(E.get("epics") or []) > MAX_EPICS:
        errs.append(f"{len(E['epics'])} epics > MAX_EPICS={MAX_EPICS} — stop and ask the user")
    it = E.get("iteration") or {}
    if not isinstance(it.get("total"), int):
        errs.append('"iteration": {"total": int, "done": int} missing')
    if errs:
        sys.exit("epics.json problems:\n  - " + "\n  - ".join(errs))


def plan(epic_keys):
    q = f'issuetype = Epic AND {TEAM_CLAUSE} AND (statusCategory = "In Progress" OR fixVersion = "{MILESTONE["name"]}") AND statusCategory != Done'
    print(f"cloudId: {CLOUD_ID} · run independent calls in parallel · never expand changelog\n")
    print("A. Epics (searchJiraIssuesUsingJql, maxResults 50):")
    print(f"   jql: {q}")
    print(f'   fields: ["summary","status","fixVersions","statuscategorychangedate","{TSHIRT_FIELD}"]')
    print(f"   → if more than {MAX_EPICS} epics: STOP and ask the user.\n")
    print('B. Iteration (searchResultMode "count"):')
    print(f"   jql: filter = {ITERATION_FILTER}")
    print(f"   jql: filter = {ITERATION_FILTER} AND statusCategory = Done\n")
    print(f'C. Testray: getConfluencePage pageId {TESTRAY_PAGE_ID}, contentFormat "html" → write body to WORK_DIR/testray.html\n')
    if epic_keys:
        print('D. Per epic (searchResultMode "count"), for every key:')
        for k in epic_keys:
            print(f'   parent = {k} | parent = {k} AND statusCategory = Done | parent = {k} AND statusCategory = "In Progress"')
        print("\nE. Slow stories (searchJiraIssuesUsingJql):")
        print(f'   jql: parent in ({",".join(epic_keys)}) AND statusCategory = "In Progress" AND statusCategoryChangedDate <= -14d')
        print('   fields: ["status","statuscategorychangedate","parent"]\n')
    else:
        print("D/E: re-run with --epic-keys K1,K2,... (keys from call A) to get the per-epic calls.\n")
    print("Then write WORK_DIR/epics.json (compact, no raw API objects):")
    print(json.dumps({"iteration": {"total": 0, "done": 0},
                      "epics": [{"key": "LPD-1", "summary": "…", "status": "In Development", "statusCategory": "indeterminate",
                                 "fixVersions": ["…"], "size": "2XL", "inProgressSince": "YYYY-MM-DD",
                                 "total": 0, "done": 0, "inProgress": 0}],
                      "slowStories": [{"key": "LPD-2", "epic": "LPD-1", "status": "In Progress", "since": "YYYY-MM-DD"}]},
                     ensure_ascii=False))
    print("statusCategory = status category key (new/indeterminate); inProgressSince = statuscategorychangedate date; size = T-shirt value or \"\".")


def find_inputs(today, roots=None):
    """Newest stable preview for today + newest jira_data.json modified today."""
    import os
    found = {"report": [], "jira": []}
    for root in roots or SEARCH_ROOTS:
        if not os.path.isdir(root):
            continue
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if d not in ("node_modules", ".git", "proc")]
            for f in fn:
                p = os.path.join(dp, f)
                if f == f"daily_actions_report_{today}.html" or (f.startswith("daily_actions_report_") and today in f and f.endswith(".html")):
                    found["report"].append(p)
                elif f == "jira_data.json" and str(date.fromtimestamp(os.path.getmtime(p))) == today:
                    found["jira"].append(p)
    pick = lambda L: max(L, key=lambda p: Path(p).stat().st_mtime) if L else None
    return pick(found["report"]), pick(found["jira"])


# ── Iteration auto-detect (keeps the shared context page's Sprint Metadata current) ──
def active_hl_sprint(jira_data_path):
    """Most common ACTIVE sprint whose name starts with 'HL' among the fetched issues."""
    from collections import Counter
    c = Counter()

    def walk(o):
        if isinstance(o, dict):
            f = o.get("fields")
            if "key" in o and isinstance(f, dict):
                for sp in f.get("customfield_10020") or []:
                    if isinstance(sp, dict) and sp.get("state") == "active" and str(sp.get("name", "")).startswith("HL"):
                        c[(sp["name"], (sp.get("startDate") or "")[:10])] += 1
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(json.loads(Path(jira_data_path).read_text()))
    return c.most_common(1)[0][0] if c else (None, None)


def sync_sprint(context_path, jira_data_path, today):
    """Update Sprint Metadata in context_scratch.md when Jira's active HL sprint differs. Returns a message."""
    name, start_hint = active_hl_sprint(jira_data_path)
    if not name:
        return "Iteration check: no active HL sprint found in jira_data — Sprint Metadata left unchanged (report this)."
    text = Path(context_path).read_text()
    m = re.search(r"(## Sprint Metadata\n)(.*?)(?=\n## |\Z)", text, re.S)
    if not m:
        return "Iteration check: no '## Sprint Metadata' section in the context file — left unchanged (report this)."
    meta = m.group(2)
    cur = re.search(r"^sprint_field:\s*(.+)$", meta, re.M)
    if cur and cur.group(1).strip() == name:
        return f"Iteration check: unchanged ({name})."
    label = name[2:]
    start, end = iteration_dates(label, start_hint or today)
    new = {"sprint_label": label, "sprint_field": name, "label_dev": label,
           "label_dis": label.replace("|DEV#", "|DIS#"), "start_date": start, "end_date": end}
    for k, v in new.items():
        if v is None:
            continue
        if re.search(rf"^{k}:", meta, re.M):
            meta = re.sub(rf"^{k}:.*$", f"{k}: {v}", meta, flags=re.M)
        else:
            meta = meta.rstrip("\n") + f"\n{k}: {v}\n"
    Path(context_path).write_text(text[:m.start(2)] + meta + text[m.end(2):])
    return f"Iteration check: UPDATED {cur.group(1).strip() if cur else '?'} → {name} ({start} – {end})."


def count_check(rep, s):
    checks = [("1a+1c+folded = stable 1a", len(s["s1a"]) + len(s["s1h"]) + len(s["hidden"]), len(rep["s1a"])),
              ("1b = stable 1b", len(s["s1b"]), len(rep["s1b"])),
              ("2a = stable Open PRs + 2a", len(s["s2a"]), len(rep["s2pr"]) + len(rep["s2a_needs_owner"])),
              ("2b = stable 2b", len(s["s2b"]), len(rep["s2b_assigned"]))]
    bad = [f"{n}: {a} vs {b}" for n, a, b in checks if a != b]
    print("Count check: OK" if not bad else "Count check: MISMATCH — " + "; ".join(bad))
    return not bad


def self_test():
    sample = ('<div class="sprint-bar">26M4|DEV#21|Oct05-Oct16  ·  10d remaining  ·  2026-10-06</div>'
              '<h3>1a. Needs Attention <span class="section-count">(2 items)</span></h3><table><thead><tr><th>P</th></tr></thead><tbody>'
              '<tr style="background:#dbeafe"><td>Planned | <strong>Focus</strong></td><td>Epic X</td><td><a href="https://liferay.atlassian.net/browse/LPD-1" target="_blank">LPD-1</a></td><td>A</td><td>20d in progress 🔴</td><td>20d in development — check for blockers</td></tr>'
              '<tr style="background:#f5f5f5"><td>Planned | <strong>Regular</strong></td><td></td><td><a href="https://liferay.atlassian.net/browse/LPD-2" target="_blank">LPD-2</a></td><td>B</td><td>4d in progress</td><td>No reviewer assigned — <a href="https://github.com/x/pull/1">PR#1</a></td></tr>'
              '</tbody></table>')
    rep = parse_report(sample)
    assert rep["sprint_label"] == "26M4|DEV#21|Oct05-Oct16" and rep["days_remaining"] == 10
    assert [r["key"] for r in rep["s1a"]] == ["LPD-1", "LPD-2"]
    a, c, h = classify_1(rep["s1a"])
    assert [r["key"] for r in a] == ["LPD-2"] and [r["key"] for r in c] == ["LPD-1"] and not h
    assert iteration_dates("26M4|DEV#21|Oct05-Oct16", "2026-10-06") == ("2026-10-05", "2026-10-16")
    assert iteration_dates("x|Dec28-Jan08", "2026-12-30") == ("2026-12-28", "2027-01-08")
    unplanned = dict(rep["s1a"][0], kind="Unplanned")
    quiet = dict(rep["s1a"][0], days="3d in progress", action="New comment from X")
    a, c, h = classify_1([unplanned, quiet])
    assert a == [unplanned] and not c and h == [quiet]
    rows = [dict(key="S", type="Spike", days="40d"), dict(key="T", type="Task", days="30d"),
            dict(key="A", type="Story", days="16d"), dict(key="B", type="Story", days="25d"), dict(key="G", type="Bug", days="9d")]
    assert [r["key"] for r in sort_1c(rows)] == ["B", "A", "T", "G", "S"]
    import tempfile, os
    d = tempfile.mkdtemp()
    ctx = os.path.join(d, "c.md"); jd = os.path.join(d, "j.json")
    Path(ctx).write_text("# x\n## Sprint Metadata\nsprint_label: 26M3|DEV#20|Sep21-Oct02\nsprint_field: HL26M3|DEV#20|Sep21-Oct02\n"
                         "label_dev: 26M3|DEV#20|Sep21-Oct02\nlabel_dis: 26M3|DIS#20|Sep21-Oct02\nstart_date: 2026-09-21\n"
                         "end_date: 2026-10-02\nactions_report_page_id: 1\n## State Snapshot\n```json\n{}\n```\n")
    Path(jd).write_text(json.dumps({"sprint_issues": [{"key": "LPD-1", "fields": {"customfield_10020": [
        {"name": "HL26M3|DEV#20|Sep21-Oct02", "state": "closed"},
        {"name": "HL26M4|DEV#21|Oct05-Oct16", "state": "active", "startDate": "2026-10-05T08:00:00Z"}]}}]}))
    msg = sync_sprint(ctx, jd, "2026-10-07")
    t = Path(ctx).read_text()
    assert "UPDATED" in msg and "sprint_field: HL26M4|DEV#21|Oct05-Oct16" in t and "label_dis: 26M4|DIS#21|Oct05-Oct16" in t
    assert "start_date: 2026-10-05" in t and "end_date: 2026-10-16" in t and "actions_report_page_id: 1" in t and "## State Snapshot" in t
    assert "unchanged" in sync_sprint(ctx, jd, "2026-10-07")
    print("self-test OK")


def main():
    ap = argparse.ArgumentParser(description="Headless Daily Board (beta)")
    ap.add_argument("--find-inputs", action="store_true"); ap.add_argument("--plan", action="store_true")
    ap.add_argument("--build", action="store_true"); ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--epic-keys", default=""); ap.add_argument("--work-dir", default=".")
    ap.add_argument("--date", default=str(date.today()))
    ap.add_argument("--report-html"); ap.add_argument("--jira-data-file"); ap.add_argument("--epics-file")
    ap.add_argument("--testray-file"); ap.add_argument("--avd-file"); ap.add_argument("--out")
    ap.add_argument("--pr-data-file", help="pr_data.json (default WORK_DIR/pr_data.json) — titles for standalone PR rows")
    ap.add_argument("--copy-to", default="/mnt/user-data/outputs")
    ap.add_argument("--sync-sprint", action="store_true"); ap.add_argument("--context-file")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.plan:
        return plan([k.strip() for k in a.epic_keys.split(",") if k.strip()])
    if a.sync_sprint:
        if not (a.context_file and a.jira_data_file):
            sys.exit("--sync-sprint needs --context-file and --jira-data-file")
        print(sync_sprint(a.context_file, a.jira_data_file, a.date)); return
    if a.find_inputs:
        r, j = find_inputs(a.date)
        print(f"stable preview: {r or 'NOT FOUND — run the daily actions report first'}")
        print(f"jira_data.json: {j or 'not found (summaries/types/epic links will be missing)'}")
        return
    if not (a.build or a.report_html):
        ap.print_help(); return

    wd = Path(a.work_dir)
    r, j = (None, None) if (a.report_html and a.jira_data_file) else find_inputs(a.date)
    report_html = a.report_html or r
    if not report_html:
        sys.exit("Stable preview for today not found — run the daily actions report first.")
    jira_data = a.jira_data_file or j
    epics_file = a.epics_file or (str(wd / "epics.json") if (wd / "epics.json").exists() else None)
    testray = a.testray_file or (str(wd / "testray.html") if (wd / "testray.html").exists() else None)
    avd_file = a.avd_file or (str(wd / "avd.json") if (wd / "avd.json").exists() else None)
    if epics_file:
        validate_epics(epics_file)

    rep = parse_report(Path(report_html).read_text())
    if not rep["s1a"] and not rep["s2a_needs_owner"] and not rep["s2b_assigned"]:
        sys.exit("No report sections found — is this the stable skill's preview file? "
                 f"Sections seen: {rep['found_sections']}")
    info = summaries_from_jira_data(jira_data)
    milestone, it, epics = build_epics(epics_file, rep["date"])
    avd = json.loads(Path(avd_file).read_text()) if avd_file else None
    ctx_file = a.context_file or (str(wd / "context_scratch.md") if (wd / "context_scratch.md").exists() else None)
    roster = load_roster(ctx_file)
    pr_file = a.pr_data_file or (str(wd / "pr_data.json") if (wd / "pr_data.json").exists() else None)
    prs = {int(p["pr_number"]): p for p in json.loads(Path(pr_file).read_text())} if pr_file else {}
    # Jira issues linked from standalone PRs (not in jira_data.json): WORK_DIR/pr_jira.json, written by
    # Claude from the PR parent-resolution getJiraIssue calls — {key: {summary, status, statusCategory}}
    prj_file = wd / "pr_jira.json"
    if prj_file.exists():
        for k, v in json.loads(prj_file.read_text()).items():
            cur = info.setdefault(k, {})
            cur.setdefault("summary", v.get("summary", "")); cur.setdefault("status", v.get("status", ""))
            cur.setdefault("status_cat", v.get("statusCategory", ""))
    page, s = render(rep, info, milestone, it, epics, clean_testray(testray), avd, roster, prs)
    out = Path(a.out) if a.out else wd / f"board_{rep['date']}.html"
    out.write_text(page)
    print(f"Board {BOARD_VERSION} → {out}")
    print(f"Inputs: preview={report_html} · jira_data={jira_data or '-'} · pr_data={pr_file or '-'} · epics={epics_file or '-'} · testray={testray or '-'} · avd={avd_file or '-'}")
    print("Rows: " + ", ".join(f"{k}={len(v)}" for k, v in s.items()) + f", excluded={len(rep['excl'])}")
    count_check(rep, s)
    print(f"Assign roster: {len(roster)} people" + (" (no context file — Assign will be disabled)" if not roster else ""))
    print(f"Epics: {len(epics or [])} (committed {sum(1 for e in (epics or []) if e['committed'])})"
          f" · AVD: {'yes' if avd else 'not connected'} · Testray: {'yes' if testray else 'no'}")
    missing = sorted({r["key"] for v in s.values() for r in v if "atlassian" in r["url"] and r["key"] not in info})
    if missing:
        print(f"No summary/type for {len(missing)} keys: {', '.join(missing[:15])}")
    if a.copy_to and Path(a.copy_to).is_dir():
        dst = Path(a.copy_to) / out.name
        dst.write_text(page)
        print(f"Copied for delivery → {dst}")


if __name__ == "__main__":
    main()
