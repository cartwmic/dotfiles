---
name: searching-with-qmd
description: Search Michael's notes, repo docs, Pi session recaps and past Pi, Claude Code and Codex sessions with QMD (local keyword plus semantic search). Use to find what was written, designed or discussed before. Not for searching source code.
---

QMD indexes markdown: scratch notes (`notes`: `*/*.md` in the agent scratch folder, which is `$AGENT_TMP` on the personal Mac and `~/tmp` on the work Mac; `notes-internal`: `~/tmp/*/*.md` not yet moved there, personal Mac only, so use `-c notes -c notes-internal` there), repo docs (`repo-*`), Pi sessions (`sessions`), Claude Code sessions (`claude-sessions`) and Codex sessions (`codex-sessions`), one file per session with user and assistant text only, and session recaps (`recaps`). Decisions and conventions: ask Hindsight first. Use QMD to find documents and sessions.

**Semantic, the default:** `qmd query "plain-language question"`
- Slow and heavy: **5-28 s and 1-5 GB of RAM** per call (every call loads three models afresh). This Mac is short on memory.
- **Never run it in parallel, in a loop, or from several subagents at once.** One call, read the answer, then decide. Do not retry because it is slow.

**Keyword, when speed matters or you know the exact words:** `qmd search "heavy-gate sync"`
- 0.2-1 s, about 150 MB, no models. Good for names, identifiers and error strings. Every word must match, so use two or three distinctive ones. Cheap enough to repeat with different words.

T3 sessions: heading = thread title. `## ownerturn` marks Michael's turns, `## agentturn` agents'. Find his: `qmd search ownerturn`.

Both take `-n 5` (result count) and `-c sessions` (one collection; repeat `-c` for several; names above). Results show `qmd://collection/path`, a `#docid` and a score.

**Read a hit:** `qmd get "#docid"` or `qmd get qmd://sessions/2026-10-26/<id>.md`. A session file is a text-only copy; its frontmatter has the session id and cwd, so look up the full `.jsonl` if you need tool output: `~/.pi/agent/sessions`, `~/.claude/projects/<cwd with / as ->/<id>.jsonl` (a Claude sub-agent file is named `<id>-agent-<x>.md` and lives under `<id>/subagents/`) or `~/.codex/sessions/<yyyy>/<mm>/<dd>/rollout-*-<id>.jsonl`.

Do not run `qmd update`, `qmd embed`, `qmd pull` or `qmd mcp`. Refreshing the index is the owner's job: run `qmd-refresh` only if they ask (long and heavy; it queues behind heavy-gate). `qmd-refresh status` says when it last finished. If hits look stale, say so rather than fixing it. Sessions and recaps appear only once the owner has built that part of the index.
