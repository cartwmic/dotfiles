// Native Anthropic owns the only OAuth credential and its locked refresh.
export function withSharedAnthropicAuth(provider, owner, lazyStream) {
	const hasOwner = async (signal) => (await owner.listCredentials({ signal }))
		.some(info => info.providerId === "anthropic" && info.type === "oauth");
	const resolveOwner = async (signal) => {
		if (!(await hasOwner(signal))) {
			throw new Error("Claude Compat requires Pi's Anthropic OAuth login. Use /login anthropic; paid API keys are not accepted.");
		}
		const resolved = await owner.getAuth("anthropic", { signal });
		if (!resolved?.auth.apiKey?.startsWith("sk-ant-oat")) {
			throw new Error("Pi Anthropic did not resolve an OAuth access token.");
		}
		return { ...resolved, source: "Pi Anthropic OAuth" };
	};
	// Native prepareRequest can reapply caller apiKey overrides after resolution.
	// Enforce the owner again at the actual dispatch boundary for both APIs.
	const wrap = (stream) => (model, context, options) => lazyStream(model, async () => {
		const resolved = await resolveOwner(options?.signal);
		return stream.call(provider, model, context, { ...options, ...resolved.auth });
	});
	const separateLogin = async () => {
		throw new Error("Claude Compat uses Pi's Anthropic OAuth login. Use /login anthropic; no separate Compat credential is needed.");
	};
	const separateCredential = async () => {
		throw new Error("A separate Claude Compat credential cannot be used in shared-auth mode. Remove that entry with /logout claude-compat; keep the Anthropic login.");
	};
	return {
		...provider,
		stream: wrap(provider.stream),
		streamSimple: wrap(provider.streamSimple),
		auth: {
			oauth: {
				...provider.auth.oauth,
				name: "Claude Compat (shared Pi Anthropic OAuth)",
				login: separateLogin,
				refresh: separateCredential,
				toAuth: separateCredential,
			},
			apiKey: {
				name: "Shared Pi Anthropic OAuth (not an API key)",
				login: separateLogin,
				check: async ({ signal }) => await hasOwner(signal)
					? { type: "oauth", source: "Pi Anthropic OAuth" } : undefined,
				resolve: ({ signal }) => resolveOwner(signal),
			},
		},
	};
}
