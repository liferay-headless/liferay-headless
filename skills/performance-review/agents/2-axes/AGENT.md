# Axes Agent

Orchestrate the seven axis evaluations.

Dispatch the seven **in parallel** (one Agent call each, in a single message), handing each its `AGENT.md` + `graph.md` + the run dir `output/<handle>` + `role`:

`agents/2-axes/agents/pr-reviews` · `agents/2-axes/agents/lpp` · `agents/2-axes/agents/testing` · `agents/2-axes/agents/discovery` · `agents/2-axes/agents/speed` · `agents/2-axes/agents/delivery` · `agents/2-axes/agents/brian`

They are independent — all read the same post-group graph, never see each other, and each appends its nodes directly. Confirm all seven returned.
