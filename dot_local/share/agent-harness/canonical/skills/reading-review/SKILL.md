---
name: reading-review
description: Use when asked to read, summarize or explore an article, paper, report, repo, spec or other source for Michael's review. Produces one viz page in four parts (what it is, what stands out, implications at every scale, then his setup) and a short report. Read-only.
---

# Reading review

Give Michael a report he can judge the source from. The source comes first. His own setup is one section near the end.

## Scope

- Read only. Change nothing in any repo.
- Fetch and read every source in full. If a fetch fails or a file cannot be parsed, say so. Do not guess at content.
- Mark each claim as **Source** (the document says it) or **Inferred** (your reading). Part 1 is mostly Source. Parts 2 to 4 are mostly Inferred, so tag the claims where the line is not obvious.
- Write plain English (the `no-ai-slop` skill). Do not add security or privacy commentary on your own. If a real risk matters, give it one line as "to consider".

## The four parts

Use this order on the page. Give each its own heading.

1. **What it is.** A plain account of the thing in its own right: what it says or contains, how it works, where it comes from (author, date, context, evidence behind it). For a long list-like source such as a radar or changelog, group the items and pull out what matters most. Put the full list in an appendix.
2. **What stands out.** What is novel, clever, useful or unusual about it, and how it compares with what already exists. Name the prior art you compared against and say how far it matches. If it is weak or old news, say so.
3. **Implications at every scale.** What could follow, big and small, broad and niche: for the industry, for practice, for tooling and for people who would never use it directly. Include things to watch and things that do not matter.
4. **Then his setup.** How it bears on Michael's own work, as one section among several. Keep it shorter than parts 1 to 3 together. Name concrete ideas worth trying or watching, and say plainly where something does not apply. Before you claim anything about his setup, read the file or command that shows it, and list what you did not check. His setup is the coordinator with leads, workers and reviewers, Loop Engine and lean-change runs, review gates, agent-kit, kgate, the homelab Kubernetes cluster, the dashboard and the board.

Open the page with a one-line verdict and, if there is one, a top recommendation.

## Output

1. **One viz page** (the `using-viz` skill). Write self-contained HTML in a scratch directory (not in a repo), run `viz publish <file> --as html`, then open the `url` once and confirm it loads and renders.
2. **A Review item**, when you work under Michael's coordinator. The first line of its TickTick content is the viz URL, then a one-line verdict. Research results become Review items that are never auto-closed. Create it with
   `coordinator board write ticktick create <Personal list id> --title "Review: <title>" --content=<url + verdict> --grant 13 --why R --event E`.
   The list id is in `<board_dir>/config.json` under `trackers.ticktick.list.id`. The CLI is `coordinator` (or `src/coordinatord/cli.ts` in the coordinator repo), never `main.ts`, which starts a second daemon. A real write needs an event id from the coordinator. If you lack one or the write fails, send the coordinator the URL, the verdict and the command, and do not invent an id. Run a `create` once; a repeat makes a duplicate task. To change a Review item's link later, use `ticktick set-content "TT <id>" --content TEXT`, which replaces the whole content, so keep the other lines.
3. **A short report** to whoever asked: the URL, three to five key takeaways and your top recommendation, if any. Say what you saw working and what you only assumed.

Outside the coordinator, steps 1 and 3 are the whole job.

## Reworking an existing review

If asked to redo a report in this shape, keep the same facts, move the setup material into part 4, add the missing parts 2 and 3, and publish the new page. If the URL changes, update the Review item's link.
