import { getAgentDir, ModelRuntime, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { lazyStream } from "@earendil-works/pi-ai";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { loadCompat, loadCompatProxy } from "./load.mjs";

export default async function claudeCompatGuard(pi: ExtensionAPI) {
	const agentDir = getAgentDir();
	const owner = await ModelRuntime.create({
		authPath: join(agentDir, "auth.json"),
		modelsPath: null,
		allowModelNetwork: false,
		refreshOnCreate: false,
	});
	const entry = join(agentDir, "git/github.com/vazzma/pi-claude-request-compat/src/extension.js");
	const { default: upstream } = await import(pathToFileURL(entry).href);
	await loadCompat(pi, upstream, owner, lazyStream);
	// Optional: the proxy provider loads only once the pinned fork is installed.
	const proxyEntry = join(agentDir, "git/github.com/cartwmic/pi-claude-request-compat/src/extension.js");
	// A proxy failure must never take down the main claude-compat provider.
	if (existsSync(proxyEntry)) {
		try {
			const { claudeCompatProxy } = await import(pathToFileURL(proxyEntry).href);
			await loadCompatProxy(pi, claudeCompatProxy);
		} catch (error) {
			const reason = error instanceof Error ? error.message : String(error);
			pi.on("session_start", (_event, ctx) => ctx.ui.notify(`Claude Compat Proxy not loaded: ${reason}`, "warning"));
		}
	}
}
