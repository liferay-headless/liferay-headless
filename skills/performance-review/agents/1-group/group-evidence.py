#!/usr/bin/env python3
import argparse, json, collections, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import graph as G

ap = argparse.ArgumentParser(description="Create skeleton work_item nodes + work_item->evidence edges.")
ap.add_argument("--dir", default="output", help="run output directory")
ap.add_argument("--graph", help="graph to read (default <dir>/graph.json)")
args = ap.parse_args()

gpath = args.graph or os.path.join(args.dir, "graph.json")
graph = json.load(open(gpath))

EV_WHY = {"commit": "commit on the ticket", "pull_request": "pull request",
          "jira_comment": "Jira comment", "created_ticket": "filed the ticket",
          "comment": "GitHub comment", "review_comment": "inline review comment"}
def ev_why(t): return "PR review" if t.startswith("review:") else EV_WHY.get(t, t)

LABEL_PRIORITY = ["created_ticket", "pull_request", "commit", "jira_comment", "comment", "review_comment"]
def label_for(recs):
    for t in LABEL_PRIORITY:
        for r in recs:
            if r["type"] == t and r.get("label"):
                return r["label"]
    return recs[0].get("label", "")

buckets = collections.defaultdict(list)
for n in graph["nodes"]:
    if n["id"].startswith("ev:"):
        for k in n.get("tickets", []):
            buckets[k].append(n)

def itype_for(ticket, recs):
    """The ticket's issue type. Prefer a record that references ONLY this ticket
    (its stamped type is unambiguous), else fall back to any record carrying one."""
    for r in recs:
        if r.get("issuetype") and r.get("tickets") == [ticket]:
            return r["issuetype"]
    return next((r.get("issuetype") for r in recs if r.get("issuetype")), None)

nodes, edges = [], []
for ticket, recs in sorted(buckets.items()):
    # a ticket they only *filed* (no work, no review) stays as evidence, not a work_item
    if all(r["type"] == "created_ticket" for r in recs):
        continue
    nodes.append({"id": "wi:" + ticket, "type": "work_item",
                  "label": label_for(recs), "ticket": ticket,
                  "issuetype": itype_for(ticket, recs)})
    for r in recs:
        edges.append({"from": "wi:" + ticket, "to": r["id"], "why": ev_why(r["type"])})

G.add_nodes(gpath, nodes)
G.add_edges(gpath, edges)
