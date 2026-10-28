import { guardProvider } from "./guard.mjs";
import { withSharedAnthropicAuth } from "./shared-auth.mjs";

// The CLIProxyAPI hub in the homelab cluster. Must match the claude-compat-proxy
// baseUrl in private_models.json.tmpl.
export const PROXY_ORIGIN = "https://cliproxy.internal.cartwmic.com";

// Public extension factory delegation, not a patch of the dependency.
export async function loadCompat(pi, upstream, owner, lazyStream) {
	await upstream({
		...pi,
		registerProvider(provider) {
			if (provider?.id !== "claude-compat") throw new Error("Expected the pinned Claude Compat native provider");
			pi.registerProvider(guardProvider(withSharedAnthropicAuth(provider, owner, lazyStream)));
		},
	});
}

// Proxy mode from the pinned cartwmic fork: a separate provider whose only
// credential is a CLIProxyAPI client key. It never touches the Anthropic login.
export async function loadCompatProxy(pi, claudeCompatProxy, origin = PROXY_ORIGIN) {
	await claudeCompatProxy({
		...pi,
		registerProvider(provider) {
			if (provider?.id !== "claude-compat-proxy") throw new Error("Expected the pinned Claude Compat Proxy provider");
			pi.registerProvider(guardProvider(provider));
		},
	}, { origin });
}
