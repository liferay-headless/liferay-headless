# Render Agent

Turn the finished graph + the person details into the self-contained HTML — mechanical, no judgment. `template.html` (in this folder) owns all markup; `render.py` fills it.

## Run

From the skill directory (person details come from the orchestrator: `name`, `role`, `period` delivery label, `gh` handle):

```bash
./agents/4-render/render.py --dir output/<handle> \
  --name "<Display Name>" --role "<Role>" --period "<Month YYYY>" --gh <handle>
```

`render.py` derives the context from the graph (rating tier → ring, the `summary` text, per-type `counts`, the six axis `score`-points, and the whole graph embedded for the drill-down panel) and writes `output/<handle>/review.html` — the top section (identity · rating · summary · radar) plus the embedded graph and the static panel. **All look-and-feel lives in `template.html`** — iterate there, not in the script. To preview without a run, render the fixture: `./agents/4-render/render.py --dir output/octocat`.

Confirm: no `{{ }}` token survives; the rating ring, the summary, and the six radar dots carry `data-node`; the embedded graph parses.
