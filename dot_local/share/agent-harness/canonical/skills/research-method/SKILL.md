---
name: research-method
description: Use when asked to research a question from outside sources (web, docs, papers, pricing pages, repos) and report what was found. Covers scoping, finding sources, quoting the exact extract for each claim, when to stop, a "could not find" section, a five-claim spot check by a fresh reader, and a fan-out recipe for broad questions. Not for searching local notes (searching-with-qmd).
---

# Research method

Method only. It does not drive Loop Engine.

## 1. Scope first

Before searching, write down:
- the question in one sentence, and who will use the answer;
- what a complete answer must contain (3 to 7 sub-questions);
- what is out of scope.

If two readings of the question would give different answers, ask once. If you cannot ask, pick one, say which in the report.

## 2. Find sources

- Prefer primary sources: official docs, the paper, the source code, the pricing API, the author's own post. Use summaries and blogs to find primary sources, not as the evidence.
- Open every page you cite. A search snippet is not a source.
- A fetch tool that summarises (WebFetch and similar) gives you a model's paraphrase, not the page. Take extracts from raw text: `curl` the page or raw file, or convert the PDF, then grep for the extract.
- Note each source's date. Say when a page is old for the question.
- Search each open sub-question with more than one wording. Search once for the opposite of what you expect to find.
- Give each source an id (S1, S2, ...) with URL, the page's own publish or update date (or "undated"), and type: primary, secondary or opinion.

## 3. Quote the extract

Every claim in the report carries the source id, the **verbatim extract** (copied, short) and a **locator** (heading, section, page, line, anchor or API field) a reader can open.
- Copy numbers, names and versions from the raw page. Never from memory or a summary.
- If you cannot quote it, it is not a finding. Move it to "could not find or check", or label it a guess.
- Never cite a source you did not open.
- Save the raw text you took each extract from (the fetched page, file or PDF text) in a folder next to the report, named by source id, so the extracts can be checked again later.

## 4. Coverage and stopping

- Coverage: every sub-question has a primary source, or sits in "could not find or check". A material claim needs one primary source or two independent ones. A contested claim needs the counterevidence you looked for and what you found.
- Stop when every sub-question meets coverage, or two more searches on an open sub-question add nothing. Do not stop at the first plausible answer. Do not keep going for completeness.

## 5. Report

1. **Answer** in 2 to 5 lines, with your confidence and why.
2. **Findings**: one row per claim: claim | source id | extract | locator.
3. **Conflicts and counter-search**: where sources disagree, and which you trust and why. Name the counter-search you ran (the queries for the opposite) and what it returned. If you ran none, say so.
4. **What I could not find or check**: required in every report, never empty. List pages that would not load, sub-questions with no primary source, numbers you could not confirm, anything you inferred. If nothing, say what you did to be sure.
5. **Sources**: the id list.
6. **Spot check** result (below).

## 6. Spot check before the report goes out

Freeze the report, then hand it whole, and nothing else, to a fresh reader: a new subagent or session with no access to your notes. Do not choose the claims for it or give it a shortlist: the reader picks five (the ones that carry the answer, numbers first), opens each source at the locator, and returns for each: extract found there verbatim, yes or no; claim supported by it, yes or no. One failure: fix every claim from that source, then run a new five. Put the result in the report as "Spot check: 5 of N claims, chosen by the reader", with what failed and was fixed. Do not write "5 of 5 confirmed" if a part of an extract could not be matched. Claims you add or change after the check were not checked: say so, or run it again. With five claims or fewer, check all of them. If you cannot start a fresh reader, re-open the sources yourself at the end and say so.

## 7. Fan-out for broad questions

Use when the question has four or more independent sub-questions, or no one source can cover it.
1. Split into sub-questions that do not depend on each other.
2. Start one read-only subagent per sub-question. Brief each with: its sub-question, the source and extract rules (sections 2 and 3), the required "could not find or check" list, and "return the findings table, not conclusions". Run them in parallel.
3. You merge. Build a sub-question by source grid, mark gaps, send a follow-up for each gap or stop under section 4. Resolve conflicts yourself.
4. You write the report and run the spot check. Do not pass subagent summaries through unchecked.
