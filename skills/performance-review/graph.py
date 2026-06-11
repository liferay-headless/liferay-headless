#!/usr/bin/env python3
import argparse, json, collections, os, sys, fcntl, contextlib

EV_TYPES = {"commit", "pull_request", "jira_comment", "created_ticket", "comment", "review_comment", "lpp_ticket"}
def is_evidence(t): return t in EV_TYPES or t.startswith("review:")

def read_json(path):
    """Load JSON from a file path, or from stdin when path is '-'."""
    return json.load(sys.stdin) if path == "-" else json.load(open(path))

def load(path): return json.load(open(path)) if os.path.exists(path) else {"nodes": [], "edges": []}
def save(graph, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    json.dump(graph, open(path, "w"), indent=2, ensure_ascii=False)

@contextlib.contextmanager
def locked(path):
    """Hold an exclusive lock for a read-modify-write, so concurrent agents serialize."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    f = open(path + ".lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN); f.close()


def add_nodes(graph_path, nodes):
    """Append nodes under an exclusive lock. Returns count added.
    (No dedupe — agents create unique ids in their own namespace; `validate`
    catches any accidental duplicate.)"""
    with locked(graph_path):
        graph = load(graph_path)
        graph["nodes"].extend(nodes)
        save(graph, graph_path)
    return len(nodes)


def add_edges(graph_path, edges):
    """Append edges under an exclusive lock. Returns count added."""
    with locked(graph_path):
        graph = load(graph_path)
        graph["edges"].extend(edges)
        save(graph, graph_path)
    return len(edges)


def _cli_add_node(args):
    items = read_json(args.source)
    if isinstance(items, dict): items = [items]
    n = add_nodes(args.graph, items)
    print(f"add-node: +{n} nodes -> {args.graph}")


def _cli_add_edge(args):
    items = read_json(args.source)
    if isinstance(items, dict): items = [items]
    n = add_edges(args.graph, items)
    print(f"add-edge: +{n} edges -> {args.graph}")


def _cli_validate(args):
    graph = load(args.graph)
    nid = {n["id"]: n for n in graph["nodes"]}
    out = collections.defaultdict(list)
    for e in graph["edges"]: out[e["from"]].append(e["to"])
    problems = []
    if len(nid) != len(graph["nodes"]): problems.append("duplicate node ids")
    dangling = [e for e in graph["edges"] if e["from"] not in nid or e["to"] not in nid]
    if dangling: problems.append(f"{len(dangling)} dangling edges (e.g. {dangling[0]})")
    nowhy = [e for e in graph["edges"] if not (e.get("why") or "").strip()]
    if nowhy: problems.append(f"{len(nowhy)} edges with empty why")
    leaves = [i for i in nid if not out[i]]
    bad_leaves = [i for i in leaves if not is_evidence(nid[i]["type"])]
    if bad_leaves: problems.append(f"{len(bad_leaves)} non-evidence leaves (e.g. {bad_leaves[0]})")
    thin = [i for i in nid if nid[i]["type"] == "finding" and len(out[i]) < 2]
    if thin: problems.append(f"{len(thin)} finding nodes grounded in <2 nodes (e.g. {thin[0]})")
    ungraded = [i for i in nid if not is_evidence(nid[i]["type"]) and not (nid[i].get("grade") or "").strip()]
    if ungraded: problems.append(f"{len(ungraded)} non-evidence nodes without a grade (e.g. {ungraded[0]})")
    # Speed is a median over the whole commit set, so axis:speed must ground in EVERY commit.
    if "axis:speed" in nid:
        commits = {i for i in nid if nid[i]["type"] == "commit"}
        missing = commits - set(out["axis:speed"])
        if missing: problems.append(f"axis:speed not grounded in {len(missing)} of {len(commits)} commits (e.g. {sorted(missing)[0]})")
    color = {}; sys.setrecursionlimit(100000); cyc = []
    def dfs(u):
        color[u] = 1
        for v in out[u]:
            if v not in nid: continue
            if color.get(v) == 1: cyc.append((u, v))
            elif v not in color: dfs(v)
        color[u] = 2
    for n in nid:
        if n not in color: dfs(n)
    if cyc: problems.append(f"cycle(s) detected (e.g. {cyc[0]})")
    bt = collections.Counter(n["type"] for n in graph["nodes"])
    print(f"validate: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges")
    print("  node types:", dict(bt))
    print("  leaves:", len(leaves), "(all evidence:", not bad_leaves, ")")
    if problems:
        print("  PROBLEMS:"); [print("   -", p) for p in problems]; sys.exit(1)
    print("  OK — acyclic DAG, no dangling edges, evidence-only leaves, every edge has a why")


def main():
    ap = argparse.ArgumentParser(description="The provenance graph — two write primitives + a validator.")
    ap.add_argument("--dir", default="output", help="run output directory")
    ap.add_argument("--graph", help="the graph being built (default <dir>/graph.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add-node"); p.add_argument("source", help="node JSON (object or array), or '-' for stdin"); p.set_defaults(fn=_cli_add_node)
    p = sub.add_parser("add-edge"); p.add_argument("source", help="edge JSON (object or array), or '-' for stdin"); p.set_defaults(fn=_cli_add_edge)
    p = sub.add_parser("validate"); p.set_defaults(fn=_cli_validate)
    args = ap.parse_args()
    args.graph = args.graph or os.path.join(args.dir, "graph.json")
    args.fn(args)


if __name__ == "__main__":
    main()
