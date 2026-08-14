These apply on this machine for every harness. A project `AGENTS.md` adds or
overrides repository procedure for that tree. Do not create `~/AGENTS.md`.

## Working style

YAGNI. Do not add code, abstractions, config, or files the current request does not need. Do not design for a future request that has not been made.

KISS. Prefer the smallest change that works. A function beats a new layer. A script beats a service. Do not add complexity to look clever.

Scripts vs skills. Watch repeating work:
- If the pattern is deterministic (same inputs, same steps, no judgment), extract a utility script. Do not keep using an LLM for it.
- If the pattern needs semantic inference (judgment, classification, rewriting) and it will recur, extract a reusable skill. Do not leave it as a one-off prompt.

Voice. Write simply, concisely, and in plain English. Do not mince words. Do not be vague or ornate for vanity. If a short sentence is true, use it.

Black-box validation. A software change is not shown to work by tests at internal seams. Prove it by driving the same path a user drives, to a completed outcome. Where that path calls an external system, use a dummy or scripted backend unless the test is specifically about that system. Fail closed if the outer path cannot finish. Seam tests may exist; they do not substitute for this proof.
