import { createHash, randomUUID } from 'node:crypto';
import { join } from 'node:path';

/** Stable canonical JSON; fingerprints include every effective generation setting. */
export function canonical(value: any): string {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().filter(k => value[k] !== undefined).map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}';
  return JSON.stringify(value);
}
export const hash = (value: string) => createHash('sha256').update(value).digest('hex');
export const commandCatalog = [
  { value: 'view', label: 'view', description: 'View the saved recap for this branch' },
  { value: 'full', label: 'full', description: 'Recap the full current context; reuse matching snapshots' },
  { value: 'history', label: 'history', description: 'Search saved recaps for this session history' },
  { value: 'settings', label: 'settings', description: 'Edit session overrides' },
  { value: 'cancel', label: 'cancel', description: 'Cancel recap work, not Pi’s agent' },
  { value: 'help', label: 'help', description: 'Open this read-only command guide' },
];
export function argumentCompletions(prefix: string) {
  const words = prefix.trimStart().split(/\s+/), fragment = words.pop() ?? '';
  let choices = commandCatalog;
  if (words[0] === 'history' && words.slice(1).every(w => ['all', 'attempts', 'legacy'].includes(w))) {
    choices = [
      { value: 'all', label: 'all', description: 'Include other Pi session histories' },
      { value: 'attempts', label: 'attempts', description: 'Include unsuccessful attempts' },
      { value: 'legacy', label: 'legacy', description: 'Browse legacy records instead of Pi histories' },
    ].filter(c => !words.includes(c.value));
  } else if (words.length === 1 && words[0] === 'settings') {
    choices = [{ value: 'defaults', label: 'defaults', description: 'Edit defaults for future sessions' }];
  } else if (words.length) return [];
  return choices.filter(c => c.value.startsWith(fragment)).map(c => ({ ...c, value: [...words, c.value].join(' ') }));
}
export const commandHelp = [
  '/recap — Generate from new observed activity in current compaction-aware context (incremental). No new activity makes no model call.',
  ...commandCatalog.map(c => `/recap ${c.value} — ${c.description}.`),
  '/recap full — A matching full snapshot is reused without generation; successful coverage ends at capture.',
  '/recap history [all|attempts|legacy] — Filters combine: all includes other Pi histories; attempts includes failures; legacy browses older records instead. Type to search, Enter to view.',
  '/recap settings [defaults] — Session overrides inherit defaults; Clear override restores inheritance. defaults edits future defaults, not saved overrides.',
  '/recap cancel — Stops recap work only, not Pi’s agent; saved history and coverage remain.',
  'Automatic final-response, active-periodic and before-compaction recaps default on. Settings can disable them. The model follows current Pi unless overridden, captured per request.',
  'timeZone is display-only: local (default), UTC or an IANA zone. Help/view/history do not generate, cancel, change coverage or interrupt the main agent.',
].join('\n\n');
export const seedSettings = Object.freeze({ model: null, completed: true, periodic: true, beforeCompaction: true, mode: 'incremental', cadence: 1, intervalMinutes: 15, timeoutSeconds: 180, recursion: false, instructions: 'Write a detailed narrative recap for reorientation and resumption. Distinguish confirmed results from ongoing, queued, partial and failed work.', options: { thinkingLevel: 'off' }, timeZone: 'local' });
export type OwnedState = { nativeSessionId: string; historyId: string; overrides: Record<string, any> };
/** Pass all custom entries, not merely the branch, for session-wide preferences. */
export function restoreState(nativeSessionId: string, states: OwnedState[]): OwnedState {
  const owned = states.filter(s => s.nativeSessionId === nativeSessionId).at(-1);
  return owned ? structuredClone(owned) : { nativeSessionId, historyId: randomUUID(), overrides: {} };
}
export function resolveSettings(defaults: Record<string, any>, overrides: Record<string, any>) {
  const { inputBudget: _retired, ...effective } = { ...seedSettings, ...defaults, ...overrides };
  return structuredClone(effective);
}
export function setOverride(state: OwnedState, key: string, value: any): OwnedState {
  const next = structuredClone(state);
  if (value === undefined) delete next.overrides[key]; else next.overrides[key] = value;
  return next;
}
export type Unit = { id: string; text: string; status: string; verifiable: boolean };
/** Only public text and tool calls. Never serialize thinking, signatures or tool details. */
export function publicContent(content: any): string {
  if (typeof content === 'string') return content;
  return (content ?? []).flatMap((c: any) => c.type === 'text' ? [c.text] : c.type === 'toolCall' ? [`Tool call ${c.id}: ${c.name} ${canonical(c.arguments)}`] : c.type === 'image' ? ['[image]'] : []).join('\n');
}
export function messageUnit(message: any, id: string, verifiable = true, partial = false): Unit | null {
  if (!['user', 'assistant', 'toolResult'].includes(message.role)) return null;
  const text = publicContent(message.content) || (['error', 'aborted'].includes(message.stopReason) ? `[${message.stopReason}] ${message.errorMessage ?? 'No public output'}` : '');
  if (!text) return null;
  const status = partial ? 'ongoing/partial' : message.isError || ['error', 'aborted'].includes(message.stopReason) ? 'failed/aborted' : 'completed';
  return { id, text: `${message.role}${message.toolName ? ' ' + message.toolName : ''}: ${text}`, status, verifiable };
}
/** Live callers must retain an observation ID and map it to the finalized entry ID.
 * Missing mappings remain ephemeral/unverifiable; never infer identity from equal text. */
export function project(entries: any[], live: Unit[] = [], aliases: Record<string, string> = {}): Unit[] {
  const units = new Map<string, Unit>();
  for (const u of live) units.set(aliases[u.id] ?? u.id, { ...u, id: aliases[u.id] ?? u.id });
  for (const e of entries) {
    if (e.type !== 'message') continue;
    const u = messageUnit(e.message, e.id);
    if (u) units.set(u.id, u);
  }
  return [...units.values()];
}
/** Canonical SDK projection, using source IDs rather than summary/text equality.
 * Current coverage covers summaries themselves, never their archived originals. */
export function projectContext(projection: any, live: Unit[] = []): Unit[] {
  const units: Unit[] = [];
  for (const { sourceEntry, messages } of projection.entries) {
    for (const message of messages) {
      if (['compactionSummary', 'branchSummary'].includes(message.role)) {
        units.push({ id: `${sourceEntry.id}:${message.role}`, text: `${message.role}: ${message.summary}`, status: 'completed', verifiable: true });
      } else if (sourceEntry.type === 'message') {
        const unit = messageUnit(message, sourceEntry.id);
        if (unit) units.push(unit);
      }
    }
  }
  return [...units, ...structuredClone(live)];
}
export const recapScope = 'current-context';
export function failureNotice(failure: any): string {
  const advice: Record<string, string> = {
    input_limit: 'Recap exceeds the model-derived input limit (SDK estimate); choose a larger model or explicitly enable recursion.',
    context_limit: 'Recap exceeds the routed model context window (SDK estimate or provider rejection); choose a larger model or explicitly enable recursion.',
    model_limits: 'Recap model limits are unavailable or unusable; select a model with valid context/output limits.',
    timed_out: 'Recap timed out; adjust timeout or reduce requested work.',
  };
  return `${advice[failure?.reason] ?? 'Recap failed;'} coverage unchanged.`;
}
export type Version = { id: string; length: number; hash: string; status: string };
export const version = (u: Unit): Version => ({ id: u.id, length: u.text.length, hash: hash(u.text), status: u.status });
export type Coverage = { anchor: string | null; units: Version[] };
/** An abandoned branch baseline covers nothing. Changed/final states remain updates. */
export function uncovered(units: Unit[], baseline: Coverage | null, branchIds: string[]): Unit[] {
  if (!baseline || (baseline.anchor !== null && !branchIds.includes(baseline.anchor))) return structuredClone(units);
  return units.flatMap(u => {
    const old = baseline.units.find(v => v.id === u.id);
    if (!u.verifiable || !old || old.length > u.text.length || hash(u.text.slice(0, old.length)) !== old.hash || old.status !== u.status) return [structuredClone(u)];
    return old.length === u.text.length ? [] : [{ ...u, text: `[update after covered prefix]\n${u.text.slice(old.length)}` }];
  });
}
export function capture(units: Unit[], branchIds: string[], state: OwnedState, settings: any, mode: string, trigger: string, capturedAt = new Date().toISOString()) {
  const coverage = { anchor: branchIds.at(-1) ?? null, units: units.filter(u => u.verifiable).map(version) };
  const { timeZone: _presentationOnly, ...generationSettings } = settings;
  const settingsFingerprint = hash(canonical(generationSettings));
  return { material: units.map(u => `[${u.status}] ${u.text}`).join('\n\n'), fingerprint: hash(canonical({ units: units.map(version), settings: generationSettings, mode, scope: recapScope })), metadata: { pi: { nativeSessionId: state.nativeSessionId, historyId: state.historyId, capturedAt, capturedEnd: coverage.anchor, scope: recapScope, mode, trigger, settingsFingerprint, coverage } } };
}
/** Runtime argv is private; persist only provider/model identity, never these paths/options. */
export function backendCommand(getPackageDir: () => string, helper: string, agentDir: string, cwd: string, settings: any, node = process.execPath) {
  if (!settings.model?.provider || !settings.model?.id) throw new Error('Recap model is unset');
  return [node, helper, join(getPackageDir(), 'dist', 'index.js'), agentDir, cwd, JSON.stringify({ model: settings.model, instructions: settings.instructions, options: settings.options, budgetBackground: settings.budgetBackground })];
}

/** null means follow the current selection, captured afresh for each request. */
export function capturedSettings(settings: any, currentModel: any) {
  const model = settings.model ?? currentModel;
  return structuredClone({ ...settings, model: model ? { provider: model.provider, id: model.id } : null });
}
export function validTimeZone(zone: any): boolean {
  if (typeof zone !== 'string' || !zone.trim()) return false;
  try { new Intl.DateTimeFormat('en-US', zone === 'local' ? {} : { timeZone: zone }); return true; } catch { return false; }
}
export function displayTime(timestamp: string, zone = 'local'): string {
  const formatter = new Intl.DateTimeFormat('sv-SE', { ...(zone === 'local' ? {} : { timeZone: zone }), year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23', timeZoneName: 'shortOffset' });
  return `${formatter.format(new Date(timestamp))} [${zone === 'local' ? formatter.resolvedOptions().timeZone : zone}]`;
}
export function compatibleRecord(rows: any[], state: OwnedState, branchIds: string[], scope?: string) {
  return rows.filter(r => r.status === 'published' && (!scope || r.metadata?.pi?.scope === scope) && r.metadata?.pi?.nativeSessionId === state.nativeSessionId && r.metadata.pi.historyId === state.historyId && r.metadata.pi.coverage && (!r.metadata.pi.coverage.anchor || branchIds.includes(r.metadata.pi.coverage.anchor))).sort((a, b) => a.created_at.localeCompare(b.created_at) || a.record_id.localeCompare(b.record_id)).at(-1);
}
