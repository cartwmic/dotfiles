import { guardProvider } from "./guard.mjs";
import { ownerAuth, withSharedAnthropicAuth } from "./shared-auth.mjs";

// The CLIProxyAPI hub in the homelab cluster.
export const HUB_ORIGIN = "https://cliproxy.internal.cartwmic.com";

// Public extension factory delegation, not a patch of the dependency.
// proxy: the fork sends claude-compat to the hub with the cpa_ key from
// models.json, and uses Pi's Anthropic OAuth only when the hub is unreachable.
// direct: the fork's upstream route, on Pi's Anthropic OAuth, as before.
export async function loadCompat(pi, upstream, owner, lazyStream, { mode, origin = HUB_ORIGIN } = {}) {
	if (mode !== "proxy" && mode !== "direct") throw new Error(`Unexpected Claude Compat mode: ${mode}`);
	const { resolveOwner } = ownerAuth(owner);
	await upstream({
		...pi,
		registerProvider(provider) {
			if (provider?.id !== "claude-compat") throw new Error("Expected the pinned Claude Compat native provider");
			pi.registerProvider(guardProvider(mode === "proxy" ? provider : withSharedAnthropicAuth(provider, owner, lazyStream)));
		},
	}, mode === "proxy"
		? { mode, origin, directAuth: async (signal) => (await resolveOwner(signal)).auth }
		: { mode });
}
