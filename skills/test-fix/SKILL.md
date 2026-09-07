---

allowed-tools: [Bash, Edit, Glob, Grep, Read, Skill, Write]
argument-hint: '<caseResultId | routineName | testName | testrayBuildUrl | testraySubtaskUrl>'
description: Resolve a single Liferay test failure end-to-end.
name: test-fix

---

# Fix a Test Failure

This skill is the **liferay-portal `test-fix` skill** plus the headless-team customizations below. It is run from within the liferay-portal repo; read the canonical skill from the repo root and follow it end-to-end:

- Skill: `.claude/skills/test-fix/SKILL.md`
- Its reference: `.claude/skills/test-fix/references/testray.md`

Apply the overrides in this file wherever they touch the canonical procedure; everything the canonical skill says that is not overridden here still holds.

## Customizations

### Additional input — Routine Name

In addition to the canonical inputs (case result ID, test name, Testray build URL), accept a **routine name**: when `${ARGUMENTS}` matches `ci:test:<team>` or `[master] ci:test:<team>`, resolve it to a case result ID with the procedure below, then feed that ID into the canonical workflow exactly like any other. The procedure finds the latest build of that team routine on the master project and returns the first unclaimed failed case result on the build.

#### Resolve a Routine Name to a Case Result ID

Run the canonical **Authentication** step from portal's `.claude/skills/test-fix/references/testray.md` first, then:

1. Normalize the input by stripping a leading `[master] ` when present. The result is the canonical routine name (e.g. `ci:test:headless`), to which `[master]` is reapplied when querying.

1. Resolve the routine ID on the master project (`35392`). When zero matches, abort:

	```bash
	curl \
		--data-urlencode "filter=name eq '[master] <routineName>' and r_routineToProjects_c_projectId eq '35392'" \
		--data-urlencode "pageSize=1" \
		--get \
		--header "Accept: application/json" \
		--header "Authorization: Bearer ${ACCESS_TOKEN}" \
		--silent \
		--url "https://testray.liferay.com/o/c/routines"
	```

1. Resolve the latest build for that routine. When no build exists, abort:

	```bash
	curl \
		--data-urlencode "filter=r_routineToBuilds_c_routineId eq '<routineId>'" \
		--data-urlencode "pageSize=1" \
		--data-urlencode "sort=dateCreated:desc" \
		--get \
		--header "Accept: application/json" \
		--header "Authorization: Bearer ${ACCESS_TOKEN}" \
		--silent \
		--url "https://testray.liferay.com/o/c/builds"
	```

1. Continue with the resulting `<buildId>` through the **Resolve a Build URL to a Case Result ID** section of portal's `.claude/skills/test-fix/references/testray.md`, treating `<teamIds>` as empty (the routine itself is already the team scope).

### Additional input — Testray Subtask URL

**Pilot — headless team only for now; promote to the canonical skill later if it proves out.**

In addition to the canonical inputs and the Routine Name addition above, accept a **Testray Subtask URL**: when `${ARGUMENTS}` matches `https://testray.liferay.com/#/testflow/<taskId>/subtasks/<subtaskId>`, resolve it to a **Group** by following [`references/testray-subtask.md`](references/testray-subtask.md).

Unlike every other input — which resolves to exactly one case result and feeds the canonical linear per-test workflow — a Subtask URL resolves to a **set** of case results, because Testray groups related failures into one subtask. The Group carries:

- `taskId`, `subtaskId` — the resolved (post-freshness-check) Task/Subtask actually operated on, which may differ from what the URL named (see the freshness checks in `testray-subtask.md`).
- `originalTaskId`, `originalSubtaskId` — parsed straight from the URL, kept for audit/reporting.
- `routineId`, `buildSha` — derived once and shared by every member, since a Task is scoped to exactly one build.
- `clusterMode` — `shared-root-cause` when every member's `type` is `Poshi` or `Playwright` (these subtasks are typically grouped by a shared broken locator/UI element across otherwise-unrelated test methods, so a single fix plausibly covers all of them); `independent` for every other type (`Java Integration`, `Java Unit`, `JavaScript`, `Java Semantic Versioning` — these subtasks are typically grouped by class, and each failing method most likely has its own distinct root cause, so no shared-cause fix is attempted).
- `members` — one entry per case result in the subtask, each with the same fields the canonical **Derive the Failure Data** procedure returns for a single case result, plus a `scope` (`in-scope`, or an `excluded-*` reason — a member is never silently dropped) and `scopeReason`.

A Subtask URL input does not run the canonical linear workflow directly. Continue instead through **Additional step — Group handling in Claim the Failure** and **Additional workflow — Diagnose the Group** below.

### Additional step — Confluence-backed lock in Claim the Failure

The headless team runs `test-fix` agents concurrently, so **Claim the Failure** needs a fence around the ticket-creation window. Before the canonical first step (the Jira duplicate-ticket check), insert this step:

1. Acquire a Confluence-backed lock that fences the critical section where two agents could race to create the Jira ticket. Create a page titled `<test-name>` under the [Test Fix Claims folder](https://liferay.atlassian.net/wiki/spaces/ENGHEADLESS/folder/4939415561). Confluence enforces unique titles within a space, so page creation is the atomic primitive — only one creation succeeds. The Jira ticket is the durable claim; the lock only protects the window leading to its creation. Drive the page create and delete through the Confluence Cloud REST API with `curl` (same auth as [`../../rules/jira-rest-api.md`](../../rules/jira-rest-api.md)), never through the Atlassian MCP.

	- **Creation succeeds** → lock acquired. You are responsible for releasing it (deleting the page) — either after creating the ticket, or after deciding to skip the candidate.
	- **Creation fails with a duplicate-title error** → the test is already claimed by another agent. Skip this candidate.

### Additional step — Group handling in Claim the Failure

**Pilot — headless team only for now.** Only applies when the input resolved to a Group (see **Additional input — Testray Subtask URL**). Runs after the Confluence-backed lock above, in place of the canonical single-test dup-check-then-create sequence:

1. Run the canonical Jira duplicate-ticket check unchanged, once per in-scope member's `name` (each check still takes the Confluence lock above around its own ticket-creation window). Because `buildSha` is shared across the whole Group, the "is the fix commit an ancestor of `<buildSha>`" test for any candidate prior ticket runs once per *candidate ticket*, not once per member. Partition members into:

	- **Claimed, unresolved** — exclude, `scopeReason` names the ticket.
	- **Claimed, resolved, fix not yet in `<buildSha>`** — exclude (Testray hasn't retested since the fix merged).
	- **Claimed, resolved, fix already an ancestor of `<buildSha>`** — this occurrence isn't covered by that ticket; keep in the "still needs coverage" bucket.
	- **Unclaimed** — keep in the "still needs coverage" bucket.

1. When the "still needs coverage" bucket is empty, report every member's existing claim link and end the run — generalizes the canonical single-test "claimed, skip" exit to the whole Group.

1. Otherwise, branch on `clusterMode`:

	- **`shared-root-cause`** — invoke `jira-task` **once** for the whole bucket. Summary names the representative failure; description enumerates every member in the bucket (test name, case result id, trace excerpt) plus the source build. Tag the primary subtask with this one ticket key via **Tag a Subtask with a Jira Ticket** in `references/testray-subtask.md`.

	- **`independent`** — run the canonical single-test Claim-the-Failure procedure independently per member in the bucket (its own `jira-task` call, its own ticket, its own Confluence-lock window). Once every ticket is created, tag the primary subtask's `issues` with **all** of them at once, comma-separated — Testray's `issues` field is additive for exactly this reason, so one subtask can list several tickets when its members turned out to have distinct root causes.

1. `start-work` on each new Task, unchanged.

### Additional workflow — Diagnose the Group

**Pilot — headless team only for now.** Only applies to a Group. Runs where the canonical workflow would move from Claim the Failure into Reproduce Locally; everything this section calls is the canonical machinery from portal's `SKILL.md`, reused per member rather than replaced.

- **`independent` mode**: for each in-scope member, run the canonical **Reproduce Locally → Identify Suspect Commits → Iterate Through Suspects** exactly as documented, completely independently — its own verdict, its own unmodified 3-round budget. No clustering is attempted here: members sharing a class does not imply they share a root cause.

- **`shared-root-cause` mode**:

	1. Run **Reproduce Locally** once per in-scope member. A member that passes locally, or whose local trace is judged "different" from `errorTrace` (per the canonical Same-failure/Different-failure judgment), resolves its own verdict right there and drops out of the Group — reinterpreting the canonical single-test exit wording ("the run ends here") as scoped to that member, not to the whole Group run.

	1. Run **Identify Suspect Commits** independently per still-active member, producing each member's own ranked, line-history-narrowed candidate list.

	1. **Cluster**: intersect the ranked candidate lists across all still-active members. Two suspects count as the same root cause when they're the literal same commit, or distinct commits that resolve to the same merged PR or the same linked `LPD-XXXXX` ticket (reuse the canonical `gh pr list --search <sha>` lookup, cross-checked across members). A nonempty intersection is a genuine shared-cause candidate. An empty intersection means the members do not actually share a root cause despite being grouped together — fall back to resolving the remaining members via `independent` handling instead of forcing a shared fix.

	1. Feed a shared candidate into **Iterate Through Suspects**, with this pilot's redefinition of success: **a member is done once the specific error its subtask/ticket describes no longer reproduces for it — not once the member is fully green.** If the candidate clears the described error but a different, unrelated failure now surfaces for that member, it still counts as resolved for this run; the new failure is out of scope, to be picked up whenever it lands in its own future subtask. Members that clear together under one candidate become one **fix group** — one commit, one PR, covering all of them. Members that don't clear fall through to their own next-ranked candidate; once a subset splits off this way, it gets its own fresh 3-round budget, the same as a solo single-test run would.

	1. Once every active member has a verdict, **proactively scan and verify same-file/component siblings** — do not wait for the user to name one. This step runs regardless of how many members the Group started with, including a single-member Group. List the other subtasks in the Task (post-freshness-check) and flag any whose member's test name shares the **same spec file** (the part of a Playwright case `name` before ` > `, e.g. `mcp-server-web/main/prompts.spec.ts`) or the **same component/component directory** (e.g. `mcp-server-web`) as a member of this fix group. This matters specifically for Playwright and Poshi: each failing test is its own case result and its own subtask even when several failures live in one file, or share one fixture/utility, and one broken fixture can fail many otherwise-unrelated tests in that file or component (a shared helper like `createFDSTableTests` can even span sibling files in the same component) — so a single one-line fix routinely covers more than the subtask you started from. Hydrate each flagged candidate (`references/testray-subtask.md`'s **Hydrate Each Member and Freshness Check B** stage — already inside the freshness-confirmed Task, so **Freshness Check A** does not reapply), then verify it against the fix itself, not against a resemblance in its error text: apply the candidate fix and rerun the affected spec file (a whole-file run, already needed to check for regressions, doubles as this check — no separate reproduction pass per candidate) and confirm the flagged test now passes.

	1. Present every candidate confirmed fixed by the actual rerun, plus any subtask that looked related but could not be mechanically verified (different file/component, or the rerun could not be scoped to it), and ask the user which to fold in — folding in is still never automatic, only the scan-and-verify step is. Each opted-in sibling re-enters this section from `references/testray-subtask.md`'s **Hydrate Each Member and Freshness Check B** stage. Whichever ticket ends up covering it — folded into the same Task when the root cause matches, or its own new ticket via **Additional step — Group handling in Claim the Failure** when it doesn't — gets its key added to that sibling subtask's `issues` (or the primary subtask's, when folded into the same ticket).

### Additional step — Complete Subtasks After the Pull Request

**Pilot — headless team only for now.** Only applies to a Group, in both `independent` and `shared-root-cause` mode. As soon as a fix group's Pull Request is opened (the canonical **Pull Request** step), transition every subtask that fix group covers — the primary subtask and any folded-in sibling — to `COMPLETE` via **Mark a Subtask Complete** in `references/testray-subtask.md`. Do this right after that PR is created, not at the end of the whole run and not conditioned on merge: this run's responsibility toward a subtask ends at its PR. Whether the PR merges and whether the fix holds up is checked by a separate process, not by leaving the subtask parked at `INANALYSIS` waiting on this one.

### Additional step — Group runs in Restore the Portal

**Pilot — headless team only for now.** Only applies to a Group. The canonical Restore the Portal section's idempotent-snapshot logic is unchanged; it runs exactly **once** per Group run — after every member, including any opted-in siblings, has resolved to a verdict — not once per member.

### Additional output — Tests table for a Group

**Pilot — headless team only for now.** The canonical `### Name` / `### Type` / `### Verdict` / `### Conclusion` / `### Jira Tickets` / `### Pull Request` output sections stay exactly as documented for every canonical input and for the Routine Name addition. For a Testray Subtask URL input, report instead:

- **`### Tests`** — a table, one row per member: Name, Type, Scope (`in-scope`, or the specific `excluded-*` reason from `references/testray-subtask.md`), Fix Group (an id shared by members whose verdict came from the same fix — always distinct per member in `independent` mode), Verdict, Conclusion. Every member gets a row, including excluded ones — never silently dropped.
- **`### Jira Tickets`** — one Task per ticket created in **Additional step — Group handling in Claim the Failure** (one for `shared-root-cause`, one per member needing coverage for `independent`). A `shared-root-cause` fix group additionally spawns a Bug per genuinely distinct root cause found, Fix-linked to the Task, same as the canonical single-test flow.
- **`### Pull Request`** — one entry per fix group, using the canonical PR body template extended so a fix group covering more than one test repeats the "## Failing Test" block once per covered test, ahead of one shared "## Root Cause" / "## Fix" explanation.
- One line reporting the sibling-sweep outcome — candidates found and verified, none found, or which subtasks were opted in and what came of each — always present even when nothing was found or nothing was opted in.
- `### Resolution Time` stays singular: the whole Group run's elapsed time.
