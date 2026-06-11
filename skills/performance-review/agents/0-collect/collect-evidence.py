#!/usr/bin/env python3
import argparse
import base64
import collections
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import graph as G
import urllib.error

REPOS = [
    "liferay/liferay-portal",
    "liferay/liferay-portal-ee",
    "liferay-headless/liferay-portal",
    "liferay-headless/liferay-headless",
    "liferay-headless/github-actions",
    "4lejandrito/cliferay",
]

JIRA_BASE = "https://liferay.atlassian.net"
NON_ENGINEERING_PROJECTS = ["EVRM"]
TICKET_RE = re.compile(r"(?<![A-Za-z0-9-])[A-Z][A-Z0-9]+-\d+(?![\d-])")


def gh(args):
    """Run a `gh` command; return parsed JSON, or the raw string for scalar --jq output."""
    out = subprocess.run(["gh", *args], capture_output=True, text=True)
    if out.returncode != 0:
        sys.stderr.write(f"gh {' '.join(args)} failed:\n{out.stderr}\n")
        return None
    s = out.stdout.strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return s


def gh_lines(args):
    """Run a `gh` command whose --jq emits one JSON object per line; yield parsed objects."""
    out = subprocess.run(["gh", *args], capture_output=True, text=True)
    if out.returncode != 0:
        sys.stderr.write(f"gh {' '.join(args)} failed:\n{out.stderr}\n")
        return
    for line in out.stdout.splitlines():
        line = line.strip()
        if line:
            yield json.loads(line)


def keys_in(text):
    return sorted(set(TICKET_RE.findall(text or "")))


def day(ts):
    """Truncate any ISO timestamp to its YYYY-MM-DD day."""
    return (ts or "")[:10]


def repo_from_url(url):
    """github.com/<owner>/<repo>/commit|pull|issues/... -> 'owner/repo'."""
    m = re.search(r"github\.com/([^/]+/[^/]+)/(?:commit|pull|issues)/", url or "")
    return m.group(1) if m else None


class Jira:
    def __init__(self, user, token):
        self.auth = "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()

    def get(self, path, retries=4):
        url = f"{JIRA_BASE}{path}"
        req = urllib.request.Request(url, headers={
            "Authorization": self.auth, "Accept": "application/json"})
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.loads(r.read().decode())
            except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
                if attempt == retries - 1:
                    sys.stderr.write(f"Jira GET {path} failed: {e}\n")
                    return None
                time.sleep(1.5 * (attempt + 1))


def adf_text(node):
    """Flatten an Atlassian Document Format body to plain text."""
    out = []

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "text":
                out.append(n.get("text", ""))
            for c in n.get("content", []) or []:
                walk(c)
        elif isinstance(n, list):
            for c in n:
                walk(c)

    walk(node)
    return " ".join(" ".join(out).split())


CI_COMMAND_RE = re.compile(r"^(ci:|reignite\b|retest\b|run ci\b|:?retry\b)", re.I)


def is_ci_command(text):
    return bool(CI_COMMAND_RE.match((text or "").strip()))


def record(type_, *, title, url, date, text, tickets, repo=None, **extra):
    """One flat evidence record: a fixed common core plus type-specific extras.

    Core (every record): type, date, title, url, text, tickets (list of Jira
    keys), repo ("owner/repo" or None for Jira-sourced records). `extra` carries
    the few type-specific fields — commit timestamps, ticket metadata.
    """
    return {"type": type_, "date": date, "title": title, "url": url,
            "text": text, "tickets": tickets, "repo": repo, **extra}


def collect_commits(login, since, until, repos):
    repo_flags = []
    for r in repos:
        repo_flags += ["--repo", r]
    data = gh([
        "search", "commits", "--author", login, "--author-date", f"{since}..{until}",
        *repo_flags, "--limit", "1000", "--json", "sha,commit,url",
    ]) or []
    out = []
    for c in data:
        commit = c.get("commit", {})
        msg = commit.get("message", "")
        url = c.get("url", "")
        authored = commit.get("author", {}).get("date")
        committed = commit.get("committer", {}).get("date")
        out.append(record(
            "commit",
            title=msg.split("\n", 1)[0], url=url, date=day(authored),
            text=msg, tickets=keys_in(msg), repo=repo_from_url(url),
            authored=authored, committed=committed,
        ))
    return out


def collect_prs(login, since, until, repos):
    repo_flags = []
    for r in repos:
        repo_flags += ["--repo", r]
    data = gh([
        "search", "prs", "--author", login, "--updated", f"{since}..{until}",
        *repo_flags, "--limit", "1000",
        "--json", "title,url,updatedAt,body",
    ]) or []
    out = []
    for p in data:
        url = p.get("url")
        out.append(record(
            "pull_request",
            title=p.get("title"), url=url, date=day(p.get("updatedAt")),
            text=p.get("body") or "", tickets=keys_in(p.get("title", "")),
            repo=repo_from_url(url),
        ))
    return out


def collect_github_threads(login, since, until, own_keys):
    """Every peer comment and review the user left, one record each.

    The `commenter:` search only finds the threads the user took part in; it
    does not say what they wrote. For each such thread we pull the user's own
    text from the comment/review endpoints — conversation comments (issues and
    PRs), PR review summaries (APPROVE / REQUEST_CHANGES bodies), and inline
    code-review comments — and emit one record per piece. The record `type` is
    the piece's kind (`comment`, `review:<state>`, `review_comment`).

    Only peer activity is kept (comments on someone else's work); chatter on the
    user's own changes and CI-bot command strings (`ci:…`) carry no review
    signal and are dropped.
    """
    out = []
    for item in gh_lines([
        "api", "--paginate",
        f"search/issues?q=commenter:{login}+updated:{since}..{until}&per_page=100",
        "--jq", ".items[]",
    ]):
        title = item.get("title", "")
        keys = keys_in(title)
        own = (item.get("user") or {}).get("login") == login or \
            any(k in own_keys for k in keys)
        if own:
            continue
        repo = repo_from_url(item.get("html_url"))
        number = item.get("number")
        if not repo or number is None:
            continue
        is_pr = bool(item.get("pull_request"))

        def emit(body, url, ts, kind):
            body = (body or "").strip()
            d = day(ts)
            if not body or is_ci_command(body) or not (since <= d < until):
                return
            out.append(record(kind, title=title, url=url, date=d,
                              text=body, tickets=keys, repo=repo))

        for c in gh_lines(["api", "--paginate",
                           f"repos/{repo}/issues/{number}/comments?per_page=100",
                           "--jq", ".[]"]):
            if (c.get("user") or {}).get("login") == login:
                emit(c.get("body"), c.get("html_url"), c.get("created_at"), "comment")

        if is_pr:
            for r in gh_lines(["api", "--paginate",
                               f"repos/{repo}/pulls/{number}/reviews?per_page=100",
                               "--jq", ".[]"]):
                if (r.get("user") or {}).get("login") == login:
                    emit(r.get("body"), r.get("html_url"), r.get("submitted_at"),
                         f"review:{(r.get('state') or '').lower()}")
            for c in gh_lines(["api", "--paginate",
                               f"repos/{repo}/pulls/{number}/comments?per_page=100",
                               "--jq", ".[]"]):
                if (c.get("user") or {}).get("login") == login:
                    emit(c.get("body"), c.get("html_url"), c.get("created_at"),
                         "review_comment")
    return out


def collect_jira_comments(jira, account_id, since, until, candidate_keys):
    out = []
    for key in sorted(candidate_keys):
        if not TICKET_RE.fullmatch(key):
            continue
        d = jira.get(f"/rest/api/3/issue/{key}/comment?maxResults=200")
        if not d:
            continue
        for c in d.get("comments", []):
            if c.get("author", {}).get("accountId", "") != account_id:
                continue
            created = day(c.get("created"))
            if not (since <= created < until):
                continue
            body_text = adf_text(c.get("body", {}))
            title = (body_text[:140] + "…") if len(body_text) > 140 else body_text
            out.append(record(
                "jira_comment",
                title=title or f"Comment on {key}",
                url=f"{JIRA_BASE}/browse/{key}?focusedCommentId={c['id']}",
                date=created, text=body_text, tickets=[key],
            ))
    return out


def collect_ticket_types(jira, keys):
    """Batch-fetch each ticket's issue-type name → {key: "Spike"/"Bug"/…}.

    The type is a per-ticket fact the work-item layer needs (e.g. Discovery keys
    off Spikes); commits/PRs only carry the ticket *key*, so we resolve the type
    here and stamp it onto every ticket-bearing evidence record.
    """
    keys = sorted(k for k in keys if TICKET_RE.fullmatch(k))
    out = {}
    for i in range(0, len(keys), 50):
        chunk = keys[i:i + 50]
        jql = f'key in ({", ".join(chunk)})'
        q = urllib.parse.quote(jql)
        d = jira.get(f"/rest/api/3/search/jql?jql={q}&maxResults=50&fields=issuetype")
        for it in (d or {}).get("issues", []):
            out[it["key"]] = (it.get("fields", {}).get("issuetype") or {}).get("name")
    return out


def collect_created_tickets(jira, account_id, since, until):
    exclude = (f' AND project NOT IN ({", ".join(NON_ENGINEERING_PROJECTS)})'
               if NON_ENGINEERING_PROJECTS else "")
    jql = (f'reporter = "{account_id}" AND created >= "{since}" '
           f'AND created < "{until}"{exclude} ORDER BY created DESC')
    q = urllib.parse.quote(jql)
    fields = "summary,issuetype,priority,status,created,resolutiondate,description"
    d = jira.get(f"/rest/api/3/search/jql?jql={q}&maxResults=200&fields={fields}")
    out = []
    for i in (d or {}).get("issues", []):
        f = i.get("fields", {})
        out.append(record(
            "created_ticket",
            title=f"{i['key']} {f.get('summary', '')}".strip(),
            url=f"{JIRA_BASE}/browse/{i['key']}",
            date=day(f.get("created")),
            text=adf_text(f.get("description")), tickets=[i["key"]],
            issuetype=(f.get("issuetype") or {}).get("name"),
            priority=(f.get("priority") or {}).get("name"),
            status=(f.get("status") or {}).get("name"),
            resolutiondate=day(f.get("resolutiondate")) or None,
        ))
    return out


def collect_lpp_assignments(jira, account_id, since, until):
    """LPP (customer support) tickets the member was assignee of, with activity in
    the window.

    LPP issues are customer-reported — they're the customer-facing provenance the
    LPP axis keys off, and they're invisible to the LPD/GitHub collectors. We keep
    tickets *assigned* to the member that were created, resolved, or otherwise
    touched inside the window — not every closed ticket they still nominally own
    (an `assignee WAS … DURING` match on a years-old closed ticket is not work
    done this period). Each record also carries `linked_tickets` (the LPD/LRHC
    engineering issues the LPP links to) so the axis can bridge a customer issue to
    the engineering work already in the graph.
    """
    jql = (f'project = LPP AND assignee = "{account_id}" AND ('
           f'(resolutiondate >= "{since}" AND resolutiondate < "{until}") OR '
           f'(created >= "{since}" AND created < "{until}") OR '
           f'(updated >= "{since}" AND updated < "{until}")) ORDER BY updated DESC')
    q = urllib.parse.quote(jql)
    fields = ("summary,issuetype,priority,status,created,resolutiondate,updated,"
              "description,issuelinks")
    d = jira.get(f"/rest/api/3/search/jql?jql={q}&maxResults=200&fields={fields}")
    out = []
    for i in (d or {}).get("issues", []):
        f = i.get("fields", {})
        links = []
        for l in f.get("issuelinks", []) or []:
            o = l.get("outwardIssue") or l.get("inwardIssue")
            if o:
                links.append(o["key"])
        out.append(record(
            "lpp_ticket",
            title=f"{i['key']} {f.get('summary', '')}".strip(),
            url=f"{JIRA_BASE}/browse/{i['key']}",
            date=day(f.get("resolutiondate")) or day(f.get("updated")),
            text=adf_text(f.get("description")), tickets=[i["key"]],
            issuetype=(f.get("issuetype") or {}).get("name"),
            priority=(f.get("priority") or {}).get("name"),
            status=(f.get("status") or {}).get("name"),
            resolutiondate=day(f.get("resolutiondate")) or None,
            linked_tickets=sorted(set(links)),
        ))
    return out


def main():
    ap = argparse.ArgumentParser(description="Collect performance-review evidence into one flat JSON array.")
    ap.add_argument("--github", required=True, help="GitHub handle / login")
    ap.add_argument("--jira-account-id", required=True, help="Jira account ID from the roster")
    ap.add_argument("--since", required=True, help="window start (YYYY-MM-DD, inclusive)")
    ap.add_argument("--until", required=True, help="window end (YYYY-MM-DD, exclusive)")
    ap.add_argument("--dir", default="output", help="run output directory")
    ap.add_argument("--graph", help="graph to write (default <dir>/graph.json)")
    args = ap.parse_args()

    user = os.environ.get("JIRA_API_USER")
    token = os.environ.get("JIRA_API_TOKEN")
    if not (user and token):
        sys.exit("JIRA_API_USER and JIRA_API_TOKEN must be set.")

    since, until = args.since, args.until
    jira = Jira(user, token)

    repos = list(REPOS)
    fork = f"{args.github}/liferay-portal"
    if gh(["api", f"repos/{fork}", "--jq", ".full_name"]):
        repos.append(fork)

    commits = collect_commits(args.github, since, until, repos)
    prs = collect_prs(args.github, since, until, repos)

    own_keys = set()
    for r in commits + prs:
        own_keys.update(r.get("tickets", []))

    threads = collect_github_threads(args.github, since, until, own_keys)

    candidate_keys = set(own_keys)
    candidate_keys.update(t for r in threads for t in r["tickets"])

    created = collect_created_tickets(jira, args.jira_account_id, since, until)
    candidate_keys.update(t for r in created for t in r["tickets"])

    lpp = collect_lpp_assignments(jira, args.jira_account_id, since, until)
    # The LPP keys join the candidate set so the member's own comments on those
    # customer tickets are collected too (see collect_jira_comments).
    candidate_keys.update(t for r in lpp for t in r["tickets"])

    jira_comments = collect_jira_comments(jira, args.jira_account_id, since, until, candidate_keys)

    # Resolve each ticket's issue type and stamp it onto every ticket-bearing
    # record. created_ticket records already carry their own issuetype; for the
    # rest (commits/PRs/comments) we look it up by the record's ticket key.
    type_map = {r["tickets"][0]: r["issuetype"] for r in created + lpp
                if r.get("tickets") and r.get("issuetype")}
    type_map.update(collect_ticket_types(jira, candidate_keys - set(type_map)))

    evidence = commits + prs + threads + jira_comments + created + lpp
    for r in evidence:
        if "issuetype" not in r and r.get("tickets"):
            r["issuetype"] = type_map.get(r["tickets"][0])
    evidence.sort(key=lambda r: r["date"], reverse=True)

    nodes = [{**r, "id": "ev:" + r["url"], "label": r["title"]} for r in evidence]
    for n in nodes:
        n.pop("title", None)
    G.add_nodes(args.graph or os.path.join(args.dir, "graph.json"), nodes)


if __name__ == "__main__":
    main()
