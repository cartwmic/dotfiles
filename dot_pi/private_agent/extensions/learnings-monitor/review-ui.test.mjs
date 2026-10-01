import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { createReviewView, recordedTime, openReview } from "./review-ui.mjs";
import { createReviewDraft, reviewIdentityKey } from "./review.mjs";
const require = createRequire(import.meta.url);
const packageRoot = require.resolve.paths("@earendil-works/pi-coding-agent").find(root => root === process.env.NODE_PATH);
const deps = await import(pathToFileURL(`${packageRoot}/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-tui/dist/index.js`).href);
const row = (id) => ({ sourceId: "source", id, source: { label: "中文 source" }, record: { status: "open", observation: `Learning ${id} 👨‍👩‍👧‍👦`, recordedAt: "2026-01-01T00:00:00Z" }, detail: Array.from({length:100}, (_,i)=>`Detail ${i}`).join("\n") });
const theme = { fg: (_color, text) => text };
test("native view bounds columns/height, scrolls details, stages without context or mutation", () => {
 const rows = Array.from({length:20}, (_,i)=>row(String(i)));
 const draft = createReviewDraft(), state = { status: "open" };
 const tui = { terminal: { rows: 24 }, requestRender() {} };
 let action;
 const view = createReviewView({ rows, draft, state, scopeLabel: "Current session", tui, theme, deps, done: value => action=value });
 for (const width of [80, 20, 1, 100]) {
  view.invalidate();
  const lines = view.render(width);
  assert.ok(lines.length <= 22);
  assert.ok(lines.every(line => deps.visibleWidth(line) <= width));
 }
 view.handleInput("k"); view.handleInput("p");
 assert.deepEqual(draft.get(rows[0]), {sourceId:"source",id:"0",status:"kept",promote:true});
 assert.match(view.render(80).join("\n"), /kept \+Promote/);
 const initialDetails = view.render(80);
 assert.match(initialDetails.join("\n"), /Detail 0\b/);
 view.handleInput("\x1b[6~");
 const pagedDetails = view.render(80);
 assert.doesNotMatch(pagedDetails.join("\n"), /Detail 0\b/);
 assert.match(pagedDetails.join("\n"), /Detail 12\b/);
 view.handleInput("\x1b[5~");
 assert.deepEqual(view.render(80), initialDetails);
 view.handleInput("d"); assert.equal(draft.get(rows[0]).promote, false);
 view.handleInput("u"); assert.equal(draft.size, 0);
 view.handleInput("\x1b[B"); assert.equal(state.selected, reviewIdentityKey(rows[1]));
 view.handleInput("f"); assert.equal(action,"f");
 view.handleInput("\x1b"); assert.equal(action,"exit");
 assert.equal(rows[0].record.status,"open");
});
test("empty and unknown age are honest, timestamp is original", () => {
 assert.equal(recordedTime(undefined), "Recorded: unknown");
 assert.equal(recordedTime("bad"), "Recorded: unknown");
 assert.match(recordedTime("2026-01-01T00:00:00Z", Date.parse("2026-01-03T00:00:00Z")), /2d ago/);
 const view = createReviewView({ rows: [], draft: createReviewDraft(), state:{status:"open"}, scopeLabel:"Current session", tui:{terminal:{rows:10},requestRender(){}},theme,deps,done(){} });
 assert.match(view.render(40).join("\n"), /No learnings/);
 view.handleInput("k"); view.handleInput("p");
});
test("controller guards terminal mode and uses each call's context; Continue preserves draft", async () => {
 let applied = 0;
 const commands = { createDraft: createReviewDraft, query: async (_options, ctx) => { assert.ok(ctx.token); return { rows:[row("one")], sources:[] }; }, apply: async (draft,ctx) => { assert.equal(ctx.token,"second"); applied++; assert.equal(draft.size,1); draft.clear(); return { applied:[{}], errors:[], promotions:[] }; } };
 await assert.rejects(openReview(commands,{mode:"rpc"},deps), /terminal mode/);
 for (const token of ["first","second"]) {
  let opens=0, notices=0;
  const ctx = { token, mode:"tui", ui:{ custom: async factory => { const view=factory({terminal:{rows:24},requestRender(){}},theme,null,()=>{}); opens++; view.handleInput("k"); return "exit"; }, select:async()=> token === "first" ? "Discard" : opens === 1 ? "Continue" : "Apply", notify:()=>notices++ } };
  await openReview(commands,ctx,deps);
  assert.equal(opens, token === "first" ? 1 : 2);
  assert.equal(notices,token === "first" ? 0 : 1);
 }
 assert.equal(applied,1);
});

test("explicit filters select eligible rows while Pending retains the staged selection", async () => {
 const rows = [row("open"), row("kept"), row("dismissed")];
 rows[1].record.status = "kept";
 rows[2].record.status = "dismissed";
 let step = 0;
 const commands = { createDraft: createReviewDraft, query: async () => ({ rows: [...rows], sources: [] }) };
 const ctx = { mode: "tui", ui: {
  custom: async factory => {
   const view = factory({ terminal: { rows: 24 }, requestRender() {} }, theme, null, () => {});
   const screen = () => view.render(120).join("\n");
   if (step === 0) {
    assert.match(screen(), /▶ open .*Learning open/);
    view.handleInput("k");
    assert.match(screen(), /▶ kept .*Learning open/);
    view.handleInput("d");
    assert.match(screen(), /▶ dismissed .*Learning open/);
   } else if (step === 1) {
    assert.match(screen(), /▶ kept .*Learning kept/);
    assert.doesNotMatch(screen(), /Learning open/);
    view.handleInput("p");
    assert.match(screen(), /kept \+Promote/);
   } else if (step === 2) {
    assert.match(screen(), /▶ dismissed .*Learning open/);
    assert.doesNotMatch(screen(), /Learning kept/);
   } else {
    assert.match(screen(), /▶ dismissed .*Learning open/);
    return "exit";
   }
   step++;
   return "f";
  }, select: async () => "Discard"
 } };
 await openReview(commands, ctx, deps);
 assert.equal(step, 3);
});
