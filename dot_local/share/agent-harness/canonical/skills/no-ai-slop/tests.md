# no-ai-slop skill tests

Not linked from SKILL.md. Agents never load this file. It records the cases used to verify changes to the skill.

## Protocol

Run before and after every change to SKILL.md, eval.md, voice-profile.md, or voice-excerpts.md. Use the same model and the same N both times. The runner is source-only (`tests/no-ai-slop/run.py` in the chezmoi repo):

```sh
python3 tests/no-ai-slop/run.py SKILL_DIR OUT_DIR 5 anthropic/claude-opus-5-5
```

It inlines the four skill files into a tool-less `pi -p` prompt, runs each case N times, and applies regex checks to the output. Checks are probabilistic. Compare pass counts per check. A change that lowers any count needs a stated reason. Raw outputs stay in OUT_DIR; read a few, since a regex can fail compliant output.

Add the owner's flagged sentences from `no-ai-slop-dogfooding.md` as Detect cases when they are not yet covered.

## Cases

| Case | Mode | Request | Input | Pass |
|---|---|---|---|---|
| T1e | Edit | remove AI-slop patterns | "Here's the thing: the cache layer exists to cut read latency for the dashboard." / "The retry policy is about protecting downstream services, not about hiding errors. It runs three attempts with 200 ms backoff." | No `, not` or other contrast template in the edited text; "three attempts" and "200 ms" kept; the report lists the retry hit on a contrast-scan line |
| T1d | Detect | audit, do not rewrite | same as T1e | Findings flag the retry sentence as Binary contrast templates |
| T2 | Edit | repair this generated draft of my explainer | "It's worth noting that the deletion flow spans ServiceA and ServiceB. ServiceB handles the deletion queue via a cronjob." | A line `Voice: profile loaded; register: systems explainer`; ServiceA and ServiceB kept |
| T3 | Edit | tighten my design doc | "Per RFC 9110 §15.5.5, the service returns 404 for unknown IDs. Signal classification: each response is labelled grounded or ungrounded." | Citation and the label colon kept, or "No material edit needed" |
| T4 | Edit | rewrite this generated draft in my opinion voice | "Codex is a powerful tool. It truly streamlines planning. Many developers find it transformative for their workflow." | No contrast template; no added source or number |
| T5 | Edit | remove AI-slop patterns | T1e input plus "The job runs nightly at 02:00 UTC." | Report has a portability line stating 3 paragraphs examined, and at least 10 pass/fail/not run statuses |
| T6 | Edit | remove AI-slop patterns | "Our new caching layer is a pivotal, transformative improvement for the platform." | "pivotal" and "transformative" removed; no metric, number, or mechanism added |
| T7 | Detect | audit, do not rewrite | "In today's world, observability is pivotal. It's not about dashboards, it's about answers. Every team needs alerts." | Labels are exactly Throat clearing, Importance puffery, Binary contrast templates, Maxims and counterfactuals, in that order, identical across runs |

## Known limits

- Detect on the owner's own bullet 5 sentence ("the reality is any time we don't spend on our zbb items is of course time lost from that work") still flags it as a faux-insight setup. The owner has not ruled on it.
- The tests do not cover Edit mode on long documents, other models, or whether the output reads as the owner's voice. Only the owner can judge the last one.
