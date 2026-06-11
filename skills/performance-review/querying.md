# Querying for more context

The graph's evidence nodes are a **curated, trimmed** subset of GitHub and Jira — only the fields the review usually needs. Any agent may pull more when the graph is too thin to judge well. The graph is the default; reach for a live query only to fill a **specific** gap.

## How

- **GitHub** — the `gh` CLI, already authenticated. e.g. `gh api repos/<owner>/<repo>/pulls/<n>`, `gh pr view`, `gh api .../pulls/<n>/files --jq '.[].changes'`, `gh search ...`.
- **Jira** — `curl` against the REST API (auth and pattern in `../../rules/jira-rest-api.md`). Useful fields the ledger drops: a ticket's full `description`, current `status`, `priority`, `parent`/epic link, `issuelinks`, `labels`.

## Guardrails

- **Scope.** Stay within the member and the review period. Don't pull other people's work or other windows.
- **Don't refetch.** The graph already has every commit, PR, comment, review, and filed ticket — don't bulk-re-collect; query for the *extra* field or the *one* linked artifact.
- **Ground it.** Any fact you fetch must show up in a node you write (its `text`) or an edge's `why`. No silent influence.
- **Cheap first.** A single `gh api` / `curl` for the missing field beats cloning a repo or paging a whole project.
