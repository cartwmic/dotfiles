# Herdr Overview follow-up issues

Recorded 2026-10-02 in cartwmic/dotfiles.

Status: issues captured; recap-preview v1 visually approved by the owner after
viewing it on the daily phone. No software-change run has started. No implementation, live apply, reload, restart, commit or push is
authorized by this brief. Runtime remains stock Herdr 0.9.1 with the managed
Overview plugin.

## OV-1 — Spatial keyboard navigation

**Reported:** arrows should move up/down/sideways; h/j/k/l should do the same.

**Confirmed:** `src/pane.mjs` maps right/down to j and left/up to k.
Only j/k are handled; h/l are ignored. `src/navigation.mjs:movePane`
traverses a flat native-order list, not the displayed card geometry.

**Requested outcome:** collapsed-map Up/k, Down/j, Left/h and Right/l move
in their displayed directions. Reach every pane in singleton grids and
multi-pane groups across wide workspace columns and narrow stacked layouts.
Selection stays visible. Preserve [/] sequential traversal and the established
detail/digest reading controls.

**Future design decisions:** edge/wrap behavior and how movement crosses uneven
rows/workspaces. Do not silently replace detail scrolling with card movement.

**Proof needed:** actual popup keyboard journey at wide and narrow sizes,
including uneven groups, resize, missing panes and exact guarded focus.

## OV-2 — Mouse browsing

**Reported:** support native-like mouse scrolling and pane selection.

**Owner scope, 2026-10-02:** overview browsing only. Wheel scrolls the map or
expanded recap/digest; single click selects a tile. Terminal focus stays a
separate explicit action. Scrolling a live terminal's scrollback and
click-to-focus-and-dismiss are not in scope.

**Confirmed:** `src/pane.mjs` neither enables mouse reporting nor decodes
mouse packets. `src/presenters/map.mjs:renderMap` centers the map viewport
on selection, so wheel-as-j/k would change selection rather than independently
scroll. Click selection needs renderer-owned hit regions, corrected for the
visible viewport and resize.

**Feasibility still open:** cached stock Herdr input code suggests popup mouse
routing, but delivery to the plugin popup PTY is not proven. First drive an
owned isolated Herdr 0.9.1 popup with a dummy mouse-reporting program and
observe real click/wheel bytes and coordinates. No fork/runtime patch is
approved or presumed necessary.

**Proof needed:** wheel browsing without moving selection, exact click targets
after scroll/resize, full recap/digest scrolling, streaming/split mouse packets,
and restoration of terminal input modes on close/error. Preserve the fresh
identity check for any later explicit terminal focus.

## OV-3 — Latest recap preview on collapsed tiles

**Reported:** show a limited latest recap without focusing/selecting a tile.

**Confirmed:** collapsed cards in `src/presenters/map.mjs:card` contain the
title and status only. Full latest-good recap appears in expanded `reading`.

**Mockup candidate:** [recap-preview.html](./recap-preview.html). Synthetic
data; based on the current workspace-column, paired singleton-card and grouped
multi-pane layout. Default is two wrapped lines on every tile, below its
status, with a publication date and truncation ellipsis. Review controls
compare Off/2/3/4 lines and wide/phone layouts. Click selects; Enter reveals
the full recap; Esc collapses. All interactions are browser simulation only.

Latest-good published recap is the only excerpt source. A newer failed attempt
is a separate warning and does not replace it. Missing recap is explicit.
Short recaps need no truncation. No generated summary, terminal tail, supplied
prompt or session digest is substituted. Titles remain stable and separate.

**Owner decision, 2026-10-02:** after initially choosing iteration, the owner
viewed recap-preview v1 in the daily-phone browser through an SSH tunnel and
said “Looks good.” This accepts v1's visual design direction for the future
run, superseding the earlier not-yet-accepted status. The mockup defaults to
two lines; no alternate line budget was explicitly selected in conversation.
Review controls are comparison aids, not promised runtime settings. Visual
approval does not authorize run start, implementation or live deployment.

**Proof already run for the mockup:** Chromium at 1400×900, 390×844 and
320×740: unselected previews, truncation, missing/failed recap handling,
click/Enter/Esc, line/layout controls and no horizontal page overflow passed.
Phone-side HTTP through the SSH tunnel was verified, and the owner visually
approved the mockup after viewing it on the daily phone. Native terminal
rendering remains unverified. Browser keyboard geometry and wheel behavior
are illustrative, not runtime proof.

**Future proof needed:** approved candidate rendered through the real popup
with terminal-cell-safe clipping/wrapping, full recap access and no model calls.
Test density on short/narrow screens and singleton/multi-pane groups.

## OV-4 — Distinguish awaiting a questionnaire answer from working

**Reported:** a waiting question tool shows as WORKING; distinguish that wait.

**Confirmed source gap:** installed `@juicesharp/rpiv-ask-user-question`
2.12.0 publishes `rpiv:ask-user:blocked` with `{ active: true }` during
the actual questionnaire wait and `{ active: false }` in finally after
answer/cancel/error. Its public contract is in `events.ts`; both TUI and RPC
waits emit it. Invalid/no-UI paths do not assert waiting.

The stock-managed `dot_pi/private_agent/extensions/herdr-agent-state.ts`
listens to `herdr:blocked`, not that rpiv channel. Its blocked state takes
precedence over active/working, but there is no bridge for questionnaire waits.
Overview already consumes native blocked status. This is source-backed
diagnosis, not a live questionnaire-to-overview proof.

**Requested outcome:** an actual outstanding questionnaire is visibly awaiting
an answer rather than working, and its question-specific reason can be
distinguished from other blocked states. On answer, cancel or error, clear only
that wait; resume WORKING while the turn continues and READY when settled.

**Candidate path, not accepted design:** a small owned adapter bridges the
public waiting lifecycle into the existing state publisher, avoiding competing
native status writers or edits to the generated integration. Inspect whether
native reason/message metadata can carry a question-specific badge before
adding another publication path.

Do not infer waiting from prompt text, transcript scraping, tool-start events
or a tool name. A collapsed questionnaire still awaits input. Unknown or
missing event support must not invent a waiting state.

**Future design/proof:** exact label and reason transport; real question UI
against a dummy native backend; answer/cancel/error and no-UI cases; concurrent
blockers; session switch/reload/shutdown and missed event recovery; installed
event availability. Question package settings currently do not pin its version.

## Handoff to a new software-change run

Bring these four issues and the owner-accepted recap mockup revision into a
fresh run. Confirm the exact profile, role/model bindings and operating scope
before start. Separate open feasibility questions from accepted requirements;
do not treat this brief as approved intent/design/plan or prior run evidence.

Keep the established transient, native shared popup and its owner-tab dismissal
contract. No persistence/anchor/resurrection, automatic opens, transcript
scraping, viewer model calls, recap-driven names or live server restarts.
Preserve native pane identity, manual labels, separate recap/digest content and
exact focus guards. Isolated outside-in popup/Pi proof is required; internal
seam tests alone do not establish these behaviors.

## Repository locations

- Runtime: `dot_local/share/herdr-overview/src/{pane,navigation,model,herdr-api}.mjs`
- Renderer: `dot_local/share/herdr-overview/src/presenters/map.mjs`
- Owned Pi adapter: `dot_pi/private_agent/extensions/herdr-overview/`
- Native state integration: `dot_pi/private_agent/extensions/herdr-agent-state.ts`
- Mockup and brief: `docs/herdr-overview-mockups/`, ignored by chezmoi

Only the new mockup and this brief were written for this request. Existing
`index.html` and `map.html` are older untracked artifacts and were not changed.
