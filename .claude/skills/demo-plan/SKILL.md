---

description: Build the weekly Headless team demo plan by reading the Work in Progress Confluence page, picking a current and a fallback ticket per member, and producing a Slack-ready announcement.
name: demo-plan

---

# Demo Plan

Each Monday the daily is replaced by a team demo. Every team member shows the work they currently own (or, if it is too early, the most recent piece they wrapped up). This skill produces the weekly announcement: it reads the canonical Work in Progress Confluence page, queries each member's open and recently closed Jira tickets, and emits a Slack-ready message that the host can paste into the team channel.

## Input

The Work in Progress Confluence page for the Headless team:

`https://liferay.atlassian.net/wiki/spaces/ENGHEADLESS/pages/2825027601/Work+in+progress`

Fetch it with `getConfluencePage` using `cloudId=liferay.atlassian.net` and the ADF body (default). The Engineering row at the top (Brian Chan, manager) is **not** part of the demo rotation — skip it. Every row under the **Headless** header maps to one demo slot. Each row contains the member's profile picture macro (carries the `accountId`) and a `blockCard` whose JQL identifies their active filter.

### Member Roster

The Slack handles below do not always match the Jira display name (Slack handles use first names, nicknames, or email-style logins). Use this exact mapping when emitting the message — never invent a handle from the Jira name alone. Order matches the Confluence page rows.

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

If a new member appears on the Confluence page that is not in the table, ask the caller for the correct Slack handle before emitting the message.

### Per-Member Lookup

For every Headless `accountId` extracted from the page, run two JQL searches in parallel via `searchJiraIssuesUsingJql`:

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
• @<slack-handle>
    ◦ Demo: https://liferay.atlassian.net/browse/LPD-ZZZZZ — <summary>
```

Each element is determined by:

- **Outer bullet** (`•`): one per Confluence-page row, in page order. `<slack-handle>` is the exact value from the Member Roster table for that row's `accountId` — never derive it from the Jira display name.
- **Inner bullets** (`◦`, four-space indent): one or two per member, picked from that member's Jira query results.
    - `Current: <url> — <summary>` — the parent Story/Task/Bug with the most recent `updated` timestamp from the **Current WIP** query. Skip Technical Task subtasks unless they're the only signal of progress, in which case use the parent Story's URL with the subtask's summary. Deprioritize Investigate / Poshi / flaky-test tickets — surface them only when nothing more substantive is open.
    - `Fallback: <url> — <summary>` — the parent Story/Task/Bug with the most recent `resolved` timestamp from the **Recently closed** query, skipping Technical Task duplicates. Recently closed feature work outranks old test fixes.
    - `Demo: <url> — <summary>` — replaces the Current/Fallback pair when the member has zero In Progress tickets. Pull from the Recently closed query.
    - `Or: <url> — <summary>` — optional second alternative paired with `Demo:`.
- **Links**: bare URLs, one per inner bullet. Do not use the `<url|label>` form (Slack's rich-text composer renders the pipe literally). Do not embed extra ticket links inside the summary.
- **Summary**: the Jira `summary` field, lightly trimmed. No trailing punctuation.

The user owning this skill is also a participant — emit a row for them too.
