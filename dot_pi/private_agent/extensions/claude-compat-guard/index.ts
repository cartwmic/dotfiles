import { getAgentDir, ModelRuntime, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { lazyStream } from "@earendil-works/pi-ai";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { loadCompat } from "./load.mjs";

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
}
