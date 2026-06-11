#!/usr/bin/env python3
import argparse, json, collections, math, os
from jinja2 import Environment, FileSystemLoader, select_autoescape

# Axes clockwise from the top; the radar is an N-gon computed from this order,
# so adding/removing an axis here reshapes the polygon with no geometry edits.
AXES = ["pr_reviews", "lpp", "testing", "delivery", "discovery", "speed", "brian"]
AXIS_LABEL = {"pr_reviews": "PR Reviews", "lpp": "LPP", "testing": "Testing",
              "delivery": "Delivery", "discovery": "Discovery", "speed": "Speed",
              "brian": "Brian"}
CX, CY, R = 160.0, 150.0, 120.0
RING_FRACS = [0.25, 0.5, 0.75, 1.0]
RING = {"meets": ("meets", "Meets expectations"),
        "exceeds": ("exceeds", "Exceeds expectations"),
        "exceeds-enables": ("enables", "Exceeds & enables others")}
def is_peer(t): return t in ("comment", "review_comment") or t.startswith("review:")


def _unit(i, n):
    """Unit direction of axis i of n, clockwise from straight up."""
    a = math.radians(-90 + i * 360.0 / n)
    return math.cos(a), math.sin(a)


def radar_geom(scored):
    """Geometry for an N-axis radar from [(key, score), …] in clockwise order:
    score points + labels per axis, the concentric ring polygons, and the spokes."""
    n = len(scored)
    axes, verts = [], []
    for i, (k, s) in enumerate(scored):
        ux, uy = _unit(i, n)
        f = s / 100.0
        anchor = "middle" if abs(ux) < 0.25 else ("start" if ux > 0 else "end")
        axes.append({
            "key": k, "score": s,
            "x": round(CX + R * f * ux, 2), "y": round(CY + R * f * uy, 2),
            "lx": round(CX + (R + 14) * ux, 2),
            "ly": round(CY + (R + 14) * uy + (10 if uy > 0.25 else 0), 2),
            "label": AXIS_LABEL[k], "anchor": anchor})
        verts.append((round(CX + R * ux, 2), round(CY + R * uy, 2)))
    rings = []
    for frac in RING_FRACS:
        rings.append(" ".join(f"{round(CX + R * frac * _unit(i, n)[0], 2)},"
                              f"{round(CY + R * frac * _unit(i, n)[1], 2)}"
                              for i in range(n)))
    spokes = [{"x": x, "y": y} for x, y in verts]
    return axes, rings, spokes

LEAN_EV = {"id", "type", "label", "url", "date", "grade"}
def embed_graph(graph):
    nodes = [{k: v for k, v in n.items() if k in LEAN_EV} if n["id"].startswith("ev:") else n
             for n in graph["nodes"]]
    return {"nodes": nodes, "edges": graph["edges"]}


def context(graph, person):
    nodes = {n["id"]: n for n in graph["nodes"]}
    c = collections.Counter()
    for n in graph["nodes"]:
        if n["id"].startswith("ev:"):
            t = n["type"]; c["peer" if is_peer(t) else t] += 1
    rc, rt = RING.get(nodes.get("summary", {}).get("grade"), ("meets", "Meets expectations"))
    present = [k for k in AXES if "axis:" + k in nodes]  # radar adapts to the axes that ran
    axes, rings, spokes = radar_geom([(k, nodes["axis:" + k]["score"]) for k in present])
    return {
        "name": person.get("name"), "role": person.get("role"),
        "period": person.get("period"), "gh": person.get("gh"),
        "rating_class": rc, "rating_text": rt,
        "summary": nodes.get("summary", {}).get("text", ""),
        "counts": {"commits": c["commit"], "prs": c["pull_request"], "peer": c["peer"],
                   "jira": c["jira_comment"], "tickets": c["created_ticket"]},
        "axes": axes, "rings": rings, "spokes": spokes, "cx": CX, "cy": CY,
        "graph_json": json.dumps(embed_graph(graph), ensure_ascii=False).replace("</", "<\\/"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="output", help="run directory (default for --graph/--out)")
    ap.add_argument("--graph", help="graph (default <dir>/graph.json)")
    ap.add_argument("--template", help="Jinja2 template (default: template.html next to this script)")
    ap.add_argument("--out", help="output HTML (default <dir>/review.html)")
    ap.add_argument("--person", help="JSON file with name/role/period/gh (default <dir>/person.json)")
    ap.add_argument("--name"); ap.add_argument("--role"); ap.add_argument("--period"); ap.add_argument("--gh")
    a = ap.parse_args()
    graph_path = a.graph or os.path.join(a.dir, "graph.json")
    out_path = a.out or os.path.join(a.dir, "review.html")
    person_path = a.person or (os.path.join(a.dir, "person.json") if not a.name else None)
    person = json.load(open(person_path)) if person_path else \
        {"name": a.name, "role": a.role, "period": a.period, "gh": a.gh}
    template = a.template or os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")
    env = Environment(loader=FileSystemLoader(os.path.dirname(template) or "."),
                      autoescape=select_autoescape(["html"]))
    out = env.get_template(os.path.basename(template)).render(
        **context(json.load(open(graph_path)), person))
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    open(out_path, "w").write(out)
    print(f"rendered {out_path}")


if __name__ == "__main__":
    main()
