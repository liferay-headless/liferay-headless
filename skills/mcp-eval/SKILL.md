---

allowed-tools: [Agent, AskUserQuestion, Bash, Read, TaskCreate, TaskList, TaskUpdate, Write]
description: Evaluate Liferay MCP discoverability and usability by attempting a list of user-supplied use cases against a live Liferay instance, failing any case that runs past a three-issue threshold. Produces a per-case verdict (OK / PARTIAL / FAIL), the roadblocks hit (discovery cost, scope ambiguity, missing prerequisites, schema confusion, MCP wrapper bugs, missing endpoints, auth or permission), and a concrete fix for each defect tagged by the surface that owns the change (OpenAPI spec, resource impl, MCP wrapper, external), rendered as a self-contained HTML report. Use when the user asks to evaluate the Liferay MCP, test its discoverability, or report on how well an AI can accomplish typical Liferay operations through it.
name: mcp-eval

---

# Liferay MCP Evaluation

Drive the Liferay MCP through a list of user-supplied use cases and report how discoverable and usable it is for an AI agent. The output is an evidence-based critique — not a list of "what I did", but a list of what got in the way and why.

## Core Principle: MCP-Only

The point of this evaluation is to prove the MCP, on its own, is enough to accomplish realistic Liferay tasks. The moment work leaks out to any non-MCP channel — `curl`, the Liferay UI, a client JAR, the database, the repo's OpenAPI YAML — the result stops measuring the MCP and starts measuring your ingenuity at routing around it. So the constraint is **hard**, not aspirational: every operation a case needs, from discovery through verification, goes through a `mcp__liferay-mcp__*` tool, retried through the MCP as many times as the task needs, and when the MCP genuinely cannot complete an operation after those retries, **that is the finding** — recorded rather than routed around.

This constraint binds the sub-agent that runs each case, not the orchestrator (which never touches Liferay). The exact out-of-bounds list, the bookkeeping tools that stay allowed, and the one narrow post-FAIL log-reading exception all live in the **Sub-Agent Prompt Template** below.

## Input

The user supplies a list of use cases, clearly split from one another — typically by numbering. Each case is a natural-language description of a Liferay operation. Cases range from simple to complex:

- A simple case fits on one line: "Create a web content article".

- A complex case spans multiple lines, carrying preconditions or several steps.

Treat each item as one case in full, however many lines it occupies — do not assume one line means one case. When the split is ambiguous, ask the user how they intend the list to divide rather than guessing.

When the user asks for an evaluation without providing cases, ask them for the list before proceeding. Do not invent cases.

## Workflow

The evaluation runs through two layers. The **orchestrator** — the agent running this skill — never invokes Liferay MCP tools; it spawns one **sub-agent** per case, collects the per-case JSON object each returns into a running array, and finally renders those objects into a single self-contained HTML report.

Each case runs in its own fresh `general-purpose` sub-agent for the cold-start isolation the evaluation needs: no leaked tool sets, no remembered IDs, no shortcut from "the previous case found this in `c-mcpevalcustomers`". The sub-agents are independent, so the orchestrator spawns them concurrently and collects each per-case JSON object as it returns.

Every rule a sub-agent applies lives inside the **Sub-Agent Prompt Template** below, the single source of truth: the sub-agent sees only that prompt, never this orchestrator-facing half of the file. The orchestrator never scores, classifies, or formats defects itself; to change any sub-agent rule, edit the template.

### Orchestrator Steps

1. **Resolve the output directory.** Outputs must land outside the repository working tree so the working copy stays clean between runs. At the start of every run, call `AskUserQuestion` with the question "Where should I write the evaluation report?" (header "Output path"). Offer these options:

	- `~/Desktop` — visible and easy to find. Recommended.
	- `~/Documents/mcp-eval` — dedicated folder for repeat runs.
	- `/tmp/mcp-eval` — ephemeral, cleared on reboot.

	The "Other" choice the prompt always adds lets the user type a custom absolute path. Normalize the chosen value via a single `Bash` call that expands `~`, ensures the directory exists, and prints the absolute path:

	```bash
	python3 \
		-c "import os, sys; p = os.path.abspath(os.path.expanduser(sys.argv[1])); os.makedirs(p, exist_ok=True); print(p)" \
		"<user-input>"
	```

	The printed line is `<output-dir>` — reuse it as the target for every subsequent `Write` and the render step.

1. **Confirm the input.** When the user has not supplied a list of use cases, ask for one. Do not invent cases.

1. **Create one task per case.** Call `TaskCreate` once for each case at the start so the user has a visible checklist.

1. **Run every case in its own sub-agent.** Mark all case tasks `in_progress` via `TaskUpdate`, then spawn the sub-agents concurrently — issue every `Agent` call (with `subagent_type: general-purpose`) in a single message, passing each the prompt from **Sub-Agent Prompt Template** below with `<<CASE_NUMBER>>` and `<<CASE_TEXT>>` substituted. As each sub-agent returns its single per-case JSON object:

	1. Collect the object into the running array, keyed by case number so the final order matches the user's list. Keep it verbatim; do not reformat, rescore, or reword it. Then enrich the object with a `caseText` field set to the verbatim use-case text from the user's list (the same string substituted for `<<CASE_TEXT>>` in the sub-agent prompt) so the report can show the original input next to the verdict. This is the only orchestrator-side mutation of the per-case object.

	1. Mark that case's task `completed` via `TaskUpdate` with a one-line internal summary (verdict, issues used, tools tried, roadblock tags). This is bookkeeping, not the report.

1. **Render the HTML report.** Assemble the collected per-case JSON objects, in case order, into a single JSON array. Write that array to `<output-dir>/mcp-eval-report.data.json` with the `Write` tool, then splice it into the shipped template and write the final report to `<output-dir>/mcp-eval-report.html`:

	```bash
	python3 \
		-c "import pathlib; out = pathlib.Path('<output-dir>'); t = pathlib.Path('<skill-dir>/report-template.html').read_text(); d = (out / 'mcp-eval-report.data.json').read_text(); (out / 'mcp-eval-report.html').write_text(t.replace('__CASE_DATA__', d))"
	```

	`<skill-dir>` is this skill's base directory, supplied at invocation. `<output-dir>` is the absolute path resolved in Step 1. The template carries all styling and rendering logic and computes the OK/partial/fail tally in its header automatically, so the orchestrator authors no aggregate prose, summary table, or cross-cutting section — it only supplies the data array. Report the absolute path of the written `mcp-eval-report.html` to the user.

### Sub-Agent Prompt Template

The orchestrator passes this prompt to every sub-agent, with `<<CASE_NUMBER>>` replaced by the 1-based index of the case and `<<CASE_TEXT>>` replaced by the verbatim use-case text from the user's list.

```text
You are running case <<CASE_NUMBER>> of a Liferay MCP evaluation. Your only output is a single JSON object describing the case (schema below) — no Markdown, no code fence, no prose around it. You have no memory of any prior case; assume nothing about the state of the Liferay instance beyond what the live MCP tools tell you.

# Hard Constraint: MCP-Only

Every Liferay operation must go through a `mcp__liferay-mcp__*` tool. Out of bounds even when faster: `curl` against `/o/...` or `/api/...`, the Liferay UI in any browser including Playwright, Java client JARs (`com.liferay.*.rest.client`), `cliferay`, Blade, Gogo shell, direct database access, file-system access under `<bundles>`, log scraping, reading Liferay REST documentation or the OpenAPI YAML in the repo, recalled facts from auto-memory about Liferay endpoints. Discovery must come from `getToolSets`, `getToolSummaries`, and `getTool`. Bookkeeping tools (`Bash` for local `grep`, `Read`, `Write`) are allowed only when they do not touch Liferay.

When the MCP fights back, stay on it: retry through the MCP as many times as the task needs — changing the tool set, scope, or body each time — until the operation either succeeds or you have genuinely exhausted the MCP's avenues. Do not route around the MCP, and do not give up early; recording a step as impossible while an untried MCP path remains is a reporting error, not a finding. Only when the MCP truly cannot complete an operation is that the finding — record it and move on.

This constraint governs the attempt only. The one exception is post-mortem log reading: see `Post-FAIL Diagnosis` below.

# Issue Threshold: Three

Three issues is a flag, not a stop sign. Work the case through every step it legitimately needs and record each defect as it surfaces. An issue is any moment the MCP fails to behave the way its own surface advertised: a POST rejected for a missing field the schema never marked `required`, a tool set whose name promised a scope it then refuses, a "success" response that produced no entity, a wrapper error on a call that should have succeeded. Each issue is also a defect to record. Steps that behave as documented cost nothing, and discovery (`getToolSets`, `getToolSummaries`, `getTool`) never counts as an issue on its own.

Keep going past the third issue. Finding the fourth, fifth, or sixth defect in the same case is exactly what tells the reader how broken a surface is, and stopping early hides that signal. The threshold is a quality bar, not a budget: once `issuesUsed > 3` the case is a **FAIL** no matter how many steps you go on to complete, because a surface that costs four or more issues to drive has failed the usability test even when the work technically goes through. At one to three issues the case is **PARTIAL**, and a clean run with zero issues is **OK** (see **Scoring**).

Stop only when no remaining step has anything left to attempt — every dependency is missing, or the case has run to its natural end. That is a verdict, not a budget cutoff.

# Steps And Conditions

Your case may bundle several steps or named conditions — a complex case especially. Do not collapse them prematurely. Evaluate each step or condition on its own: invoke it, observe the result, and note whether it held. An issue attaches to the specific step that misbehaved, not to the case as a whole.

The case carries a single verdict, defined under **Scoring** below. When the case has more than one step or condition, give each step its own entry in the `flow` array (format below) so the reader sees which part held and which broke instead of one opaque verdict. A step that could not be attempted because of an unresolvable dependency is a `flow` entry with `outcome: "blocked"`; a step that surfaced an MCP defect is `outcome: "issue"`.

# Prerequisite Handling

Many cases need entities that must already exist — a site, a role, a content structure, a workflow definition. How you treat the prerequisite depends on where it comes from:

- **Part of the natural workflow, and the MCP exposes the setup path.** Do it through the MCP. "Create a custom object entry" naturally entails *define → publish → insert*; that is one case, not three, and none of those steps counts as an issue as long as each behaves as documented.

- **Environmental** — a workflow engine, an SMTP relay, a feature flag, anything the MCP cannot reasonably bootstrap. Tag the affected step `missing-prerequisite` and continue with any other steps that do not depend on it; the case fails only when nothing else can proceed.

Also tag `missing-prerequisite` when the requirement only surfaces mid-case, and treat each as an issue because the surface did not behave as advertised:

- The `getTool` schema named a `required` field (`contentStructureId`, `workflowDefinitionId`, `accountId`, `objectDefinitionId`) that resolves to nothing in the instance.
- An error response named an entity that does not exist.
- A "successful" response left the entity in a non-functional state (status `draft`, `inactive`, `pending`), needing a follow-up activation step the schema never mentioned.

Late discovery is the most expensive kind: the user already invested steps before learning the prerequisite even applied. Record that the discovery was late, not just that the prerequisite was missing.

# Discovery Loop

1. `getToolSets` to find a candidate tool set.
1. `getToolSummaries` to find a candidate tool.
1. `getTool` to fetch the input schema.
1. `invokeTool` to execute. When the first candidate is wrong, that is itself a finding — log it, then try the next one.

# Scoring

The verdict is the **issue count** — `issuesUsed`, the number of `outcome: "issue"` flow entries — and nothing else:

- **OK** — **zero issues**. Every step behaved exactly as its surface advertised; nothing got in the way.
- **PARTIAL** — **one to three issues** (`1 <= issuesUsed <= 3`). The surface had defects the agent had to work around, whether or not every step ultimately completed.
- **FAIL** — **more than three issues** (`issuesUsed > 3`). A surface that costs four or more issues to drive has failed the usability test, even when the work technically goes through.

The count is the whole rule. Do **not** promote a case to **OK** because the work eventually succeeded despite defects — a single issue makes it **PARTIAL**. Do **not** demote a clean run to **PARTIAL** because a step was slow or needed a documented prerequisite that behaved as advertised — zero issues is **OK**. A flow with no `issue` entries is OK; one to three is PARTIAL; four or more is FAIL.

A clean **OK** carries a `happyPathNote`; every **PARTIAL** and **FAIL** carries one `defect` per issue. When `issuesUsed > 3` but you still drove the primary objective to success through the MCP, record that in `achievable` (see **Required Output**) so the reader sees the operation is possible, just too costly.

# Post-FAIL Diagnosis

After the case has run to its end and the verdict has settled at **FAIL**, you may read the bundle logs at `<bundles>/logs/liferay.<yyyy-MM-dd>.log` to diagnose why the attempt failed and sharpen your defect bullets with a concrete root cause. This is the sole exception to the MCP-only constraint, and it is narrow: log reading only (no database, no other file-system access), available only once the verdict is **FAIL**, and never used to retroactively complete the case or change the score. If the verdict is not FAIL, do not read the logs.

# Roadblock Taxonomy

Tag every defect with one or more of these. A defect can carry several tags — record all that apply. When something fits none of them, invent a new tag and flag it explicitly so future runs consider it.

- **discovery-cost** — finding the right tool set or tool consumed disproportionate effort: empty descriptions on tool sets, oversized `getToolSummaries` payloads, names that do not hint at scope.
- **scope-ambiguity** — multiple tool sets appear to fit the same operation but target different scopes (site vs. asset library vs. depot vs. company), and the names do not disambiguate.
- **missing-prerequisite** — the call shape is right but the instance lacks required seed data (Content Structures, Forms, Object Definitions, workflow definitions, etc.).
- **dynamic-toolset** — a tool set the operation needs only exists after a separate publishing or activation step, and is not visible in the initial `getToolSets` call.
- **schema-confusion** — the input schema is technically valid but practically misleading: a `required` field with no documented default, enum values that are not enumerated, or a `body` shape that nests differently from comparable tools.
- **mcp-wrapper-bug** — the underlying REST call likely succeeded but the MCP layer returned an error (e.g. `-32603 "text must not be null"` on a 204 No Content response).
- **missing-endpoint** — the operation a user would expect (e.g. "create a Form definition") is not exposed by any MCP tool set, even though it exists in the product.
- **auth-or-permission** — the call failed with a 401/403 or an "operation not permitted" message under the MCP server's effective identity.

# Required Output

Return exactly one JSON object and nothing else: no Markdown, no code fence, no preamble or postscript. It must parse with a single `JSON.parse`. The object has this shape (the orchestrator adds a `caseText` field afterwards with the verbatim use-case text; do not include it yourself):

```json

{
  "caseNumber": <<CASE_NUMBER>>,
  "title": "<Use Case in Title Case>",
  "verdict": "OK" | "PARTIAL" | "FAIL",
  "issuesUsed": <integer; may exceed issuesMax>,
  "issuesMax": 3,
  "flow": [
    {
      "tool": "<toolSet/toolName>" | null,
      "intent": "<what the agent tried at this step>",
      "result": "<what happened>",
      "outcome": "ok" | "issue" | "blocked" | "note",
      "request": <JSON arguments passed to invokeTool, optional>,
      "response": <JSON body returned by the tool, optional>,
      "defect": {
        "tag": "<roadblock-taxonomy tag>",
        "description": "<why it is a defect, concrete enough to file as a ticket>",
        "alternatives": [
          {"title": "<fix title>", "surface": "openapi", "detail": "<one or two sentences>", "diff": "<unified diff, optional>"}
        ],
        "additional": [
          {"title": "<complementary fix title>", "surface": "resource-impl", "detail": "<one or two sentences>", "diff": "<unified diff, optional>"}
        ]
      }
    }
  ],
  "happyPathNote": "<one-line keeper>" | null,
  "achievable": "<one-line note that the case completed end-to-end through the MCP despite the issues>" | null
}

```

Field rules:

- **title** — the use case in Title Case, not the verbatim input.
- **verdict** — one of the three strings exactly; the renderer keys its color off the `OK` / `PARTIAL` / `FAIL` prefix.
- **flow** — the unified timeline of MCP interactions, from discovery through the verdict. Each entry is an object with the following fields:
	- `tool` — the `toolSet/toolName` invoked (string), or `null` for an entry that is not a tool call (a planning decision, a high-level "blocked" summary of unreached scope, the post-FAIL log read).
	- `intent` — what the agent tried to accomplish at this step, written as a short imperative or noun phrase. Inline markup applies.
	- `result` — one or two sentences on what actually happened. Inline markup applies. Reference other tools or fields inline with backticks.
	- `outcome` — one of `ok` (the action behaved as documented), `issue` (an MCP defect surfaced — this entry counts toward `issuesUsed` and must carry a `defect` object, described below), `blocked` (the agent could not attempt this part because of a prior issue), `note` (a planning step, a decision, or an observation that does not pass or fail).
	- `request` — the **complete, exact** arguments object passed to `invokeTool` for this step, reproduced field for field. This must be the literal payload that produced the `response` recorded beside it, so that a reader can copy the request, replay the call, and reproduce the same outcome. Build this field by capturing the arguments at the moment of the call, not by reconstructing them from memory afterward. Include every field the call actually sent: the full request body, every nested object, all path parameters, and the body-nesting wrapper if one was used. Never abbreviate, summarize, omit a field, or collapse a body to a representative subset, because a partial request silently misattributes the failure (a body missing a required attachment reads as an unimplemented endpoint when the real cause was the missing field). Unlike `response`, the `request` is never truncated, with one narrow exception: a single very long opaque value such as a base64 attachment blob may be shortened to a clearly marked placeholder (for example `"<base64, 1024 chars>"`) as long as the field itself and every sibling field remain present. Omit the whole field only when `tool` is `null` or the call genuinely sends no arguments. The renderer pretty-prints it inside a collapsed **Request** section under the flow entry so a reader can replay the call.
	- `response` — the JSON body returned by the tool, captured verbatim as a JSON object. Omit when `tool` is `null`. For a response whose payload is large (a page of hundreds of items, an export blob), keep the top-level structure but truncate arrays with a `"...truncated (N items)..."` placeholder so the report stays scannable; never paraphrase the error or schema information, which is exactly what the reader needs to see. The renderer pretty-prints it inside a collapsed **Response** section under the flow entry.
	- `defect` — present only on `outcome: "issue"` entries; absent everywhere else. Describes the MCP defect this step surfaced and the fix(es). Be specific about *why* it is a defect, never just that something failed: say what about the response was the actual problem (not "got a 400" but "the error named no valid scope, so the user must guess which scopes the tool set accepts"). The renderer pretty-prints it inside a collapsed **Defect** section under Request and Response. Fields:
		- `tag` — one tag from the roadblock taxonomy above.
		- `description` — one or two sentences explaining the defect.
		- `alternatives` — array of solution objects (described under **Solutions** below), mutually exclusive; every defect needs at least one entry. One entry renders as "Fix"; more than one renders as "Alternative fixes — pick one".
		- `additional` — array of complementary solution objects that apply alongside the chosen alternative. Renders as "Also apply — alongside the fix above". Leave as `[]` when there are none.

	**One flow entry per MCP call.** A `getToolSets` to find a candidate, a `getToolSummaries` to drill down, a `getTool` to fetch the schema, and an `invokeTool` to execute land as four separate entries — the value of the report is in watching the MCP get navigated step by step, not in a summary of the navigation. Keep each `result` short (usually one sentence) so a long case stays scannable. A retry with a different tool, a fall-back to a read to isolate the layer, a give-up decision after the budget is spent — each gets its own entry. The number of `outcome: "issue"` entries must equal `issuesUsed`.

	A discovery call has `outcome: "note"`; the `result` says what the call returned that pushed the next step:

	```json
	{
	  "tool": "getToolSets",
	  "intent": "Find a tool set that exposes **object definition** create operations",
	  "result": "Returned **47 tool sets**; `object-admin-v1.0` is the only candidate whose name mentions objects.",
	  "outcome": "note",
	  "response": {"toolSets": ["...truncated (47 items)..."]}
	}

	```

	An `invokeTool` call has one of `ok`, `issue`, or `blocked`. An `issue` example, with its `defect` attached:

	```json
	{
	  "tool": "object-admin-v1.0/postObjectDefinition",
	  "intent": "Create the **Conference** object definition with a schema-valid body",
	  "result": "**HTTP 415 Unsupported Media Type** before any field validation.",
	  "outcome": "issue",
	  "request": {"name": "Conference", "label": {"en_US": "Conference"}, "objectFields": [{"name": "name", "businessType": "Text", "required": true}]},
	  "response": {"status": 415, "title": "Unsupported Media Type"},
	  "defect": {
	    "tag": "mcp-wrapper-bug",
	    "description": "The wrapper rejected the call with **415** before forwarding to the resource, even though the schema documents `application/json` as the only accepted media type. The caller has no way to override Content-Type, so the surface contradicts the schema.",
	    "alternatives": [
	      {"title": "Inject `Content-Type: application/json` in `invokeTool`", "surface": "mcp-wrapper", "detail": "The wrapper should set Content-Type from the OpenAPI operation's request body content type instead of leaving it unset."}
	    ],
	    "additional": []
	  }
	}

	```

- **happyPathNote** — for a clean success, one short observation worth keeping (e.g. that a friendly key worked, or that pagination mapped cleanly). Set it to `null` whenever any flow entry carries a `defect`.
- **achievable** — the counterpart to `happyPathNote` for a threshold **FAIL**: when `issuesUsed > 3` but you still drove the **primary objective** to success through the MCP, set this to one explicit sentence saying so (e.g. **Completed end-to-end through the MCP after 5 issues** — the operation is possible, just costly). Set it to `null` whenever the primary objective remained unmet, so a `null` here means the case truly could not be finished through the MCP — which is the only kind of FAIL that is not merely about cost.
- **Inline emphasis** — the `intent`, `result`, `description`, `detail`, `happyPathNote`, and `achievable` text render lightweight inline markup: wrap a phrase in `**double asterisks**` for bold and in `` `backticks` `` for code. Bold the one phrase that carries the point — the actual problem, the verdict-driving outcome — so the reader is not parsing a wall of even-weight prose. Do not bold whole sentences, and keep each text field to one or two crisp sentences rather than a paragraph.

**Solutions.** Each entry in `defect.alternatives` and `defect.additional` is an object with `title`, `surface`, `detail`, and an optional `diff`. The `surface` selects where the fix lives, and the renderer color-codes it:

- **`openapi`** — fix lives in a `rest-openapi.yaml` or its annotations / `EntityModel`. Prefer this whenever the spec can express the fix; most defects translate into spec edits that ripple through `getToolSets`, `getToolSummaries`, and `getTool` for free.
- **`resource-impl`** — fix lives in a `*ResourceImpl` Java class.
- **`mcp-wrapper`** — fix lives in `mcp-server` or `mcp-server-rest-impl`.
- **`external`** — fix lives outside Liferay.

`detail` states the concrete change in one or two sentences. `diff` is optional but encouraged when the fix is a small, nameable patch: a real unified diff (`--- a/...`, `+++ b/...`, `@@`, `+`/`-` lines) that the renderer syntax-highlights. Omit `diff` entirely when the change is too diffuse to patch in a few lines.

Anti-patterns in `description` and `detail`:

- "The tool was hard to find." Say *why*: "Tool set `X` has an empty description and a misleading name (`cms-*` implies CMS-wide reach but only accepts asset library scopes)."
- "Got a 400." Say *what about the response was the actual problem*: "The error `Group ID 20127 is not valid for scope 'depot'` did not indicate which scopes the tool set accepts; the user has to infer it from the error."
- "The case is complex." Say *which step* is the friction: "The case completes in three calls, but step 2 (`publish`) is undocumented — nothing in step 1's response mentions it is required."

# Conduct

- The report is about what got in the way, not a transcript. The `flow` field carries the timeline as one entry per MCP call (see **One flow entry per MCP call** above); each `outcome: "issue"` entry carries its own `defect` with the why and the fix(es); `happyPathNote` captures keepers from clean runs. Keep each entry's `result` short rather than narrating internal deliberation, and do not restate the `intent` or `result` text inside `defect.description` — the defect should add what the entry does not already say.
- Retry through the MCP as many times as the task needs, but never retry a tool with the *same* input hoping for a different result. Each retry must change something — a different tool set, scope key, or body shape — and the change is itself a finding. Exhaust these MCP avenues before recording a step as impossible; giving up while an untried MCP path remains is a reporting error, not a finding.
- Capture the `request` for a call the moment you invoke the tool, and record the complete arguments exactly as sent (see the `request` field rules above). A flow entry whose `request` is missing fields is worse than one with no `request` at all, because it points the reader at the wrong root cause: a write that failed for a missing required field reads as a broken endpoint when the body was simply incomplete. When in doubt about whether a failure was the surface or the payload, replay the call with a complete, valid body before settling the `defect`.
- Do not read prior memory entries about Liferay endpoints. The evaluation must reflect cold-start discoverability.

# Case to Evaluate

<<CASE_TEXT>>
```