// Run: node --test dot_pi/private_agent/extensions/anthropic-stall-retry/index.test.ts
import assert from "node:assert/strict";
import { afterEach, beforeEach, mock, test } from "node:test";
import extension, { DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT_MS, OBSERVER, POLL_MS, RETRY_TEXT, contentSilenceMs, readConfig } from "./index.ts";

type Handler = (event: any, ctx?: any) => any;
let snapshot: any = null;

function setup(env: Record<string, string> = {}, provider = "anthropic", handle: unknown = { version: 1, snapshot: () => snapshot }) {
	const saved = { ...process.env };
	Object.assign(process.env, env);
	const handlers: Record<string, Handler[]> = {};
	const sent: string[] = [];
	const notes: string[] = [];
	let aborts = 0;
	let pending = false;
	const pi = {
		on: (name: string, handler: Handler) => (handlers[name] ??= []).push(handler),
		sendUserMessage: (text: string) => sent.push(text),
	};
	extension(pi as any);
	process.env = saved;
	if (handle === null) delete (globalThis as any)[OBSERVER];
	else (globalThis as any)[OBSERVER] = handle;
	const ctx = {
		model: { provider },
		ui: { notify: (text: string) => notes.push(text) },
		abort: () => aborts++,
		hasPendingMessages: () => pending,
	};
	const emit = (name: string, event: any = {}) => handlers[name]?.forEach((h) => h({ type: name, ...event }, ctx));
	emit("session_start");
	return { emit, sent, notes, aborts: () => aborts, setPending: (v: boolean) => (pending = v) };
}

const stalled = (ageMs: number) => ({ phase: "waiting", quiet: { phase: "waiting", absent: "content progress", ageMs } });

beforeEach(() => {
	mock.timers.enable({ apis: ["setInterval"] });
	snapshot = null;
});
afterEach(() => {
	mock.timers.reset();
	delete (globalThis as any)[OBSERVER];
});

test("config defaults, overrides, 0 disables, invalid values fall back and are reported", () => {
	assert.deepEqual(readConfig({}), { timeoutMs: DEFAULT_TIMEOUT_MS, maxRetries: DEFAULT_MAX_RETRIES, invalid: [] });
	assert.deepEqual(readConfig({ PI_ANTHROPIC_STALL_RETRY_MS: "120000", PI_ANTHROPIC_STALL_RETRY_MAX: "0" }), { timeoutMs: 120000, maxRetries: 0, invalid: [] });
	assert.deepEqual(readConfig({ PI_ANTHROPIC_STALL_RETRY_MS: "90s", PI_ANTHROPIC_STALL_RETRY_MAX: "-1" }), {
		timeoutMs: DEFAULT_TIMEOUT_MS, maxRetries: DEFAULT_MAX_RETRIES, invalid: ["PI_ANTHROPIC_STALL_RETRY_MS", "PI_ANTHROPIC_STALL_RETRY_MAX"],
	});
});

test("only content silence counts; phase silence and flowing content do not", () => {
	assert.equal(contentSilenceMs(stalled(5000)), 5000);
	assert.equal(contentSilenceMs({ quiet: { absent: "phase progress", ageMs: 999999 } }), null);
	assert.equal(contentSilenceMs({ quiet: null }), null);
	assert.equal(contentSilenceMs(null), null);
});

test("a stall past the timeout aborts once, notifies, and sends continue after the aborted run settles", () => {
	const s = setup();
	s.emit("turn_start");
	snapshot = stalled(DEFAULT_TIMEOUT_MS - 1);
	mock.timers.tick(POLL_MS);
	assert.equal(s.aborts(), 0);
	snapshot = stalled(DEFAULT_TIMEOUT_MS);
	mock.timers.tick(POLL_MS * 5);
	assert.equal(s.aborts(), 1);
	assert.match(s.notes.at(-1)!, /no content progress for 90s.*retry 1\/2/);
	s.emit("agent_end");
	s.emit("agent_settled", { aborted: true });
	assert.deepEqual(s.sent, [RETRY_TEXT]);
	s.emit("agent_settled", { aborted: true });
	assert.deepEqual(s.sent, [RETRY_TEXT], "a later settle does not resend");
});

test("a reply that finishes before the abort lands is not resent", () => {
	const s = setup();
	s.emit("turn_start");
	snapshot = stalled(DEFAULT_TIMEOUT_MS);
	mock.timers.tick(POLL_MS);
	s.emit("agent_settled", { aborted: false });
	assert.deepEqual(s.sent, []);
	assert.match(s.notes.at(-1)!, /recovered/);
});

test("the owner's own Esc, queued input, other providers and a 0 timeout never trigger a resend", () => {
	const own = setup();
	own.emit("turn_start");
	own.emit("agent_settled", { aborted: true });
	assert.deepEqual(own.sent, []);

	const queued = setup();
	queued.emit("turn_start");
	snapshot = stalled(DEFAULT_TIMEOUT_MS);
	mock.timers.tick(POLL_MS);
	queued.setPending(true);
	queued.emit("agent_settled", { aborted: true });
	assert.deepEqual(queued.sent, []);

	for (const s of [setup({}, "openai-codex"), setup({ PI_ANTHROPIC_STALL_RETRY_MS: "0" })]) {
		s.emit("turn_start");
		snapshot = stalled(10 * DEFAULT_TIMEOUT_MS);
		mock.timers.tick(POLL_MS);
		assert.equal(s.aborts(), 0);
	}
});

test("turn_end stops watching, so a finished request is never aborted", () => {
	const s = setup();
	s.emit("turn_start");
	s.emit("turn_end");
	snapshot = stalled(DEFAULT_TIMEOUT_MS);
	mock.timers.tick(POLL_MS * 3);
	assert.equal(s.aborts(), 0);
});

test("retries stop at the cap until a completed reply or a new prompt resets the count", () => {
	const s = setup();
	const stallOnce = () => {
		s.emit("turn_start");
		snapshot = stalled(DEFAULT_TIMEOUT_MS);
		mock.timers.tick(POLL_MS);
		s.emit("message_end", { message: { role: "assistant", stopReason: "aborted" } });
		s.emit("agent_settled", { aborted: true });
	};
	stallOnce();
	stallOnce();
	assert.equal(s.aborts(), 2);
	stallOnce();
	assert.equal(s.aborts(), 2, "third consecutive stall is not retried");
	assert.match(s.notes.at(-1)!, /Retry limit \(2\) reached/);
	assert.deepEqual(s.sent, [RETRY_TEXT, RETRY_TEXT]);

	s.emit("input", { source: "extension" });
	stallOnce();
	assert.equal(s.aborts(), 2, "our own continue does not reset the count");
	s.emit("message_end", { message: { role: "assistant", stopReason: "stop" } });
	stallOnce();
	assert.equal(s.aborts(), 3, "a completed reply resets it");
	stallOnce();
	stallOnce();
	assert.equal(s.aborts(), 4);
	s.emit("input", { source: "interactive" });
	stallOnce();
	assert.equal(s.aborts(), 5, "a new prompt resets it");
});

test("without the pi-response-visibility handle it warns once and does nothing", () => {
	const s = setup({}, "anthropic", null);
	s.emit("turn_start");
	s.emit("turn_start");
	snapshot = stalled(DEFAULT_TIMEOUT_MS);
	mock.timers.tick(POLL_MS);
	assert.equal(s.aborts(), 0);
	assert.equal(s.notes.filter((n) => /observer handle not found/.test(n)).length, 1);
});
