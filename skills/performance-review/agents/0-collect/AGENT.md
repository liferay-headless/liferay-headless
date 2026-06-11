# Collect Agent

Pull all of the member's evidence into the graph as the leaf nodes — mechanical, no judgment.

## Run

From the skill dir (needs `gh` logged in and `JIRA_API_USER` / `JIRA_API_TOKEN` set — see `../../rules/jira-rest-api.md`):

```bash
./agents/0-collect/collect-evidence.py --dir output/<handle> --github <github> --jira-account-id <jira_account_id> --since <since> --until <until>
```

The collector owns the mechanics — repo list, queries, the personal-fork check, peer-only/CI filtering of GitHub comments — and writes the evidence leaf nodes itself (one per record, carrying the full source record; see `graph.md`).
