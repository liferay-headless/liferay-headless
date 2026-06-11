# Group Agent

Group the evidence into one graded work-item per ticket the member **worked on or reviewed** — the ticket is the unit of contribution, not the commit or comment. A ticket they only *filed* (no work, no review) stays as evidence, not a work-item.

## Run

```bash
./agents/1-group/group-evidence.py --dir output/<handle>
```

It buckets the evidence by ticket and, for every ticket the member worked on or reviewed, creates a skeleton `work_item` node and links it to its evidence (whether they authored it or only reviewed it — the `role` you write captures which). Tickets they only filed are skipped — they remain evidence the axes can cite.

## Enrich

Then edit the graph directly (safe — the group step runs alone, before the parallel axes) to enrich each `wi:*` node **from its grounding evidence** — the records it links to. Set on each:

```json
{
  "label": "value from the script",        // you may also refine this if needed.
  "role": "author",                        // the member's part on the ticket, not the work: author | co-author | driver | reviewer (only reviewed) | reporter (filed only) …
  "text": "what the work actually was",    // one line; read the commits/PR bodies/comments, don't restate the label
  "theme": ["export-import", "testing"]    // tags hinting the axes: testing | security | support | refactor | filed …
}
```

The script also stamps `issuetype` on each `work_item` (the ticket's Jira type — `Spike`, `Bug`, `Task`, …); leave it as-is, the axes read it (Discovery keys off `Spike`).

