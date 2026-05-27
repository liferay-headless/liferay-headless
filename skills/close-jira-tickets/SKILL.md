---

allowed-tools: Bash(curl *), Bash(git *), Glob, Grep, Read
argument-hint: "[ticket key(s) or a JQL filter]"
description: Close LPD Jira tickets whose work has already merged into brianchandotcom/liferay-portal. Use when asked to close, resolve, or clean up WIP tickets that are done.
name: close-jira-tickets

---

# Close Merged Jira Tickets

Close LPD tickets whose code already reached `brianchandotcom/liferay-portal`
master using `../../rules/jira-rest-api.md`.

## Confirm the Work Merged

A ticket is "merged by Brian" when its commits are in the master branch of the
remote tracking `brianchandotcom/liferay-portal`. Forwarding rewrites commit SHAs, so match by commit message, after fetching the latest version.

All commits matching means the work landed. The PR may show as `CLOSED` (the CI
bot closes it on forward) rather than merged.

## Locate the Ticket Carrying the PR

The PR URL lives in the **Git Pull Request** field (`customfield_10201`). A
**Task** records the PR on its **Technical Task** subtask, while a **Bug** or
**Technical Task** records it on itself. Read that field together with
`subtasks` and `issuetype`, then grep `brian/master` for the ID of whichever
ticket actually holds the work.

## Close the Ticket

Transition IDs and screen fields vary by issue type and current status, so never
hardcode them. Fetch the issue transitions expanded with their fields, pick the
one whose `to.name` is `Closed`, then post that transition ID with the
type-specific fields below. A successful transition returns HTTP `204`.

### Confirm Before Closing

Once you have confirmed which tickets merged and located the ticket carrying each
PR, list every ticket you are about to close and stop for the user's explicit
confirmation before transitioning anything. For each ticket show:

- the **title**,
- the **Jira link** (`https://liferay.atlassian.net/browse/<KEY>`), and
- the **PR link** (from the **Git Pull Request** field).

Do not transition any ticket until the user confirms. If the user drops some
tickets from the list, close only the ones they keep.

### Required Fields by Issue Type

The allowed resolutions and required fields differ per type. A **Bug** uses
`Fixed`; a **Task** and a **Technical Task** reject `Fixed` and use `Completed`.

| Issue Type | Resolution | Other Required Fields |
| --- | --- | --- |
| Technical Task | `Completed` | None |
| Task | `Completed` | None |
| Bug | `Fixed` | `customfield_10979` (Cross Cutting Properties) as an array, e.g. `[{"value": "None"}]`; a Fix version, e.g. `{"name": "Master"}` |

The Bug Fix version is enforced by a transition validator even though the field
metadata marks it optional. Ask the user which version to set; use `Master` for
master-only work.

### Parent Tasks Close Last

A parent **Task** exposes the **Closed** transition only once every Technical
Task subtask is already Closed. Close the subtasks first, then refetch the
parent's transitions and close it.

## Verify

Refetch the closed keys and confirm each reports status `Closed` with the
expected resolution.