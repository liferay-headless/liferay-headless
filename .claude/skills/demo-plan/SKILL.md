---

description: Build the weekly Headless team demo plan by picking a current and a fallback ticket per member from Jira and producing a Slack-ready announcement.
name: demo-plan

---

# Demo Plan

Each Monday the daily is replaced by a team demo. Every team member shows the work they currently own (or, if it is too early, the most recent piece they wrapped up). This skill produces the weekly announcement: it queries each member's open and recently closed Jira tickets and emits a Slack-ready message that the host can paste into the team channel.

## Input

### Member Roster

The roster below is the source of truth for who demos each week and how to address them. The Slack handles do not always match the Jira display name (Slack handles use first names, nicknames, or email-style logins). Use this exact mapping when emitting the message — never invent a handle from the Jira name alone. The bullets in the output are in this order.

| Jira name             | Account ID                                     | Slack handle           |
| --------------------- | ---------------------------------------------- | ---------------------- |
| Alejandro Tardín      | `5ce7d3ef8fa24d0dd2de9989`                     | `@Alejandro Tardín`    |
| Carlos Correa García  | `62050b847334070067553c44`                     | `@Carlos Correa`       |
| Jaime León Rosado     | `633c09763ac41ebde76da845`                     | `@Jaime León Rosado`   |
| Jorge González        | `605242d9009fee00693ade38`                     | `@boton`               |
| Magdalena Jedraszak   | `6107dedec51f3a0069dffc8a`                     | `@Meg Jedraszak`       |
| Vendel Töreki         | `606cbbb63e6ea00068536e7f`                     | `@Vendel Töreki`       |
| Alberto Moreno Lage   | `64198a787222b08f3e722b76`                     | `@Alberto Moreno`      |
| Gábor Komáromi        | `606da595edc14f00769a90f1`                     | `@Gábor Komáromi`      |
| Daniel Raposo Sánchez | `712020:7f3f1739-bbf7-4824-9b42-7e1196684ff6`  | `@Daniel Raposo`       |
| Petteri Karttunen     | `557058:09ff46ee-56b3-491b-9454-4540bf458976`  | `@Petteri Karttunen`   |
| Jose Luis Navarro     | `712020:2de6b052-0fdc-4f34-8b53-9bede77e739d`  | `@joseluis.navarro`    |

When the team composition changes, update this table. The skill does not infer roster changes from any external source.

### Per-Member Lookup

For every roster `accountId`, run two JQL searches in parallel via `searchJiraIssuesUsingJql`:

1. **Current WIP** — `assignee = <accountId> AND project = LPD AND statusCategory = "In Progress" ORDER BY updated DESC` with `maxResults=5`.
1. **Recently closed** — `assignee = <accountId> AND project = LPD AND statusCategory = Done ORDER BY resolved DESC` with `maxResults=3`.

Request the fields `summary`, `status`, `issuetype`, `updated`, `resolutiondate`. Wrap account IDs that contain `:` in double quotes inside the JQL string.

## Expected Output

A Slack-ready message copied to the clipboard. Do not post it from the skill — the host owns the announcement. After copying, tell the caller that the clipboard holds the message and that they need to convert each `@handle` into a real Slack mention before sending.

The message has this exact shape:

```
• @<slack-handle>
    ◦ Current: https://liferay.atlassian.net/browse/LPD-XXXXX — <summary>
    ◦ Fallback: https://liferay.atlassian.net/browse/LPD-YYYYY — <summary>
```

Every member gets the same two-line block — no exceptions, no alternate labels.

- **Outer bullet** (`•`): one per member, in roster order. `<slack-handle>` is the exact value from the Member Roster table for that member's `accountId` — never derive it from the Jira display name.
- **`Current:` line**: the parent Story/Task/Bug with the most recent `updated` timestamp from the **Current WIP** query. Skip Technical Task subtasks unless they're the only signal of progress, in which case use the parent Story's URL with the subtask's summary. Deprioritize Investigate / Poshi / flaky-test tickets — surface them only when nothing more substantive is open. If the member has zero In Progress tickets, pull `Current:` from the **Recently closed** query (most recent `resolved`).
- **`Fallback:` line**: the next-most-recent parent Story/Task/Bug from the **Recently closed** query, skipping Technical Task duplicates and the ticket already used on the `Current:` line. Recently closed feature work outranks old test fixes.
- **Links**: bare URLs, one per inner bullet. Do not use the `<url|label>` form (Slack's rich-text composer renders the pipe literally). Do not embed extra ticket links inside the summary.
- **Summary**: the Jira `summary` field, lightly trimmed. No trailing punctuation.
