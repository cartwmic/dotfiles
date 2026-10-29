// notify-owner: the one explicit way a Pi worker rings the owner's doorbell.
//
// A worker that needs the owner calls the `notify_owner` tool; an `ask_user_question` dialog
// rings too; a clean Pi exit in a Herdr pane reports `exited`. Each runs `agent-alert emit` for
// this pane. Nothing is inferred from status, labels or screen text, and a plain finished turn
// does not ring.
//
// Kept free of Pi imports so node --test can run it. index.ts wires it to Pi.
import { spawn } from "node:child_process";
import { accessSync, appendFileSync, constants, mkdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export const TOOL_NAME = "notify_owner";
export const ASK_TOOL_NAME = "ask_user_question";
const CORE_RELATIVE = ".local/share/agent-alert/core/agent-alert";
const LOG_RELATIVE = ".local/state/agent-alert/agent-alert.log";

type Env = Record<string, string | undefined>;
type Child = { on(event: string, handler: (arg?: unknown) => void): unknown; unref(): void };
type Spawner = (command: string, args: string[], options: Record<string, unknown>) => Child;
export type Kind = "question" | "exited";

/** A subagent child has no owner to ring (its supervisor answers it), and outside Herdr there is no pane to name. */
export function eligible(env: Env): boolean {
  return env.PI_SUBAGENT_CHILD !== "1" && Boolean(env.HERDR_PANE_ID?.trim());
}

export function corePath(env: Env): string {
  return join(env.HOME || homedir(), CORE_RELATIVE);
}

// Only "~" and "~/..." (the core also expands "~user/...", which nobody sets here).
const expand = (path: string, home: string) => (path === "~" || path.startsWith("~/") ? join(home, path.slice(1)) : path);

/** The operator log path, resolved as the core does: AGENT_ALERT_LOG, then log_path in the config file, then the default. */
export function logPath(env: Env): string {
  const home = env.HOME || homedir();
  if (env.AGENT_ALERT_LOG) return expand(env.AGENT_ALERT_LOG, home);
  try {
    const config = JSON.parse(readFileSync(expand(env.AGENT_ALERT_CONFIG || "~/.config/agent-alert/config.json", home), "utf8"));
    if (typeof config?.log_path === "string" && config.log_path) return expand(config.log_path, home);
  } catch {
    // no config, or not JSON: the default
  }
  return join(home, LOG_RELATIVE);
}

/** The agent-alert operator log, where the core and the sinks already write their problems. */
function logProblem(env: Env, message: string): void {
  try {
    const path = logPath(env);
    mkdirSync(dirname(path), { recursive: true });
    appendFileSync(path, `${new Date().toISOString().replace(/\.\d+Z$/, "Z")} notify-owner: ${message}\n`);
  } catch {
    // best effort
  }
}

/**
 * Start `agent-alert emit` for this pane and do not wait for it (the core waits on the sink, up to its bound).
 * "sent" means the command was started; a failure to start it or a nonzero exit is logged to the operator log.
 */
export function ring(env: Env, kind: Kind = "question", spawnFn: Spawner = spawn as unknown as Spawner): "sent" | "no-core" | "no-pane" {
  const pane = env.HERDR_PANE_ID?.trim();
  if (!pane) return "no-pane";
  const core = corePath(env);
  try {
    accessSync(core, constants.X_OK);
  } catch {
    return "no-core";
  }
  const args = ["emit", "--worker", pane, "--kind", kind, "--context", "agent=pi"];
  if (env.HERDR_WORKSPACE_ID?.trim()) args.push("--context", `workspace_id=${env.HERDR_WORKSPACE_ID.trim()}`);
  const child = spawnFn(core, args, { detached: true, stdio: "ignore", env });
  child.on("error", (error) => logProblem(env, `cannot start agent-alert emit (${kind}): ${(error as Error)?.message ?? error}`));
  child.on("exit", (code) => {
    if (code !== 0) logProblem(env, `agent-alert emit (${kind}) exited with status ${code}; the event was not recorded`);
  });
  child.unref();
  return "sent";
}

export const ALERT_KINDS = ["report", "review", "question", "decision", "blocked"] as const;
export const ALERT_SCOPES = ["step", "workstream"] as const;
export const ALERT_DOORS = ["none", "push", "force_push", "delete", "deploy", "merge", "spend", "other"] as const;
export type AlertKind = (typeof ALERT_KINDS)[number];

export interface TypedAlert {
  kind: AlertKind;
  summary: string;
  scope: (typeof ALERT_SCOPES)[number];
  attachments: string[];
  options: string[];
  recommendation: string | null;
  door: (typeof ALERT_DOORS)[number] | null;
}
export interface LegacyAlert {
  kind: null;
  summary: string;
}
export type AlertResult = { ok: true; alert: TypedAlert | LegacyAlert } | { ok: false; errors: string[] };

const NEW_ARGUMENTS = ["kind", "summary", "scope", "attachments", "options", "recommendation", "door"];
const KNOWN_ARGUMENTS = [...NEW_ARGUMENTS, "question"];
const hasControl = (value: string, allowNewline: boolean) => (allowNewline ? /[^\P{Cc}\n]/u : /\p{Cc}/u).test(value);
const length = (value: string) => [...value].length; // characters, not UTF-16 units
const oneOf = (values: readonly string[]) => values.join(", ");

/** A trimmed string of `min`..`max` characters, or an error. */
function boundedString(value: unknown, name: string, min: number, max: number, errors: string[], allowNewline = false): string | undefined {
  if (typeof value !== "string") {
    errors.push(`${name}: must be a string`);
    return undefined;
  }
  const trimmed = value.trim();
  if (length(trimmed) < min || length(trimmed) > max) {
    errors.push(`${name}: must be ${min} to ${max} characters after trimming (got ${length(trimmed)})`);
    return undefined;
  }
  if (hasControl(trimmed, allowNewline)) {
    errors.push(`${name}: must not contain control characters${allowNewline ? " other than newline" : ""}`);
    return undefined;
  }
  return trimmed;
}

/**
 * A list argument as sent: an array, or a string that holds a JSON array (some models send lists that way; Pi's own
 * edit tool accepts the same). Anything else is returned unchanged and fails the list check.
 */
export function listValue(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try {
    const parsed: unknown = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : value;
  } catch {
    return value;
  }
}

const sentAs = (value: unknown) => (typeof value === "string" ? "a string that is not a JSON array" : value === null ? "null" : typeof value);

function stringList(raw: unknown, name: string, min: number, max: number, itemMax: number, errors: string[], checkItem?: (item: string, label: string) => string | undefined): string[] | undefined {
  const value = listValue(raw);
  if (!Array.isArray(value)) {
    errors.push(`${name}: must be an array of strings, like ["first", "second"], or that array as a JSON string (got ${sentAs(value)})`);
    return undefined;
  }
  if (value.length < min || value.length > max) errors.push(`${name}: must have ${min === 0 ? "at most " + max : `${min} to ${max}`} entries (got ${value.length})`);
  const items: string[] = [];
  value.forEach((entry, index) => {
    const label = `${name}[${index}]`;
    const item = boundedString(entry, label, 1, itemMax, errors);
    if (item === undefined) return;
    const problem = checkItem?.(item, label);
    if (problem) errors.push(problem);
    else items.push(item);
  });
  return value.length >= min && value.length <= max && items.length === value.length ? items : undefined;
}

// An attachment is an http(s) URL, a PR reference ("PR owner/repo#N" or "PR #N"), or else a file path.
const URL_RE = /^https?:\/\/\S+$/i;
const PR_RE = /^PR (?:[\w.-]+\/[\w.-]+)?#\d+$/;
const checkAttachment = (item: string, label: string) => (URL_RE.test(item) || PR_RE.test(item) || !item.includes("..") ? undefined : `${label}: a path must not contain ".."`);

/**
 * Check a notify_owner call against the typed contract (README.md, "Arguments") and return the normalized alert
 * or every problem found. The coordinator parses the same arguments from the worker's session log and is tested
 * against the same alert-fixtures.json.
 */
export function validateAlert(args: unknown): AlertResult {
  if (typeof args !== "object" || args === null || Array.isArray(args)) return { ok: false, errors: ["arguments: must be an object"] };
  const input = args as Record<string, unknown>;
  const present = (name: string) => input[name] !== undefined;
  const errors: string[] = [];

  for (const name of Object.keys(input)) if (!KNOWN_ARGUMENTS.includes(name)) errors.push(`${name}: unknown property (allowed: ${oneOf(KNOWN_ARGUMENTS)})`);

  const typed = NEW_ARGUMENTS.some(present);
  if (!typed) {
    if (!present("question")) return { ok: false, errors: [...errors, "kind: required (one of " + oneOf(ALERT_KINDS) + "), with summary"] };
    if (typeof input.question !== "string" || !input.question.trim()) errors.push("question: must be a non-empty string");
    return errors.length ? { ok: false, errors } : { ok: true, alert: { kind: null, summary: (input.question as string).trim() } };
  }

  if (present("question")) errors.push("question: must not be combined with kind or the other typed arguments; use summary");
  const kind = present("kind") ? (typeof input.kind === "string" && (ALERT_KINDS as readonly string[]).includes(input.kind) ? (input.kind as AlertKind) : undefined) : undefined;
  if (!present("kind")) errors.push(`kind: required (one of ${oneOf(ALERT_KINDS)})`);
  else if (!kind) errors.push(`kind: must be one of ${oneOf(ALERT_KINDS)}`);

  const summary = present("summary") ? boundedString(input.summary, "summary", 3, 600, errors, true) : (errors.push("summary: required (3 to 600 characters; it replaces question)"), undefined);

  let scope: TypedAlert["scope"] = "step";
  if (present("scope")) {
    if (typeof input.scope !== "string" || !(ALERT_SCOPES as readonly string[]).includes(input.scope)) errors.push(`scope: must be one of ${oneOf(ALERT_SCOPES)}`);
    else scope = input.scope as TypedAlert["scope"];
    if (kind && kind !== "report" && scope === "workstream") errors.push(`scope: "workstream" is only for kind report (got kind ${kind}); use "step"`);
  }

  const attachments = present("attachments") ? stringList(input.attachments, "attachments", 0, 8, 500, errors, checkAttachment) : [];
  const attachmentList = listValue(input.attachments);
  if (kind === "review" && !(Array.isArray(attachmentList) && attachmentList.length > 0)) errors.push("attachments: required for kind review (at least 1: what the owner should look at)");

  const optionsNeeded = kind === "question" || kind === "decision";
  const optionsAllowed = optionsNeeded || kind === "blocked";
  let options: string[] | undefined = [];
  if (present("options")) {
    if (kind && !optionsAllowed) errors.push(`options: not allowed for kind ${kind}`);
    else options = stringList(input.options, "options", 2, 6, 200, errors);
  } else if (optionsNeeded) errors.push(`options: required for kind ${kind} (2 to 6 choices)`);

  let recommendation: string | null = null;
  if (present("recommendation")) {
    if (kind && !optionsNeeded) errors.push(`recommendation: not allowed for kind ${kind}`);
    else {
      const value = boundedString(input.recommendation, "recommendation", 1, 200, errors);
      if (value !== undefined) {
        recommendation = value;
        if (value !== "none" && options && !options.includes(value)) errors.push('recommendation: must equal one of options exactly, or be "none"');
      }
    }
  } else if (optionsNeeded) errors.push(`recommendation: required for kind ${kind} (one of options exactly, or "none")`);

  let door: TypedAlert["door"] = null;
  if (present("door")) {
    if (kind && kind !== "decision") errors.push(`door: not allowed for kind ${kind}`);
    else if (typeof input.door !== "string" || !(ALERT_DOORS as readonly string[]).includes(input.door)) errors.push(`door: must be one of ${oneOf(ALERT_DOORS)}`);
    else door = input.door as TypedAlert["door"];
  } else if (kind === "decision") errors.push(`door: required for kind decision (one of ${oneOf(ALERT_DOORS)}; none when no one-way door is involved)`);

  if (errors.length || !kind || summary === undefined || !attachments || !options) return { ok: false, errors };
  return { ok: true, alert: { kind, summary, scope, attachments, options, recommendation, door } };
}

export const DESCRIPTION =
  "Ring the owner's doorbell and record a typed alert: a report, a review, a question, a decision or a blocker. " +
  "It returns at once and does not wait: put the same text in your reply and end your turn. " +
  "Choose kind. report: you finished work, ask nothing, and nobody has to look at anything. " +
  "review: something is ready for the owner to LOOK AT (a recording, screenshots, a PR, a document) and you do not wait for an answer; it needs attachments, and it means 'look at this', not 'answer me'. " +
  "question: you need an answer to continue (a two-way matter, no one-way door); it needs options and a recommendation. " +
  `decision: you need the owner to decide something, possibly a one-way door; it needs options, a recommendation and door: ${oneOf(ALERT_DOORS)} (none when no one-way door is involved, other for any other irreversible step). ` +
  "blocked: you cannot continue until the owner does or fixes something. " +
  "summary is one or two plain sentences (3 to 600 characters). " +
  "scope applies to report only: 'step' (the default) for a merged PR, a finished phase or a passed review; use 'workstream' only when the WHOLE assignment this pane exists for is finished. " +
  "attachments: files (absolute, ~/, or relative to your cwd), http(s) URLs, or 'PR owner/repo#N' / 'PR #N'. " +
  "recommendation is one of options, written exactly, or 'none'. " +
  "A malformed call is rejected with the list of problems and rings nothing; fix it and call again. " +
  "Never for progress or for finishing a turn nobody is waiting on, and not for a question you are asking with ask_user_question (that rings by itself). " +
  "A call with only question (a string) still works as an untyped legacy alert; do not use it.";

const malformed = (errors: string[]) => ["Owner not notified: the call is malformed. Fix these and call notify_owner again.", ...errors].join("\n");

/**
 * Pi's prepareArguments hook: it gets the call exactly as the model sent it, before Pi's schema coercion. That
 * coercion would turn a bare string into a one-item list (and a number into a string), so the tool would accept a call
 * that the coordinator, reading the raw call from the session log, rejects. So the raw call is checked here, and a
 * malformed one fails with every problem and rings nothing. A list sent as a JSON string is handed on as a real list.
 */
export function prepareNotifyArguments(args: unknown): unknown {
  const checked = validateAlert(args);
  if (!checked.ok) throw new Error(malformed(checked.errors));
  const prepared = { ...(args as Record<string, unknown>) };
  for (const name of ["attachments", "options"]) if (prepared[name] !== undefined) prepared[name] = listValue(prepared[name]);
  return prepared;
}

const text = (message: string, isError = false) => ({ content: [{ type: "text" as const, text: message }], details: {}, ...(isError ? { isError: true } : {}) });

export interface PiLike {
  registerTool(tool: Record<string, unknown>): void;
  on(event: string, handler: (event: { toolName?: string; reason?: string }, ctx: { hasUI?: boolean; mode?: string }) => void): void;
}

export interface TypeBoxLike {
  Object(properties: unknown, options?: unknown): unknown;
  String(options?: unknown): unknown;
  Array(items: unknown, options?: unknown): unknown;
  Optional(schema: unknown): unknown;
}

/** Register the tool and the listeners. `Type` is TypeBox's, passed in so tests need no Pi. */
export function registerNotifyOwner(pi: PiLike, Type: TypeBoxLike, env: Env = process.env, spawnFn?: Spawner): void {
  if (!eligible(env)) return;
  pi.registerTool({
    name: TOOL_NAME,
    label: "Notify Owner",
    description: DESCRIPTION,
    promptSnippet: "Ring the owner's doorbell with a typed alert (kind report, review, question, decision or blocked) when someone should look at or answer something",
    // Every field is optional and extra properties pass the schema on purpose: Pi checks parameters against it
    // before execute, and validateAlert then reports every problem at once instead of a generic schema error.
    parameters: Type.Object(
      {
        kind: Type.Optional(Type.String({ description: `One of: ${oneOf(ALERT_KINDS)}. See the tool description for which to choose.` })),
        summary: Type.Optional(Type.String({ description: "One or two plain sentences, 3 to 600 characters. It stays in your transcript; the doorbell sends no text." })),
        scope: Type.Optional(Type.String({ description: "report only: step (default) or workstream. workstream only when the WHOLE assignment this pane exists for is finished." })),
        attachments: Type.Optional(Type.Array(Type.String(), { description: "A list of at most 8: file paths (absolute, ~/, or relative to your cwd; no ..), http(s) URLs, or PR references like 'PR owner/repo#N'. Required for review." })),
        options: Type.Optional(Type.Array(Type.String(), { description: "A list of 2 to 6 choices the owner can pick from. Required for question and decision; allowed for blocked." })),
        recommendation: Type.Optional(Type.String({ description: "Exactly one of options, or 'none'. Required for question and decision." })),
        door: Type.Optional(Type.String({ description: `Required for decision: ${oneOf(ALERT_DOORS)}.` })),
        question: Type.Optional(Type.String({ description: "Legacy, untyped: use kind and summary instead. Never together with kind." })),
      },
      { additionalProperties: true },
    ),
    prepareArguments: prepareNotifyArguments,
    async execute(_callId: string, args: unknown) {
      const checked = validateAlert(args);
      if (!checked.ok) return text(malformed(checked.errors), true);
      const result = ring(env, "question", spawnFn);
      if (result === "sent") return text(`Doorbell dispatched. Put the question or answer summary in your reply and end your turn; do not wait. (A failure to deliver is logged, not shown here.)${checked.alert.kind ? ` Recorded as kind=${checked.alert.kind}.` : ""}`);
      return text(`Owner not notified (${result === "no-core" ? "agent-alert is not installed or not executable on this machine" : "this is not a Herdr pane"}). Put the question or answer summary in your reply anyway.`, true);
    },
  });
  pi.on("tool_execution_start", (event, ctx) => {
    if (event.toolName === ASK_TOOL_NAME && ctx.hasUI) ring(env, "question", spawnFn);
  });
  // A clean Pi exit, including SIGTERM and SIGHUP (closing the pane). Reload, new, resume and fork also
  // shut a session down but Pi keeps running, so only "quit" counts. Only the interactive TUI is a pane's agent: a
  // print-mode run (no UI) or an RPC helper (hasUI is true there too) that inherited the pane id is not.
  pi.on("session_shutdown", (event, ctx) => {
    let tui = false;
    try {
      tui = ctx.mode === "tui";
    } catch {
      // a stale ctx: treat as not an interactive pane
    }
    if (event.reason === "quit" && tui) ring(env, "exited", spawnFn);
  });
}
