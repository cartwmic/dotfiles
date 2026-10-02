import { guardProvider } from "./guard.mjs";
import { withSharedAnthropicAuth } from "./shared-auth.mjs";

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
