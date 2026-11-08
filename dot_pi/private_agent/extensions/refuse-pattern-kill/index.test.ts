// Run: node --test dot_pi/private_agent/extensions/refuse-pattern-kill/index.test.ts
import assert from "node:assert/strict";
import { chmodSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import extension, { guard, refusal } from "./index.ts";

const REAL = join(dirname(fileURLToPath(import.meta.url)), "../../../../dot_local/share/agent-harness/hooks/refuse_pattern_kill.py");

test("a pattern kill is refused with the exact-PID reason; ordinary commands are not", () => {
	const reason = refusal("pkill -f something-harmless", REAL);
	assert.ok(reason?.includes("pkill is refused in agent sessions"), String(reason));
	assert.ok(reason?.includes("kill <pid>") && reason.includes("kgate cancel <id>"));
	assert.ok(refusal("echo a && killall node", REAL)?.includes("killall is refused"));
	assert.ok(refusal("sh -c 'pkill x'", REAL));
	for (const ok of ["kill 123", "kgate cancel abc", "git commit -m 'no pkill'", "grep -rn pkill ."]) assert.equal(refusal(ok, REAL), undefined, ok);
});

test("fails open: a missing script, and a script that exits 2 for some other reason, allow the command", () => {
	assert.equal(refusal("pkill x", join(tmpdir(), "refuse-pattern-kill-missing.py")), undefined);
	const dir = mkdtempSync(join(tmpdir(), "rpk-"));
	const broken = join(dir, "broken.py");
	writeFileSync(broken, "import sys\nsys.stderr.write('some other failure')\nsys.exit(2)\n");
	chmodSync(broken, 0o644);
	assert.equal(refusal("pkill x", broken), undefined);
});

test("the tool_call handler blocks only a refused bash call", () => {
	const handler = guard(REAL);
	assert.equal(handler({ toolName: "read", input: { command: "pkill x" } }), undefined);
	assert.equal(handler({ toolName: "bash", input: {} }), undefined);
	assert.equal(handler({ toolName: "bash", input: { command: "kill 123" } }), undefined);
	const blocked = handler({ toolName: "bash", input: { command: "pkill -f x" } });
	assert.equal(blocked?.block, true);
	assert.ok(blocked?.reason.includes("pkill is refused"));
});

test("the extension registers one tool_call handler", () => {
	const seen: string[] = [];
	extension({ on: (name: string) => seen.push(name) } as any);
	assert.deepEqual(seen, ["tool_call"]);
});
