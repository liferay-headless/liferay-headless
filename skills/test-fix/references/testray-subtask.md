# Resolve a Testray Subtask URL to a Group of Case Results

Pull every member of a Testray Subtask (ST) through the REST API at `https://testray.liferay.com`, apply two freshness checks against the routine's current state, and claim the ST for the invoking user. The caller supplies a Subtask URL as `${ARGUMENTS}`. This procedure is additive to portal's `.claude/skills/test-fix/references/testray.md` — it reuses that file's **Authentication** and **Derive the Failure Data** sections verbatim rather than restating them.

## Preconditions

In addition to `${TESTRAY_CLIENT_ID}`/`${TESTRAY_CLIENT_SECRET}` (portal's `references/testray.md` **Preconditions**), `${TESTRAY_USER_ID}` must be set. Without it, abort and surface the reason.

`${TESTRAY_USER_ID}` cannot be derived from the API — the OAuth2 client-credentials grant represents the *application*, not a logged-in human, so no endpoint can answer "who am I" for it regardless of scope (a `GET /o/headless-admin-user/v1.0/user-accounts/by-email-address/<email>` lookup 403s under these credentials, which is one symptom of this, not the whole story). Resolve it once, out of band: pick any Task, Subtask, or case result already created by or assigned to the invoking person in the Testray web UI, note its numeric id from the URL, then fetch it directly —

```bash
curl \
	--header "Accept: application/json" \
	--header "Authorization: Bearer ${ACCESS_TOKEN}" \
	--silent \
	--url "https://testray.liferay.com/o/c/tasks/<that-id>"
```

— and read `creator.id` (or, for a subtask already assigned to them, `r_userToSubtasks_userId`) from the response. GETs work fine under the app credentials; only the by-email lookup above does not. Export the value as `TESTRAY_USER_ID` once, in the shell profile, alongside `TESTRAY_CLIENT_ID`/`TESTRAY_CLIENT_SECRET`.

## Parse the URL

Parse `<taskId>` and `<subtaskId>` from `https://testray.liferay.com/#/testflow/<taskId>/subtasks/<subtaskId>`. Print both before running any query, so the parse is auditable rather than asserted.

## Claim the Subtask Immediately

This is the first network write the procedure makes — ahead of even fetching the Task, so the claim lands before any other agent or person can race for the same ST.

1. Fetch the subtask's current state:

	```bash
	curl \
		--header "Accept: application/json" \
		--header "Authorization: Bearer ${ACCESS_TOKEN}" \
		--silent \
		--url "https://testray.liferay.com/o/c/subtasks/<subtaskId>"
	```

1. When `dueStatus.key` is `INANALYSIS`, `COMPLETE`, or `MERGED` **and** `r_userToSubtasks_userId` is nonzero and does not equal `${TESTRAY_USER_ID}`, abort — someone is already working this ST. Surface who owns it (resolve the id to a name via `GET /o/c/subtasks/<subtaskId>` — the object embeds no name for the assignee directly, so cross-reference the Task's or a sibling subtask's `creator` block, or simply report the numeric id when no name is readily available) and do not claim it.

1. Otherwise, claim it:

	```bash
	curl \
		--data '{"dueStatus": {"key": "INANALYSIS", "name": "In Analysis"}, "r_userToSubtasks_userId": '"${TESTRAY_USER_ID}"'}' \
		--header "Authorization: Bearer ${ACCESS_TOKEN}" \
		--header "Content-Type: application/json" \
		--request PUT \
		--silent \
		--url "https://testray.liferay.com/o/c/subtasks/<subtaskId>"
	```

## Resolve the Routine and Build SHA

```bash
curl \
	--header "Accept: application/json" \
	--header "Authorization: Bearer ${ACCESS_TOKEN}" \
	--silent \
	--url "https://testray.liferay.com/o/c/tasks/<taskId>"
```

Read `r_buildToTasks_c_buildId`, then:

```bash
curl \
	--header "Accept: application/json" \
	--header "Authorization: Bearer ${ACCESS_TOKEN}" \
	--silent \
	--url "https://testray.liferay.com/o/c/builds/<buildId>"
```

Read `r_routineToBuilds_c_routineId` as `<routineId>` and `gitHash` as `<buildSha>`. A Task is scoped to exactly one build, so `<buildSha>` is shared by every member of the group — compute it once here, not per member.

## Freshness Check A: Is `<taskId>` the Latest Task for `<routineId>`?

There is no direct task-level routine filter (`r_routineToTasks_c_routineId` does not exist as a filter property — confirmed, do not use it). Walk builds for the routine newest-first instead, checking each one for an associated Task:

```bash
curl \
	--data-urlencode "filter=r_routineToBuilds_c_routineId eq '<routineId>'" \
	--data-urlencode "pageSize=20" \
	--data-urlencode "sort=dateCreated:desc" \
	--get \
	--header "Accept: application/json" \
	--header "Authorization: Bearer ${ACCESS_TOKEN}" \
	--silent \
	--url "https://testray.liferay.com/o/c/builds"
```

For each build id, newest first:

```bash
curl \
	--data-urlencode "fields=id,dueStatus" \
	--get \
	--header "Accept: application/json" \
	--header "Authorization: Bearer ${ACCESS_TOKEN}" \
	--silent \
	--url "https://testray.liferay.com/o/c/builds/<buildId>/buildToTasks"
```

Skip any Task whose `dueStatus.key` is `ABANDONED`. The first non-abandoned Task found, on the newest build that has one, is the latest Task.

- **Latest Task equals `<taskId>`** → no remap needed, continue to **List the Subtask's Members**.

- **Latest Task differs** → remap by case id, not by ST number (subtask names like `ST-15` are not stable across Tasks — the same underlying failure can carry a different number in a newer Task). For each member's `<caseId>` (gathered in **List the Subtask's Members** below — fetch that section first if the members aren't already known, then return here):

	```bash
	curl \
		--data-urlencode "filter=r_caseToCaseResult_c_caseId eq '<caseId>' and r_buildToCaseResult_c_buildId eq '<latestTaskBuildId>'" \
		--data-urlencode "pageSize=1" \
		--get \
		--header "Accept: application/json" \
		--header "Authorization: Bearer ${ACCESS_TOKEN}" \
		--silent \
		--url "https://testray.liferay.com/o/c/caseresults"
	```

	Read `r_subtaskToCaseResults_c_subtaskId` from the result. When a member has no case result against `<latestTaskBuildId>` (the test didn't run in that build), leave its freshness judgment to **Freshness Check B** instead of using it here.

	- **Every member resolves to the same subtask** → that subtask is the actual operating one. Re-run **Claim the Subtask Immediately** against it (it becomes `<taskId>`/`<subtaskId>` for the rest of the procedure), then revert the *original* subtask back to `dueStatus: OPEN` and `r_userToSubtasks_userId: 0` — it is stale and no one will actually work it, so it must not keep looking claimed.

	- **Members resolve to different subtasks** → stop and ask the user how to proceed. Testray's own regrouping across builds disagreeing with the original grouping is itself evidence the grouping doesn't reliably track root cause — do not auto-split silently.

## List the Subtask's Members

```bash
curl \
	--data-urlencode "filter=r_subtaskToCaseResults_c_subtaskId eq '<subtaskId>'" \
	--data-urlencode "pageSize=100" \
	--get \
	--header "Accept: application/json" \
	--header "Authorization: Bearer ${ACCESS_TOKEN}" \
	--silent \
	--url "https://testray.liferay.com/o/c/caseresults"
```

Each item's `id` is `<caseResultId>` and `r_caseToCaseResult_c_caseId` is the stable `<caseId>` — key every subsequent lookup (including the remap above and the freshness check below) on `<caseId>`, never on the subtask's own `name` (e.g. `"ST-15"`), which is not stable across Tasks.

## Hydrate Each Member and Freshness Check B

For each member's `<caseResultId>`, run portal's **Derive the Failure Data** procedure unmodified, producing `name`, `type`, `errorTrace`, `failureDate`, `firstFailSha`, `lastPassSha`, and `dueStatus`.

- `dueStatus.key` is `PASSED` → member is `excluded-passed`.
- `dueStatus.key` is `BLOCKED` → member is `excluded-blocked` (a tester deliberately flagged it — do not auto-fix, same rule as the canonical single-case-result path, just non-fatal to the rest of the group here).
- Otherwise (`FAILED`), continue to the freshness check below.

For each still-`FAILED` member, check whether it's still failing the same way in the newest execution of the routine — regardless of whether that execution has a Task yet:

```bash
curl \
	--data-urlencode "testrayRoutineIds=<routineId>" \
	--data-urlencode "pageSize=1" \
	--data-urlencode "sort=executionDate:desc" \
	--get \
	--header "Accept: application/json" \
	--header "Authorization: Bearer ${ACCESS_TOKEN}" \
	--silent \
	--url "https://testray.liferay.com/o/testray-rest/v1.0/testray-case-result-history/<caseId>"
```

The single newest entry (`items[0]`) carries `status`, `error` (full text, not truncated), `gitHash`, and `executionDate` directly — no further join is needed to compare it against the member's own `errorTrace`.

- `items[0].status` is not `FAILED` → `excluded-now-passing-upstream`. `scopeReason` names `items[0].gitHash` and `executionDate`.
- `items[0].status` is `FAILED` but `items[0].error` reads as a different failure from the member's own `errorTrace` — apply the same "Same failure / Different failure" judgment portal's `SKILL.md` Reproduce Locally step already defines — → `excluded-different-failure-upstream`.
- `items[0].status` is `FAILED` with the same error → member stays `in-scope`.

## Tag a Subtask with a Jira Ticket

Reusable for both the primary subtask and any sibling subtask opted into during the sibling sweep:

```bash
curl \
	--data '{"dueStatus": {"key": "INANALYSIS", "name": "In Analysis"}, "issues": "<comma-separated ticket keys>", "r_userToSubtasks_userId": '"${TESTRAY_USER_ID}"'}' \
	--header "Authorization: Bearer ${ACCESS_TOKEN}" \
	--header "Content-Type: application/json" \
	--request PUT \
	--silent \
	--url "https://testray.liferay.com/o/c/subtasks/<subtaskId>"
```

`issues` is additive — this is how a single subtask ends up listing more than one ticket key when its members split across tickets (the `independent` cluster mode; see `SKILL.md`). It is **not** returned by a plain `GET /o/c/subtasks/<id>` (not even with `?fields=issues`) — read it back instead via:

```bash
curl \
	--data-urlencode "testrayTaskId=<taskId>" \
	--get \
	--header "Accept: application/json" \
	--header "Authorization: Bearer ${ACCESS_TOKEN}" \
	--silent \
	--url "https://testray.liferay.com/o/testray-rest/v1.0/testray-testflow/testray-subtask"
```

which returns `issues`, `userId`, and `userName` per subtask of the given Task.
