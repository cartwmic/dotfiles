// Shared locator for the Pi package tree that the `pi` command loads.
// Not a patch: the apply loop only runs */patch.mjs.
//
// Order: PI_ROOT override, Pi's managed install
// (~/.pi/agent/install/releases/<current-version>/), then the npm global root.
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const SCOPE = "@earendil-works";

function managedRoot() {
	const agentDir = process.env.PI_CODING_AGENT_DIR || join(homedir(), ".pi", "agent");
	try {
		const version = readFileSync(join(agentDir, "install", "current-version"), "utf8").trim();
		if (!version || version.includes("/") || version.startsWith(".")) return undefined;
		return join(agentDir, "install", "releases", version, "node_modules", SCOPE, "pi-coding-agent");
	} catch {
		return undefined;
	}
}

function npmGlobalRoot() {
	try {
		return join(execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim(), SCOPE, "pi-coding-agent");
	} catch {
		return undefined;
	}
}

// Absolute pi-coding-agent package dir, or undefined when Pi is not installed.
export function piCodingAgentRoot() {
	if (process.env.PI_ROOT) return process.env.PI_ROOT;
	for (const root of [managedRoot(), npmGlobalRoot()]) {
		if (root && existsSync(join(root, "package.json"))) return root;
	}
	return undefined;
}

// pi-ai package dir next to a pi-coding-agent root: nested (npm global) or
// hoisted sibling (managed install).
export function piAiRoot(pcaRoot = piCodingAgentRoot()) {
	if (!pcaRoot) return undefined;
	for (const root of [join(pcaRoot, "node_modules", SCOPE, "pi-ai"), join(pcaRoot, "..", "pi-ai")]) {
		if (existsSync(join(root, "package.json"))) return root;
	}
	return undefined;
}
