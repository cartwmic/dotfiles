import { execFile } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";
import { guardProvider } from "./guard.mjs";
import { ownerAuth, withSharedAnthropicAuth } from "./shared-auth.mjs";

// The CLIProxyAPI hub in the homelab cluster, and its client key for this laptop.
export const HUB_ORIGIN = "https://cliproxy.internal.cartwmic.com";
export const HUB_KEY_REF = "op://developer/tb36gtnaocyezjk3dslomp64he/laptop-pi";
const HUB_KEY = /^cpa_[A-Za-z0-9_-]{16,}$/;

// Read only in proxy mode, so direct mode never depends on 1Password.
export function readHubKey(signal) {
	return new Promise((resolve, reject) => execFile(join(homedir(), ".local/user_scripts/op_read_cached.sh"), [HUB_KEY_REF],
		{ encoding: "utf8", timeout: 10000, signal },
		(error, stdout) => error
			? reject(new Error("Claude Compat could not read the hub key from 1Password (laptop-pi)"))
			: resolve(stdout.trim())));
}

// The hub key always comes from 1Password; stored credentials and overrides are ignored.
export function withHubKey(provider, hubKey, lazyStream) {
	const source = "1Password laptop-pi";
	const readKey = async (signal) => {
		signal?.throwIfAborted();
		const key = await hubKey(signal);
		if (typeof key !== "string" || !HUB_KEY.test(key)) {
			throw new Error("The 1Password laptop-pi value is not a cpa_ hub client key");
		}
		return key;
	};
	// Native prepareRequest reapplies a caller apiKey over the resolved one, so the
	// key is set again at the dispatch boundary for both APIs, as in shared-auth.
	const wrap = (stream) => (model, context, options) => lazyStream(model, async () =>
		stream.call(provider, model, context, { ...options, apiKey: await readKey(options?.signal) }));
	return {
		...provider,
		stream: wrap(provider.stream),
		streamSimple: wrap(provider.streamSimple),
		auth: {
			apiKey: {
				name: "Claude Compat hub key (1Password laptop-pi)",
				login: async () => { throw new Error("The Claude Compat hub key comes from 1Password (laptop-pi); no login is needed."); },
				check: async () => ({ type: "api_key", source }),
				resolve: async ({ signal } = {}) => ({ auth: { apiKey: await readKey(signal) }, source }),
			},
		},
	};
}

// Public extension factory delegation, not a patch of the dependency.
// proxy: the fork sends claude-compat to the hub with the 1Password cpa_ key,
// and uses Pi's Anthropic OAuth only when the hub is unreachable.
// direct: the fork's upstream route, on Pi's Anthropic OAuth, as before.
export async function loadCompat(pi, upstream, owner, lazyStream, { mode, origin = HUB_ORIGIN, hubKey = readHubKey } = {}) {
	if (mode !== "proxy" && mode !== "direct") throw new Error(`Unexpected Claude Compat mode: ${mode}`);
	const { resolveOwner } = ownerAuth(owner);
	await upstream({
		...pi,
		registerProvider(provider) {
			if (provider?.id !== "claude-compat") throw new Error("Expected the pinned Claude Compat native provider");
			pi.registerProvider(guardProvider(mode === "proxy"
				? withHubKey(provider, hubKey, lazyStream)
				: withSharedAnthropicAuth(provider, owner, lazyStream)));
		},
	}, mode === "proxy"
		? { mode, origin, directAuth: async (signal) => (await resolveOwner(signal)).auth }
		: { mode });
}
