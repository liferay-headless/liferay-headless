# Rating calibration

Every node except the evidence leaves carries a grade, against the row that matches the member's role (from `rules/team.md`). Four levels: **Below**, **Meets**, **Exceeds**, **Exceeds + enables others**. The headline rating has no "Below" tier.

## Capacity normalization (FTE)

The roster (`rules/team.md`) carries an **FTE** per member — their capacity, where `1.0` is full-time. Grades are **role-relative**, and capacity is part of that judgment: a member at `0.75` FTE has ~75% of a full-timer's hours, so volume-sensitive expectations scale to their capacity. Someone who ships in proportion to their FTE clears the **same grade tier** as a full-timer who shipped the full amount — and a part-timer who matches a full-timer's raw output is doing *more* than expected, which can lift the grade. Apply this whenever the bar is about *how much* was done: the Delivery grade, the volume side of PR-Reviews and LPP, the per-`work_item` grades, and the headline synthesis.

This touches **grades, not magnitude scores.** A volume `score` is the absolute, org-wide magnitude of what was actually produced (it drives the radar geometry) and stays as-is regardless of FTE — a 0.75-FTE engineer genuinely shipped fewer absolute tickets, and the radar should show that honestly. Capacity is reflected in the role-relative *grade*, not by rescaling the volume score.

**The one exception is Speed.** Its score is computed from wall-clock time-to-land, which a part-timer's off-days mechanically inflate — so there capacity is corrected *in the score itself*, by deflating the median by `fte` before scoring (see `speed/AGENT.md`). That is a latency artifact, not a magnitude judgment. Brian's rejection rate is genuinely capacity-neutral (a rejection is a rejection regardless of hours) and is left alone. When FTE `< 1.0` changes how you read a node, say so in that node's `text`.

### Associate Software Engineer

- **Below expectations.** Slips routine tickets despite mentorship; landed code regresses in review; needs hand-holding for ordinary work.
- **Meets expectations.** Closes assigned bug tickets and small technical tasks with normal review feedback; absorbs guidance and applies it.
- **Exceeds expectations.** Ships modest features independently; picks up adjacent issues without prompting; raises code quality bar for own work.
- **Exceeds + enables others.** Authors reusable docs, fixtures, or onboarding artifacts the next associate inherits — rare at this level.

### Mid Software Engineer

- **Below expectations.** Routine domain work needs senior rescue; commitments slip without flagging; customer bugs sit untouched.
- **Meets expectations.** Owns features and customer bug fixes end-to-end within an established domain; backports cleanly; gives review feedback.
- **Exceeds expectations.** Drives multi-ticket arcs; shapes design within the domain; takes on customer-blocking or critical-priority work.
- **Exceeds + enables others.** Builds shared tooling, conventions, or mentorship that lifts the team's mid-level cohort and reduces senior load.

### Senior Software Engineer

- **Below expectations.** Stays at mid-level scope; avoids cross-cutting work; defers architecture calls to others.
- **Meets expectations.** Owns major features end-to-end; debugs hard issues independently; makes sound architecture calls in their domain.
- **Exceeds expectations.** Leads multi-team initiatives; runs firefights; shapes technical direction across the domain; mentors mids.
- **Exceeds + enables others.** Builds APIs/platforms other teams adopt; sets reusable patterns; raises the bar for the senior cohort.

### Staff Software Engineer

- **Below expectations.** Operates at senior scope without broadening influence; doesn't shape decisions outside immediate team.
- **Meets expectations.** Drives multi-product initiatives; owns hardest problems; shapes cross-team architecture; influences other senior+ engineers.
- **Exceeds expectations.** Defines engineering strategy for product areas; lands platform-level wins visible across the org.
- **Exceeds + enables others.** Builds capabilities other Staff engineers and teams compound on; sets cross-org standards; force-multiplies the engineering function.

### Team Lead

- **Below expectations.** Personal IC work without team uplift; team blocked, unbalanced, or unclear on priorities.
- **Meets expectations.** Ships personal work AND unblocks the team; runs planning, reviews, and quality; closes the loop on commitments.
- **Exceeds expectations.** Drives team-wide outcomes; owns product quality and roadmap execution; absorbs firefighting without dropping plan work.
- **Exceeds + enables others.** Builds capabilities other Liferay teams adopt; force-multiplies the engineering org beyond the team's headcount.
