# Agent stack map

One web page that explains how the agent setup fits together: dotfiles, the coordinator, agent-kit and Loop Engine, the seats and models, the providers, and how a piece of work moves through them. It is built from the `origin/main` of the four repositories, so it is only as old as the last run.

## Run it

```sh
python3 ~/.local/user_scripts/stack_map.py --fetch --out stack-map.html
```

From a dotfiles checkout, run `python3 dot_local/user_scripts/executable_stack_map.py` instead (the script installs as `stack_map.py` on the personal profile only).

- `--fetch` runs `git fetch origin main` in each repository first. Without it the page shows whatever `origin/main` each checkout last fetched.
- `--repos-root DIR` is the folder holding the four repositories (default `~/git`).
- `--content FILE` reads the text from a file instead of `docs/stack-map/content.md` at dotfiles `origin/main`. Use it to try an edit before it is merged.
- `--facts-json` prints the facts it parsed (seats, pins, providers and so on) as JSON, for diffing between runs. With no `--out` it writes no page.

The page is one self-contained file: inline styles, inline diagrams, no scripts, no network. The same commits always give the same bytes. Each run adds one line to `~/.local/state/stack-map/log.jsonl` (`$STACK_MAP_LOG` overrides the path).

## Change the text

The plain-English text is `docs/stack-map/content.md`. It needs these `##` sections (the generator finds each by words in its heading): *Start here*, *The one-minute picture*, something with *repo* in it for the per-repository notes, *How a piece of work moves* (holds the flow block), *Where do I change X?* and *Glossary*. Any other `##` section is shown before the glossary, with its own anchor and a chip in the top nav.

Two things in it are checked against the code:

- **Citations**: `[[repo:path|snippet]]`. `path` at that repository's `origin/main` must have exactly one line that contains `snippet` (a short literal, not a paraphrase). The generator finds that line itself, so a line that moves does not break the build; there is no line number to keep. A snippet that is on no line, or on more than one, fails (lengthen it until one line matches). The old `[[repo:path:LINE|snippet]]` form fails with the fix named. A citation shows as a small link to the file at that commit, at the line found. Write the citation after the sentence it supports. A snippet cannot contain `]]`.
- **The flow**: a ```` ```flow ```` block, one step per line: `1. Actor | what happens [[repo:path|snippet]] | where`. Each step must carry a checked citation, so the diagram cannot keep saying something the code stopped saying. The where column is `repo:path` (the path must exist) or a command. It is drawn as the step diagram.

Everything else is ordinary markdown: headings, paragraphs, lists, tables, `**bold**`, `` `code` ``, links.

## When it fails

It exits 1, writes nothing, and prints one line per problem as `repo:path:line: reason`. Line 0 means no particular line.

| Line says | What happened | Fix |
|---|---|---|
| `...:path:0: missing at origin/main` | a file a fact is read from moved or was deleted | change where the generator reads it (`extract_*` in the script), or restore the file |
| `...: no CREATE TABLE statements found` (or any `no ... found`) | the file is there but its shape changed, so a fact came back empty | update that extractor to the new shape; never let it print a blank |
| `repo:path:0: snippet '...' is not in the file ... (content.md line N)` | a citation is out of date: the cited text changed or left the file | find the line that now backs the claim and put its text in the snippet in `content.md` |
| `dotfiles:docs/stack-map/content.md:N: says where something sits on the page (...)` | the text uses a word of position ("above", "below", "further down", "earlier on this page") outside code and citations, but the generator decides the page order | name the section instead, for example: the tables under "Facts read from the files" |
| `dotfiles:docs/stack-map/content.md:0: no ## section for ...` | a required section is missing or renamed | restore the heading (see the list above) |
| `...: flow step N names a path missing` | the flow points at a file that is gone | fix the path |
| `dotfiles:docs/stack-map/content.md:N: citation names a line number` | a citation is in the old `[[repo:path:LINE\|snippet]]` form | drop the `:LINE`; the snippet alone finds the line |
| `repo:path:N: snippet '...' is on K lines (...): lengthen it` | the snippet matches more than one line, so it does not say which line backs the claim | make the snippet longer until one line matches |
| `...: flow step N makes a claim with no checked citation` | a diagram step has no `[[repo:path\|snippet]]` | add one from the line that backs the step |
| `...: git fetch origin main failed` | no network, or the remote is unreachable | rerun when it is |

A version mismatch between pins is not a failure: the page flags it in red.

## Tests

`python3 -m unittest discover -s tests/stack-map -v`. They build four small scratch repositories and run the real script against them.
