import type { ExtensionAPI, ExtensionContext } from '@earendil-works/pi-coding-agent';
import { getPackageDir, getAgentDir } from '@earendil-works/pi-coding-agent';
import { Input, SelectList, truncateToWidth, stripTerminalSequences, matchesKey, Key, wrapTextWithAnsi } from '@earendil-works/pi-tui';
import { spawn, execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdtempSync, rmSync, openSync, closeSync } from 'node:fs';
import { tmpdir, homedir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { budgets } from './backend.mjs';
import { restoreState, resolveSettings, setOverride, project, capture, uncovered, backendCommand, messageUnit, publicContent, canonical, capturedSettings, validTimeZone, displayTime, compatibleRecord } from './helpers.ts';

const directory = dirname(fileURLToPath(import.meta.url));
const configPath = join(directory, 'config.json');
const cli = join(homedir(), '.local/bin/session-recap');
const cliEnv = () => ({ ...process.env, ...(process.env.PI_RECAP_CLI ? { SESSION_RECAP_IMPLEMENTATION: process.env.PI_RECAP_CLI } : {}) });
const call = (...args: string[]) => JSON.parse(execFileSync(cli, args, { env: cliEnv(), encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }));
const records = () => {
  // Retained history is unbounded by policy; a pipe would impose Node's
  // default 1 MiB maxBuffer on every caller, even for a small active branch.
  const temp = mkdtempSync(join(tmpdir(), 'pi-recap-records-'));
  const path = join(temp, 'records.json');
  try {
    const fd = openSync(path, 'wx', 0o600);
    try {
      execFileSync(cli, ['list', '--json'], { env: cliEnv(), stdio: ['ignore', fd, 'ignore'] });
    } finally { closeSync(fd); }
    return JSON.parse(readFileSync(path, 'utf8')).records;
  } finally { rmSync(temp, { recursive: true, force: true }); }
};
const interactive = (ctx: ExtensionContext) => ctx.mode === 'tui' && ctx.hasUI;

export default function recap(pi: ExtensionAPI) {
  let active = false, sessionId = '', contextEpoch = 0;
  let state: any;
  let working = false, settlements = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let observation = '';
  const live = new Map<string, any>();
  const actions: { sessionId: string; trigger: string }[] = [];
  function stopTimer() { if (timer) clearTimeout(timer); timer = undefined; }
  function armTimer() {
    stopTimer();
    if (!active || !working || !state) return;
    const settings = resolveSettings(defaults(), state.overrides);
    if (!settings.periodic) return;
    const id = sessionId;
    timer = setTimeout(() => {
      timer = undefined;
      if (!active || !working || sessionId !== id) return;
      actions.push({ sessionId: id, trigger: 'periodic' });
      dispatch();
      armTimer();
    }, settings.intervalMinutes * 60_000);
    timer.unref();
  }
  function ongoing() { return [...live.values()].filter(u => u.status === 'ongoing/partial').map(u => u.text).join('\n') || 'Pi is still working; no new public progress observed.'; }
  const generations = new Map<string, number>();
  const queue: any[] = [];
  const pipes = new Set<any>();
  const announced = new Set<string>();
  const dispatchName = 'recap-deliver-internal';
  const nonce = randomUUID();
  const key = (id: string) => `pi-recap:${id}`;
  const invalidate = (id: string) => { const n = (generations.get(id) ?? 0) + 1; generations.set(id, n); return n; };
  function defaults() { try { return JSON.parse(readFileSync(configPath, 'utf8')); } catch { return {}; } }
  function initialize(ctx: ExtensionContext) {
    contextEpoch++;
    sessionId = ctx.sessionManager.getSessionId();
    state = restoreState(sessionId, ctx.sessionManager.getEntries().filter((e: any) => e.type === 'custom' && e.customType === 'recap-state').map((e: any) => e.data));
    pi.appendEntry('recap-state', state);
    working = false; settlements = 0; live.clear(); observation = ''; actions.length = 0; stopTimer();
    refreshWidget(ctx);
  }
  function dispatch() {
    if (!active || !pi.getCommands().some(c => c.name === dispatchName)) return false;
    pi.sendUserMessage(`/${dispatchName} ${nonce}`, { expandPromptTemplates: true });
    return true;
  }
  function notice(ctx: ExtensionContext, text: string) { ctx.ui.notify(ctx.ui.theme.fg('dim', text), 'info'); }
  function currentRecap(ctx: ExtensionContext) {
    return compatibleRecord(records(), state, ctx.sessionManager.getBranch().map((e: any) => e.id));
  }
  function refreshWidget(ctx: ExtensionContext) {
    // Factories retain only plain presentation data, never a session context.
    let record; try { record = currentRecap(ctx); } catch { /* Hide unavailable history. */ }
    if (!record) { ctx.ui.setWidget('recap', undefined); return; }
    const time = displayTime(record.published_at ?? record.created_at, resolveSettings(defaults(), state.overrides).timeZone);
    const excerpt = stripTerminalSequences(record.summary).replace(/\s+/g, ' ').trim();
    ctx.ui.setWidget('recap', (_tui, theme) => ({
      invalidate() {},
      render(width: number) { return [theme.fg('dim', stripTerminalSequences(truncateToWidth(`Recap updated ${time}`, width))), theme.fg('dim', stripTerminalSequences(truncateToWidth(excerpt, width)))]; },
    }), { placement: 'aboveEditor' });
  }
  function saved(record: any) {
    if (announced.has(record.record_id)) return;
    announced.add(record.record_id);
    pi.events.emit('recap:saved', { recordId: record.record_id, sessionId: record.metadata.pi.nativeSessionId, historyId: record.metadata.pi.historyId });
  }
  async function consume(ctx: ExtensionContext) {
    if (!interactive(ctx)) return;
    const id = ctx.sessionManager.getSessionId();
    for (let i = queue.length - 1; i >= 0; i--) {
      const item = queue[i];
      if (item.sessionId !== id) continue;
      queue.splice(i, 1);
      if (generations.get(id) !== item.generation || (item.epoch !== undefined && item.epoch !== contextEpoch)) continue;
      let current; try { current = call('current', '--key', key(id), '--json'); } catch { continue; }
      if (current.token !== item.token || generations.get(id) !== item.generation || ctx.sessionManager.getSessionId() !== id) continue;
      if (item.notice) notice(ctx, item.notice);
      else if (item.status === 'published') {
        const record = call('read', item.record_id, '--json').record;
        saved(record);
        refreshWidget(ctx);
      } else if (item.status === 'generated-unsaved') ctx.ui.notify(item.warning, 'warning');
      else if (!['superseded', 'cancelled'].includes(item.status)) notice(ctx, `Recap ${item.status}; coverage unchanged.`);
    }
  }
  async function picker(ctx: ExtensionContext) {
    const models = ctx.modelRegistry.getAvailable();
    const choices = models.map((m: any) => `${m.provider}/${m.id}`);
    const selected = await ctx.ui.select('Recap model', ['Follow current Pi model', ...choices]);
    if (selected === 'Follow current Pi model') return null;
    const model = models[choices.indexOf(selected!)];
    return model ? { provider: model.provider, id: model.id } : undefined;
  }
  async function settings(ctx: ExtensionContext, scope = 'session') {
    for (;;) {
      const base = defaults(), effective = resolveSettings(base, state.overrides);
      const target = scope === 'defaults' ? resolveSettings(base, {}) : effective;
      const fields = Object.keys(target);
      const help: Record<string, string> = {
        model: 'null follows current Pi model', completed: 'After final response, error or abort',
        periodic: 'Progress only while Pi is active', beforeCompaction: 'Capture before context is compacted',
        mode: 'New activity or full branch snapshot', cadence: 'Final responses per automatic recap',
        intervalMinutes: 'Active progress interval in minutes', timeoutSeconds: 'Whole attempt limit; one retry',
        recursion: 'Allow reduction of oversized input', instructions: 'Instructions for recap generation',
        options: 'Independent thinking and output limit', inputBudget: 'Input byte ceiling; model bound applies',
        timeZone: 'Display only: local, UTC or IANA zone',
      };
      const items = ['Done', scope === 'session' ? 'Edit defaults' : 'Edit session', ...fields];
      const choice = await ctx.ui.custom<string | undefined>((tui, theme, _kb, done) => {
        let selected = 0;
        return { invalidate() {}, render(width: number) {
          const start = Math.max(0, selected - 4);
          return [truncateToWidth(theme.fg('dim', `Recap ${scope} settings — ↑↓ Enter, Esc close`), width), ...items.slice(start, start + 5).flatMap((field, i) => {
            const isField = fields.includes(field);
            const origin = scope === 'defaults' ? 'default' : field in state.overrides ? 'session' : 'inherited';
            const label = isField ? `${field} (${origin}): ${field === 'model' && target[field] === null ? 'follow current' : JSON.stringify(target[field])}` : field;
            return [truncateToWidth(theme.fg(start + i === selected ? 'accent' : 'text', `${start + i === selected ? '› ' : '  '}${label}`), width), ...(isField ? wrapTextWithAnsi(theme.fg('dim', `  ${help[field]}`), width) : [])];
          })];
        }, handleInput(data: string) {
          if (matchesKey(data, Key.escape)) done(undefined);
          else if (matchesKey(data, Key.enter)) done(items[selected]);
          else { if (matchesKey(data, Key.up)) selected = Math.max(0, selected - 1); if (matchesKey(data, Key.down)) selected = Math.min(items.length - 1, selected + 1); tui.requestRender(); }
        } };
      });
      if (!choice || choice === 'Done') return;
      if (choice.startsWith('Edit ')) { scope = choice === 'Edit defaults' ? 'defaults' : 'session'; continue; }
      const field = choice;
      const action = await ctx.ui.select(field, scope === 'session' ? ['Set', 'Clear override'] : ['Set']);
      if (!action) continue;
      let value: any;
      if (action === 'Set') {
        if (field === 'model') { value = await picker(ctx); if (value === undefined) continue; }
        else {
          const input = await ctx.ui.input(`Set ${field} (JSON; instructions may be plain text)`, JSON.stringify(target[field]));
          if (input === undefined) continue;
          try { value = JSON.parse(input); } catch { if (['instructions', 'timeZone'].includes(field)) value = input; else { notice(ctx, 'Invalid JSON'); continue; } }
          if (typeof value !== typeof target[field] || (typeof value === 'number' && (!Number.isFinite(value) || value <= 0)) || (field === 'mode' && !['incremental', 'full'].includes(value)) || (field === 'timeZone' && !validTimeZone(value))) { notice(ctx, 'Invalid setting'); continue; }
        }
      }
      if (scope === 'defaults') writeFileSync(configPath, JSON.stringify({ ...base, [field]: value }, null, 2) + '\n', { mode: 0o600 });
      else { state = setOverride(state, field, value); pi.appendEntry('recap-state', state); }
      refreshWidget(ctx);
    }
  }
  async function viewer(ctx: ExtensionContext, title: string, text: string) {
    await ctx.ui.custom<void>((tui, theme, _kb, done) => {
      let top = 0;
      return { invalidate() {}, render(width: number) { const lines = wrapTextWithAnsi(text, width); top = Math.min(top, Math.max(0, lines.length - 18)); return [...wrapTextWithAnsi(theme.fg('dim', title + ' — ↑↓ scroll, Esc close'), width), ...lines.slice(top, top + 18).map(l => theme.fg('dim', l))]; }, handleInput(data: string) { if (matchesKey(data, Key.escape)) done(); else { if (matchesKey(data, Key.up)) top = Math.max(0, top - 1); if (matchesKey(data, Key.down)) top++; if (matchesKey(data, Key.pageDown)) top += 18; if (matchesKey(data, Key.pageUp)) top = Math.max(0, top - 18); tui.requestRender(); } } };
    });
  }
  async function history(ctx: ExtensionContext, args: string[]) {
    const legacy = args.includes('legacy'), attempts = args.includes('attempts'), all = args.includes('all');
    const rows = records().filter((r: any) => legacy ? !r.metadata?.pi?.historyId : r.source_kind === 'pi' && !!r.metadata?.pi?.historyId).filter((r: any) => all || legacy || r.metadata.pi.historyId === state.historyId).filter((r: any) => attempts || r.status === 'published').sort((a: any, b: any) => Number(b.metadata?.pi?.historyId === state.historyId) - Number(a.metadata?.pi?.historyId === state.historyId) || b.created_at.localeCompare(a.created_at));
    const zone = resolveSettings(defaults(), state.overrides).timeZone;
    const labels = rows.map((r: any) => `${displayTime(r.created_at, zone)} ${r.status}${r.failure?.reason === 'timed_out' ? ' (timed out)' : ''} ${r.metadata?.pi?.trigger ?? 'legacy'} ${r.source_id} ${r.record_id}`);
    const choice = await ctx.ui.custom<string | undefined>((tui, theme, _kb, done) => {
      const input = new Input({ prompt: 'Search: ' });
      const makeList = (query: string) => new SelectList(labels.map((label: string, i: number) => ({ value: String(i), label })).filter((item: any) => `${item.label} ${rows[Number(item.value)].summary ?? ''}`.toLowerCase().includes(query.toLowerCase())), 10, {
        selectedPrefix: text => theme.fg('accent', text), selectedText: text => theme.fg('accent', text),
        description: text => theme.fg('dim', text), scrollInfo: text => theme.fg('dim', text), noMatch: text => theme.fg('dim', text),
      });
      let list = makeList('');
      const bind = () => { list.onSelect = item => done(item.value); list.onCancel = () => done(undefined); };
      bind();
      return {
        get focused() { return input.focused; }, set focused(value: boolean) { input.focused = value; },
        invalidate() { input.invalidate(); list.invalidate(); },
        render(width: number) { return [truncateToWidth(theme.fg('dim', 'Recap history — type to search, ↑↓ select, Enter view, Esc close'), width), ...input.render(width), ...list.render(width)]; },
        handleInput(data: string) {
          if ([Key.up, Key.down, Key.enter, Key.escape].some(key => matchesKey(data, key))) list.handleInput(data);
          else { input.handleInput(data); list = makeList(input.getValue()); bind(); }
          tui.requestRender();
        },
      };
    });
    const record = choice === undefined ? undefined : rows[Number(choice)];
    if (record) await viewer(ctx, `${record.record_id} ${displayTime(record.created_at, zone)} ${record.status}`, record.summary ?? JSON.stringify(record.failure ?? record, null, 2));
  }
  async function request(ctx: ExtensionContext, mode = 'incremental', trigger = 'manual') {
    const id = ctx.sessionManager.getSessionId(), generation = invalidate(id), epoch = contextEpoch;
    const reserved = call('reserve', '--key', key(id), '--json');
    const own = structuredClone(state);
    let settings = capturedSettings(resolveSettings(defaults(), own.overrides), ctx.model);
    const entries = ctx.sessionManager.getBranch(), ids = entries.map((e: any) => e.id);
    const units = project(entries, [...live.values()]);
    if (!units.length) { if (trigger === 'manual') notice(ctx, 'Nothing to recap yet.'); return; }
    const prior = compatibleRecord(records(), own, ids);
    const pending = uncovered(units, prior?.metadata.pi.coverage ?? null, ids);
    if ((mode !== 'full' || trigger === 'periodic') && !pending.length) { refreshWidget(ctx); if (trigger === 'manual') notice(ctx, 'No new activity.'); return; }
    if (!settings.model) {
      if (trigger !== 'manual') { ctx.ui.notify('Recap model unavailable; coverage unchanged.', 'warning'); return; }
      const setupCurrent = () => active && contextEpoch === epoch && sessionId === id && generations.get(id) === generation && ctx.sessionManager.getSessionId() === id && call('current', '--key', key(id), '--json').token === reserved.token;
      const model = await picker(ctx); if (!model || !setupCurrent()) return;
      const scope = await ctx.ui.select('Save recap model', ['Current session', 'Defaults for future sessions']);
      if (!scope || !setupCurrent()) return;
      if (scope === 'Defaults for future sessions') writeFileSync(configPath, JSON.stringify({ ...defaults(), model }, null, 2) + '\n', { mode: 0o600 });
      else { state = setOverride(state, 'model', model); pi.appendEntry('recap-state', state); }
      settings = capturedSettings(resolveSettings(defaults(), state.overrides), ctx.model);
    }
    const material = (mode === 'full' ? units : pending).map(u => `[${u.status}] ${u.text}`).join('\n\n');
    let effectiveBudgets;
    try {
      const selectedModel = ctx.modelRegistry.find(settings.model.provider, settings.model.id);
      if (!selectedModel) throw new Error('Selected recap model unavailable');
      if (selectedModel.api !== 'pi-virtual') effectiveBudgets = budgets(selectedModel, settings, settings.options.thinkingLevel ?? 'off');
    } catch { notice(ctx, 'Recap selected model unavailable or unusable; coverage unchanged.'); return; }
    // Capture everything while this call's context is fresh, before compaction
    // can change public material. Neither preflight nor its callbacks receive ctx.
    const work = { id, generation, epoch, token: reserved.token, own, settings, units, ids, mode, trigger, material, background: prior?.summary ?? '', cwd: ctx.cwd, ongoing: trigger === 'periodic' ? ongoing() : '', capturedAt: new Date().toISOString(), effectiveBudgets };
    handoff(work);
  }
  function authorized(work: any) {
    try { return call('current', '--key', key(work.id), '--json').token === work.token; }
    catch { return false; }
  }
  function enqueueNotice(work: any, text: string) {
    if (!active || contextEpoch !== work.epoch || sessionId !== work.id || generations.get(work.id) !== work.generation || !authorized(work)) return;
    queue.push({ sessionId: work.id, generation: work.generation, epoch: work.epoch, token: work.token, notice: text });
    dispatch();
  }
  function handoff(work: any) {
    const { id, generation, own, settings, units, ids, mode, trigger, material, background, cwd } = work;
    try {
      if (!authorized(work)) return;
      const effectiveBudgets = work.effectiveBudgets;
      const generationSettings = effectiveBudgets ? { ...settings, inputBudget: effectiveBudgets.inputBudget, options: { ...settings.options, maxTokens: effectiveBudgets.maxTokens } } : settings;
      // Virtual budgets are resolved inside each detached attempt. Fingerprints
      // describe captured source/settings, not metadata that is not yet known.
      const snapshot: any = capture(units, ids, own, effectiveBudgets ? { ...settings, effectiveBudgets } : settings, mode, trigger, work.capturedAt);
      const reuse = mode === 'full' && records().find((r: any) => r.status === 'published' && r.metadata?.pi?.historyId === own.historyId && r.metadata.pi.fingerprint === snapshot.fingerprint);
      if (reuse) { if (trigger === 'manual') enqueueNotice(work, 'Reused matching full recap.'); return; }
      if (!authorized(work)) return;
      const temp = mkdtempSync(join(tmpdir(), 'pi-recap-'));
      const path = join(temp, 'request.json');
      snapshot.metadata.pi.fingerprint = snapshot.fingerprint;
      const command = backendCommand(getPackageDir, join(directory, 'backend.mjs'), getAgentDir(), cwd, generationSettings);
      writeFileSync(path, JSON.stringify({ schema_version: 1, request_key: key(id), token: work.token, source_kind: 'pi', source_id: id, kind: 'single', metadata: snapshot.metadata, material, background, instructions: settings.instructions, command, ...(!effectiveBudgets ? { preflight: { command: [...command, '--preflight'] } } : {}), backend_identity: { provider: settings.model.provider, model: settings.model.id }, timeout_seconds: settings.timeoutSeconds, input_budget_bytes: effectiveBudgets?.inputBudget ?? settings.inputBudget, recursive: settings.recursion }), { mode: 0o600 });
      const child = spawn(cli, ['run', '--request-file', path, '--json-lines'], { env: cliEnv(), detached: true, stdio: ['ignore', 'pipe', 'ignore'] });
      pipes.add(child.stdout); let buffer = '';
      child.stdout.on('data', (chunk: Buffer) => {
        buffer += chunk.toString(); let end;
        while ((end = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, end); buffer = buffer.slice(end + 1);
          try { const event = JSON.parse(line); if (event.event === 'terminal') {
            if (event.status === 'published' && active && sessionId === id && generations.get(id) === generation && call('current', '--key', key(id), '--json').token === event.token) armTimer();
            queue.push({ ...event, sessionId: id, generation, epoch: work.epoch }); dispatch();
          } } catch { /* Invalid pipe event is not an outcome. */ }
        }
      });
      child.on('error', () => { rmSync(temp, { recursive: true, force: true }); });
      child.on('close', () => { pipes.delete(child.stdout); rmSync(temp, { recursive: true, force: true }); });
      child.unref(); child.stdout.unref();
    } catch { enqueueNotice(work, 'Recap operation failed; coverage unchanged.'); }
  }
  pi.registerCommand(dispatchName, { description: 'Internal recap delivery', handler: async (args, ctx) => {
    if (!active || args !== nonce || !interactive(ctx) || ctx.sessionManager.getSessionId() !== sessionId) return;
    await consume(ctx);
    refreshWidget(ctx);
    for (const action of actions.splice(0)) {
      if (action.sessionId !== sessionId || (action.trigger === 'periodic' && !working)) continue;
      try { await request(ctx, resolveSettings(defaults(), state.overrides).mode, action.trigger); }
      catch { notice(ctx, 'Recap operation failed; coverage unchanged.'); }
    }
  } });
  pi.registerCommand('recap', { description: 'Recap [view|full|history [all|attempts|legacy]|settings [defaults]|cancel]', handler: async (args, ctx) => {
    if (!interactive(ctx)) return;
    if (sessionId !== ctx.sessionManager.getSessionId()) initialize(ctx);
    const parts = args.trim().split(/\s+/);
    try {
      if (parts[0] === 'cancel') { invalidate(sessionId); call('cancel', '--key', key(sessionId), '--json'); notice(ctx, 'Recap cancelled; saved history retained.'); }
      else if (parts[0] === 'settings') {
        const before = resolveSettings(defaults(), state.overrides);
        await settings(ctx, parts[1] === 'defaults' ? 'defaults' : 'session');
        const after = resolveSettings(defaults(), state.overrides);
        if (before.periodic !== after.periodic || before.intervalMinutes !== after.intervalMinutes) armTimer();
      }
      else if (parts[0] === 'view') {
        const record = currentRecap(ctx);
        if (record) await viewer(ctx, `Recap ${displayTime(record.published_at ?? record.created_at, resolveSettings(defaults(), state.overrides).timeZone)}`, record.summary);
        else notice(ctx, 'No saved recap for this branch.');
      }
      else if (parts[0] === 'history') await history(ctx, parts.slice(1));
      else if (!parts[0] || parts[0] === 'full') await request(ctx, parts[0] === 'full' ? 'full' : 'incremental');
      else notice(ctx, 'Use /recap [view|full|history|settings|cancel].');
    } catch { notice(ctx, 'Recap operation failed; coverage unchanged.'); }
  } });
  pi.on('session_start', async (_event, ctx) => {
    active = interactive(ctx); if (!active) return;
    initialize(ctx);
    try { for (const record of records().filter((r: any) => r.status === 'published' && r.metadata?.pi?.nativeSessionId === sessionId)) saved(record); await consume(ctx); } catch { /* Recovery can be retried via history. */ }
  });
  pi.on('agent_start', (_event, ctx) => {
    if (!active || !interactive(ctx)) return;
    if (!working) { working = true; armTimer(); }
  });
  pi.on('message_start', (event, ctx) => {
    if (!active || !interactive(ctx) || event.message.role !== 'assistant') return;
    observation = `live:${randomUUID()}`;
  });
  pi.on('message_update', (event, ctx) => {
    if (!active || !interactive(ctx) || !observation) return;
    const unit = messageUnit(event.message, observation, true, true);
    if (unit) live.set(observation, unit);
  });
  pi.on('turn_end', (_event, ctx) => {
    if (!active || !interactive(ctx)) return;
    // Final persisted messages replace observations; never match by equal text.
    if (observation) live.delete(observation);
    observation = '';
    for (const entry of ctx.sessionManager.getBranch()) {
      if (entry.type === 'message' && entry.message.role === 'toolResult') live.delete(`tool:${entry.message.toolCallId}`);
    }
  });
  pi.on('tool_execution_start', (event, ctx) => {
    if (!active || !interactive(ctx)) return;
    const id = `tool:${event.toolCallId}`;
    live.set(id, { id, text: `Tool ${event.toolName} (${event.toolCallId}) running: ${canonical(event.args)}`, status: 'ongoing/partial', verifiable: true });
  });
  pi.on('tool_execution_update', (event, ctx) => {
    if (!active || !interactive(ctx)) return;
    const unit = live.get(`tool:${event.toolCallId}`);
    if (unit) unit.text = `Tool ${event.toolName} (${event.toolCallId}) running: ${canonical(event.args)}\n${publicContent(event.partialResult?.content)}`;
  });
  pi.on('tool_execution_end', (event, ctx) => {
    if (!active || !interactive(ctx)) return;
    const unit = live.get(`tool:${event.toolCallId}`);
    if (unit) { unit.text = `Tool ${event.toolName} (${event.toolCallId}): ${publicContent(event.result?.content)}`; unit.status = event.isError ? 'failed/aborted' : 'completed'; }
  });
  pi.on('agent_settled', async (_event, ctx) => {
    if (!active || !interactive(ctx)) return;
    working = false; stopTimer();
    const settings = resolveSettings(defaults(), state.overrides);
    settlements++;
    if (settings.completed && settlements % Math.max(1, Math.floor(settings.cadence)) === 0) {
      try { await request(ctx, settings.mode, 'settlement'); } catch { notice(ctx, 'Recap operation failed; coverage unchanged.'); }
    }
  });
  pi.on('session_before_compact', async (_event, ctx) => {
    if (!active || !interactive(ctx)) return;
    const settings = resolveSettings(defaults(), state.overrides);
    if (settings.beforeCompaction) {
      try { await request(ctx, settings.mode, 'before-compaction'); } catch { notice(ctx, 'Recap operation failed; coverage unchanged.'); }
    }
  });
  pi.on('session_tree', (_event, ctx) => { live.clear(); observation = ''; if (interactive(ctx)) refreshWidget(ctx); });
  pi.on('session_shutdown', () => { contextEpoch++; active = false; working = false; stopTimer(); actions.length = 0; live.clear(); for (const pipe of pipes) pipe.destroy(); pipes.clear(); });
}
