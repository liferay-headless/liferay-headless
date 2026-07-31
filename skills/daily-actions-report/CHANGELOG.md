# Changelog — headless-daily-actions-report

Version numbers were introduced in **2.0.0** (2026-07-28). Everything before
that shipped without a version string, so the entries below map each dated
fix — already documented in detail in the individual `CHANGELOG-fixes-*.md`
files — onto an informal version number, oldest first. Going forward, bump
`SKILL_VERSION` (set at the top of `headless_daily_report.py`,
`assemble_jira_data.py`, and `assemble_slack_data.py`) and add an entry here
on every change, however small. The dated files remain in the skill folder
for the full forensic detail (root cause, symptom, exact fix) behind each
entry — this file is the fast "what changed and when" index.

## 2.1.1 — 2026-07-31

A routine run in a fresh, sandboxed Cowork session (no prior local state)
surfaced two structural bugs — both fixed same-day. Full writeup with
symptoms and root causes in `CHANGELOG-fixes-2026-07-31.md`; short version:

- **`assemble_slack_data.py` never got the 2026-07-29 blank-line parser fix.**
  `load_sprint_context()` in `headless_daily_report.py` was patched
  2026-07-29 to tolerate a blank line between a `## Section Name` heading
  and its ` ```json ` fence. `assemble_slack_data.py` has its own duplicated
  copy of this parsing logic (`_read_md_json_section()` /
  `_write_md_json_section()`) and was still on the old, strict regex — so a
  page that's been through one Confluence round-trip (i.e. every page, every
  run) silently returned an empty `Team Slack Names` roster to the Slack
  classifier, misclassifying every answered thread as unanswered. Caused a
  real false-positive on 2026-07-31 (a 19-reply and a 5-reply thread, both
  with genuine team replies, both flagged unanswered). **Fixed:** both
  regexes now match `\n+` instead of a literal `\n`, identical in spirit to
  the 2026-07-29 fix, just finally applied to this file too.
- **`headless_daily_report.py`'s output files defaulted to the skill's own
  (often read-only) folder.** `OUTPUT_DIR = Path(__file__).parent` failed
  with a read-only filesystem error in any sandboxed session where the skill
  is mounted read-only (every Cowork session) — affected the HTML preview,
  `adf_output.json`, and every publish snippet. **Fixed:** new `--output-dir`
  CLI flag overrides `OUTPUT_DIR`; defaults to the old behavior if omitted,
  so standalone/local use is unaffected. This replaces the previous
  workaround (copying the whole skill folder to a writable scratch
  directory before running anything) entirely.
- All three scripts (`headless_daily_report.py`, `assemble_jira_data.py`,
  `assemble_slack_data.py`) bumped to `SKILL_VERSION = "2.1.1"` in lockstep.

## 2.1.0 — 2026-07-29

The first real run against the new 2.0.0 shared-context storage, and it
surfaced a fragile parser plus a couple of process gaps. See
`CHANGELOG-fixes-2026-07-29.md` for the full six-part writeup; short version:

- **Parser hardening.** `load_sprint_context()`'s section regex only matched
  a heading immediately followed by its ` ```json ` fence — a blank line in
  between (which Confluence's own markdown round-trip introduces routinely)
  made every roster and cache silently parse as empty, with no error. Now
  tolerates blank lines, and raises loudly if fences are present but nothing
  parsed. This was the root cause behind three of the four review rounds
  today, so it's the highest-value fix in this release.
- **Approved-PR routing changed (behavior change, per Nóra).** An approved
  PR attached to a rendering Section 1 issue now shows under that issue's
  Action column instead of always appearing separately in Pick Up Next.
- **Process, not code:** PR→parent resolution and roster completeness both
  turned out to be "the script/data will handle it" assumptions that don't
  hold up in practice — documented explicitly in SKILL.md as mandatory
  Claude-side steps rather than left implicit.
- `context_page_id` for the ENGHEADLESS shared context page is now recorded
  directly in SKILL.md (5190975505) — the one-time bootstrap is done.

## 2.0.0 — 2026-07-28

**Shared context storage.** Sprint Metadata, both rosters, and the four
run-to-run caches (Changelog Cache, State Snapshot, PR Snapshot, Slack Thread
Snapshot) moved from a local `project_current_sprint.md` file inside the
skill's own install — which only the machine that installed the skill could
see or update — onto a single shared Confluence page that every teammate's
session reads and writes via the Atlassian MCP. Triggered by two real
failures on 2026-07-28: a teammate covering during PTO would only ever see
whatever cache happened to be on their own machine, and a sandboxed/read-only
session could build a correct report but silently fail to persist the cache
update anywhere. See SKILL.md § Shared Context Storage for the full design,
the one-time bootstrap, and the permanent context page policy.

- `headless_daily_report.py`: new `--sprint-context-file` flag overriding the
  previously-hardcoded local path (defaults to the old path, so the script
  still runs standalone without the flag); `SprintContext` gained
  `latest_skill_version`; `save_sprint_context()` now also patches that key
  into the Sprint Metadata block.
- `assemble_slack_data.py`: no code change needed — `--sprint-context` was
  already a CLI flag; just point it at the synced scratch copy instead of
  the local skill file.
- `assemble_jira_data.py`: unaffected by the context-storage change (it
  never read `project_current_sprint.md`).

**Versioning.** All three scripts now carry a `SKILL_VERSION` constant,
printed at the start of every run. `headless_daily_report.py` compares its
own version against `latest_skill_version` on the shared context page (see
above) and prints a loud, non-blocking console warning if it's behind
whatever last successfully published — so "is everyone on the latest
version?" is answerable by reading one Confluence page instead of asking
around. `SKILL.md` now carries a `Skill Version` line and a matching
`version:` field in its frontmatter.

## Pre-versioning history (informal version numbers)

| Ver (informal) | Date | Summary | Detail |
|---|---|---|---|
| 1.1.0 | 2026-07-02 | Sprint-query completeness guard — a truncated MCP page falsely marked `hasNextPage=false` silently dropped LPP-64669; added the `--expected-count` completeness check in `assemble_jira_data.py`. | `CHANGELOG-fixes-2026-07-02.md` |
| 1.2.0 | 2026-07-06 | Section tables now carry explicit `colwidth` so Confluence stops resetting Nóra's manually-tuned column widths on every publish. | `CHANGELOG-fixes-2026-07-06.md` |
| 1.3.0 | 2026-07-08 | Three-part fix day: added the LPP age trigger (7b) so long-running LPPs like LPP-64236 stop falling through Section 1's visibility gate; two follow-up fixes same day; testing-panel delta bug. | `CHANGELOG-fixes-2026-07-08.md` |
| 1.4.0 | 2026-07-09 | Test section became a static Confluence Include Page macro — removed the live Testray scrape and Jira bug-count fetch entirely. | `CHANGELOG-fixes-2026-07-09.md` |
| 1.5.0 | 2026-07-09 | New feature: unanswered `#t-dxp-headless` Slack questions surface at the top of Needs Owner, via Chrome-scraping (no Slack connector available for this org). | `CHANGELOG-fixes-2026-07-09-slack-needs-owner.md` |
| 1.6.0 | 2026-07-10 | Fixed a false "cross-team" flag on a genuine Headless PR — the author was missing from the `Team GitHub Logins` roster, not actually a wrong exclusion rule. | `CHANGELOG-fixes-2026-07-10.md` |
| 1.7.0 | 2026-07-13 | LPD "Days in Progress" now tracks days in the *current* status (not carried over from the development phase) for LPDs past development; plus two related fixes the same day. | `CHANGELOG-fixes-2026-07-13.md` |
| 1.8.0 | 2026-07-15 | Fixed a closed SEV bug appearing in the report from a stale re-used fetch, and BPR-linkage catching backport tickets the saved filter hadn't picked up yet; plus the Slack-scrape-skip incident that went unreported until a team meeting. | `CHANGELOG-fixes-2026-07-15.md` |
| 1.9.0 | 2026-07-08 to 2026-07-15 (various) | Everything else folded into the dated files above but not called out as its own headline item (minor exclusion-rule tightenings, PTR ownership rule, etc.) — see the dated files and SKILL.md's inline "2026-0X-XX fix" notes throughout the Workflow/Deduplication sections. | various |

## Format going forward

```
## X.Y.Z - YYYY-MM-DD
One-paragraph summary of what changed and why (symptom -> root cause -> fix,
same spirit as the dated CHANGELOG-fixes-*.md files). Bullet the concrete
code/doc changes if there's more than one.
```

Bump the patch version (`X.Y.Z+1`) for a bug fix, minor (`X.Y+1.0`) for a new
feature or non-breaking behavior change, major (`X+1.0.0`) for anything that
changes the on-disk data format or breaks compatibility with an older copy of
the skill (like this 2.0.0 release does for the context-storage location).
