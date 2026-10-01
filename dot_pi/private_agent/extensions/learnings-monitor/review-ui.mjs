import { reviewIdentityKey } from "./review.mjs";

export function recordedTime(value, now = Date.now()) {
 const time = typeof value === "string" ? Date.parse(value) : NaN;
 if (!Number.isFinite(time)) return "Recorded: unknown";
 const days = Math.floor(Math.max(0, now - time) / 86400000);
 return `Recorded: ${new Date(time).toLocaleString()} (${days ? `${days}d` : `${Math.floor(Math.max(0, now-time)/3600000)}h`} ago)`;
}

/** One disposable interaction. Plain state and injected native dependencies only. */
export function createReviewView({ state, rows, draft, scopeLabel, tui, theme, done, deps }) {
 const { Text, ScrollView, matchesKey, truncateToWidth, wrapTextWithAnsi } = deps;
 let selected = Math.max(0, rows.findIndex(row => reviewIdentityKey(row) === state.selected));
 let width = 0, detailHeight = 1;
 const text = new Text("", 0, 0);
 const scroll = new ScrollView(text, { scrollbar: "hidden" });
 const refresh = () => {
  const row = rows[selected];
  if (row) state.selected = reviewIdentityKey(row);
  text.setText(row ? `${recordedTime(row.record.recordedAt)}\n${row.detail}` : "No learnings in this scope/filter.");
 };
 refresh();
 return {
  invalidate() { text.invalidate(); scroll.invalidate(); width = 0; },
  handleInput(data) {
   const row = rows[selected];
   if (matchesKey(data, "escape")) return done("exit");
   if (data === "s" || data === "f") return done(data);
   if (matchesKey(data, "up") || matchesKey(data, "down")) {
    selected = Math.max(0, Math.min(rows.length - 1, selected + (matchesKey(data, "up") ? -1 : 1)));
    const target = rows[selected];
    rows = rows.filter(item => state.status === "all" || (draft.get(item)?.status ?? item.record.status) === state.status || item === target);
    selected = Math.max(0, rows.indexOf(target));
    refresh(); scroll.scrollToStart();
   } else if (matchesKey(data, "pageUp")) scroll.scrollBy(-detailHeight);
   else if (matchesKey(data, "pageDown")) scroll.scrollBy(detailHeight);
   else if (row && data === "k") draft.stage(row, "kept");
   else if (row && data === "d") draft.stage(row, "dismissed");
   else if (row && data === "p") draft.togglePromotion(row);
   else if (row && data === "u") draft.reset(row);
   text.invalidate(); tui.requestRender();
  },
  render(w) {
   if (width !== w) { text.invalidate(); scroll.invalidate(); width = w; }
   const height = Math.max(6, tui.terminal.rows - 2);
   const listHeight = Math.min(Math.max(1, Math.floor(height / 3)), Math.max(1, rows.length));
   const start = Math.max(0, Math.min(selected - Math.floor(listHeight / 2), rows.length - listHeight));
   const lines = [theme.fg("accent", `Learnings review · ${scopeLabel} · ${state.status === "open" ? "Pending" : state.status} · ${draft.size} staged`)];
   for (let i = start; i < Math.min(rows.length, start + listHeight); i++) {
    const row = rows[i], choice = draft.get(row);
    lines.push(`${i === selected ? "▶" : " "} ${choice?.status ?? row.record.status}${choice?.promote ? " +Promote" : ""} · ${row.source.label ?? row.sourceId} · ${row.record.observation}`);
   }
   if (!rows.length) lines.push("No learnings in this scope/filter.");
   lines.push("── Details ──");
   detailHeight = Math.max(1, height - lines.length - 2);
   const content = text.render(w);
   scroll.updateLayout(content.length, detailHeight, () => tui.requestRender());
   // ScrollView exposes unsliced child lines; custom render owns viewport cropping.
   lines.push(...scroll.render(w).slice(scroll.scrollTop, scroll.scrollTop + detailHeight));
   while (lines.length < height - 2) lines.push("");
   lines.push(...wrapTextWithAnsi("↑↓ select · PgUp/PgDn details · k Keep · d Dismiss · p Promote · u Reset · s Scope · f Filter · Esc Exit", w).slice(0, 2));
   return lines.slice(0, height).map(line => truncateToWidth(line, w));
  },
 };
}

export async function openReview(commands, ctx, deps) {
 if (ctx.mode !== "tui" || !ctx.ui?.custom || !deps) throw new Error("Interactive review requires Pi terminal mode. Use /learnings list [source|all] for native protocol review.");
 const draft = commands.createDraft();
 const state = { scope: "current", status: "open", selected: undefined };
 const selections = new Map();
 for (;;) {
  const result = await commands.query({ scope: state.scope, status: "all" }, ctx);
  result.rows = result.rows.filter(row => state.status === "all" || (draft.get(row)?.status ?? row.record.status) === state.status || reviewIdentityKey(row) === state.selected);
  const scopeLabel = state.scope === "current" ? "Current session" : state.scope === "all" ? "All local sources" : state.scope.sourceId;
  const action = await ctx.ui.custom((tui, theme, _keys, done) => createReviewView({ state, rows: result.rows, draft, scopeLabel, tui, theme, done, deps }));
  if (action === "f") {
   const filters = ["open", "kept", "dismissed", "all"];
   state.status = filters[(filters.indexOf(state.status)+1)%4];
   const selected = result.rows.find(row => reviewIdentityKey(row) === state.selected);
   // A staged row stays visible during review, not across an explicit filter change.
   if (state.status !== "all" && (!selected || (draft.get(selected)?.status ?? selected.record.status) !== state.status)) state.selected = undefined;
   continue;
  }
  if (action === "s") {
   const labels = ["Current session", "All local sources", ...result.sources.map(source => `${source.label} · ${source.sourceId}`)];
   const choice = await ctx.ui.select("Review scope", labels);
   const index = labels.indexOf(choice);
   if (index >= 0) {
    selections.set(JSON.stringify(state.scope), state.selected);
    state.scope = index === 0 ? "current" : index === 1 ? "all" : { sourceId: result.sources[index-2].sourceId };
    state.selected = selections.get(JSON.stringify(state.scope));
   }
   continue;
  }
  if (!draft.size) return;
  const choice = await ctx.ui.select("Staged Learnings decisions", ["Apply", "Discard", "Continue"]);
  if (choice === "Discard") { draft.clear(); return; }
  if (choice !== "Apply") continue;
  const applied = await commands.apply(draft, ctx);
  ctx.ui.notify(`Learnings: ${applied.applied.length} applied; ${applied.errors.length} failed.`, applied.errors.length ? "warning" : "info");
  for (const promotion of applied.promotions) ctx.ui.notify(promotion.message, "info");
  if (!draft.size) return;
 }
}
