# Graph — the shared medium

The review is built as a **provenance graph** in `output/<handle>/graph.json`. Every pipeline agent reads the current graph and **appends** nodes and edges; nothing already in the graph is rewritten. It is a DAG: derived claims point through edges to what they're built on, recursing down to the evidence leaves.

## Shape

```json
{ "nodes": [ { "id": "...", "type": "...", "label": "...", ...typed fields } ],
  "edges": [ { "from": "<derived node>", "to": "<grounding node>", "why": "..." } ] }
```

**Grounding.** This is why the agent docs only list the *nodes* an agent adds — the edges are implied by the grounding rules here:

- Every node you add (other than evidence) **must be grounded** — it has ≥1 outgoing edge, pointing **derived → grounding** to the node(s) it's built on. Only evidence records are **leaves**. (`validate` enforces this: a non-evidence leaf is an error.)
- Every edge MUST carry a non-empty `why` — the one phrase that justifies the link.
- Topology is **flexible**: a node may ground in work items *and/or* raw evidence directly (a node may ground straight in evidence that belongs to no work item). Pick whatever nodes actually justify the claim.

**Findings — optional intermediate grounding.** Any deriving agent may add `finding` nodes between its main node and the nodes below it, when a graded sub-claim ties several pieces together. A finding is just `label` + `text` + `grade`, created in the agent's own namespace as `<owner>:finding:<n>`. A finding MUST ground in **≥2** nodes (`validate` enforces this) — a one-child finding adds nothing, so if a claim rests on a single node, skip the finding and link the main node directly to that node. Findings are optional: ground the main node directly when no synthesis is needed.

## Node id namespaces

| prefix | type(s) | created by |
| --- | --- | --- |
| `ev:<url>` | `commit`, `pull_request`, `comment`, `review:<state>`, `review_comment`, `jira_comment`, `created_ticket`, `lpp_ticket` | collect |
| `wi:<ticket>` | `work_item` | group |
| `axis:<key>` | `radar_axis` (`pr_reviews`/`lpp`/`testing`/`delivery`/`discovery`/`speed`) | axis agents |
| `<owner>:finding:<n>` | `finding` | any deriving agent (axes, summary) |
| `summary` | `summary` | summary agent |

## Rules for an agent

1. **Create only in your own namespace.** An axis agent for `testing` creates `axis:testing` and `testing:finding:1`, `testing:finding:2`, … — never touches `ev:*`, `wi:*`, or another axis's ids.
2. **Link to existing ids.** Your edges reference nodes already in the graph (`ev:…`, `wi:…`) by their exact id — you do not recreate them. The evidence leaves carry the **full record** (commit/PR/comment `text`, commit `authored`/`committed`, ticket metadata) — read what you need straight from the graph; there is no separate ledger file.
3. **No prescribed starting point.** Read the whole graph and find the nodes relevant to your lens yourself; don't assume an entry layer.
4. **Append with the two primitives — never hand-edit `graph.json`, never write a fragment file.** `graph.py` has exactly two write commands; pass each a single object or a JSON array, via stdin (`-`) so nothing hits disk:

   ```bash
   ./graph.py --dir <dir> add-node - <<'JSON'
   [ {"id":"axis:testing","type":"radar_axis","label":"Testing","grade":"meets","score":70,"text":"..."},
     {"id":"testing:finding:1","type":"finding","grade":"meets","label":"...","text":"..."} ]
   JSON
   ./graph.py --dir <dir> add-edge - <<'JSON'
   [ {"from":"axis:testing","to":"testing:finding:1","why":"..."},
     {"from":"testing:finding:1","to":"wi:LPD-123","why":"..."} ]
   JSON
   ```

   Both just append (no dedupe — you create unique ids in your own namespace; `validate` catches any accidental duplicate). Each call takes an exclusive lock on the graph, so the **parallel axis subagents can all append directly and concurrently** — no merge step, no per-agent fragment files.

5. **Enriching an existing node** (adding fields to a node already in the graph — e.g. the group agent adding `grade`/`text`/`theme` onto a skeleton `work_item`) is the one case you may **edit `graph.json` directly**. Only a **sequential** agent that runs alone may do this; the parallel axes must never edit the file in place.

## Node fields

- Every node has `id`, `type`, `label` (a terse title) and `text` (a sentence describing it). What `text` says is the agent's call — its own doc defines it.
- **Every node except the evidence leaves carries a `grade`** — the role-calibrated tier `below` / `meets` / `exceeds` / `exceeds-enables` (see `rating-calibration.md`). `validate` enforces it, so the per-agent node specs don't repeat it — assume it on every node you add. `below` is for a genuine shortfall, not a small-but-competent contribution.
- Any further fields are per-type and declared in the agent's own node spec (an axis's `score`, an evidence leaf's `url`/`date`, …).
