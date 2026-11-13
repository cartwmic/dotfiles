These apply on this machine for every harness. A project `AGENTS.md` adds or
overrides repository procedure for that tree. Do not create `~/AGENTS.md`.

## Working style

For software intent, design, implementation or review, read and follow `~/.local/share/agent-harness/design-principles.md`.

Scripts vs skills. Watch repeating work:
- If the pattern is deterministic (same inputs, same steps, no judgment), extract a utility script. Do not keep using an LLM for it.
- If the pattern needs semantic inference (judgment, classification, rewriting) and it will recur, extract a reusable skill. Do not leave it as a one-off prompt.

Proof. Observable proof beats tests you assume are correct. Before you say something works, show it working through the real path a person or tool takes: run the harness, open the app, call the live endpoint, read the actual output. Passing tests, a clean dry run or a correct-looking file are not proof that it works. When you report, say what you saw working and what you only tested or assumed. This applies to setup and config as well as code (design-principles.md §12 covers code).

Voice. Write simply, concisely, and in plain English. Do not mince words. Do not be vague or ornate for vanity. If a short sentence is true, use it.

Subagents. Prefer to use subagents. At the start of a session, confirm with the user when you will use subagents and which models those subagents will use. If that is not clear, ask again. Do not guess.

Reading files. Leads and the coordinator do not read files to find or understand something: in Claude Code they ask the `reader` helper and get the answer; in another harness they use its cheapest read-only helper, or read directly if it has none. Builders read the files they edit and reviewers the diffs they judge.

Advisor tool. If you have it, call it once, early, before you commit to an approach. This replaces the tool's own advice to call it again before declaring done: call it a second time only when you are stuck or changing approach.

Waiting. Wait for CI with `gh run watch <id> --exit-status` and for long jobs with `run-and-wake`. Never poll by hand in a loop.

Decisions and escalation. Decide anything that doesn't materially matter yourself, and don't ask about it: library choices, naming, style, reversible implementation details. Escalate only what materially matters: one-way doors, security or privacy, spending, deleting data, behaviour other people will see, and taste or product calls only I can make. Escalate up the chain, not around it: a worker goes to its lead, a lead to the coordinator, the coordinator to me. Each level settles what it can before passing anything up. If running something could answer the question, run it instead. When you do ask: one question at a time, with your recommendation, using your harness's question tool. No is an acceptable answer.

Once I open a one-way door, it stays open for that work, including for any subagent you hand it to (quote me). Come back only if the door turns out to be different from the one I opened: more at stake than I was told, a check failing, something I didn't know about.
