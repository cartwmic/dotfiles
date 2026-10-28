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
	const entry = join(agentDir, "git/github.com/cartwmic/pi-claude-request-compat/src/extension.js");
	const { default: upstream, compatMode } = await import(pathToFileURL(entry).href);
	// PI_CLAUDE_COMPAT_MODE: unset or proxy -> hub; direct -> Anthropic. Anything
	// else throws here, so claude-compat does not load at all.
	await loadCompat(pi, upstream, owner, lazyStream, { mode: compatMode() });
}
