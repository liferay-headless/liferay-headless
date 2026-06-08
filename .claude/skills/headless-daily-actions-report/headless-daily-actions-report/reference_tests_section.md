# Testing Panel Baseline

Persistent reference for Testing Panel counts. Updated after each run where numeric counts are available. Survives sprint transitions — do not reset this file when starting a new sprint, only update it when new counts are fetched.

## Current Baseline
```json
{
  "date": "2026-06-02",
  "investigation": 101,
  "acceptance": 18,
  "all_bugs": 183,
  "fp4_fp5": 2,
  "no_fp": 10
}
```

## Sources
- Investigation → Testray whole run, latest [master] ci:test:headless build — **Failed** count
  Routine: `https://testray.liferay.com/web/testray#/project/35392/routines/994140`
- Acceptance → Testray acceptance build, latest EE Development Acceptance (master), filtered by Headless team — **Failed** count
  Routine: `https://testray.liferay.com/web/testray#/project/35392/routines/994140`
- All bugs → `https://liferay.atlassian.net/issues/?filter=15065`
- FP4/FP5 → `https://liferay.atlassian.net/issues/?filter=45383`
- No FP → `https://liferay.atlassian.net/issues/?filter=45384`

## How to fetch
- **Investigation & Acceptance**: Navigate to each Testray build page via Chrome MCP, take a screenshot, read the Failed count from the "Total test cases" chart.
- **All bugs, FP4/FP5, No FP**: Browser JS fetch from a liferay.atlassian.net tab (see SESSION_PROMPTS.md Step 4).

## API Note
The Jira REST API `/rest/api/3/search/jql` POST endpoint may or may not return a `total` field. The skill uses a multi-method fallback: POST with maxResults=0, then GET with maxResults=0. If both fail, `N/A (–)` is shown and the baseline is not updated. Baselines from 2026-05-18 were set manually from the published Confluence page.
