// Fixed, validated request edits. Never mutate Pi's transcript or retry variants.
const DOCS = /(^|\n)(<docs>\nPi documentation \(read only when the user asks about (?:pi|Pi) itself,[\s\S]*?\n<\/docs>)(?=\n|$)/g;

export function rewriteDocs(text) {
	if (typeof text !== "string") return text;
	const matches = [...text.matchAll(DOCS)];
	if (matches.length !== 1) return text;
	const match = matches[0];
	const before = match[2];
	const after = before
		.replace("about pi itself, its SDK", "about Pi itself, its SDK")
		.replace(", pi packages (docs/packages.md),", ", Pi packages (docs/packages.md),");
	if (before === after) return text;
	const start = match.index + match[1].length;
	return text.slice(0, start) + after + text.slice(start + before.length);
}

export function rewriteContext(model, context) {
	if (model.provider !== "claude-compat" || model.api !== "claude-compat-messages") return context;
	let changed = false;
	const messages = context.messages.map((message) => {
		if (message.role !== "system") return message;
		const docs = message.sections?.docs;
		const rewrittenDocs = rewriteDocs(docs);
		// Forced system prompts and older checkpoints can carry flattened sections.
		const content = typeof message.content === "string"
			? rewriteDocs(message.content)
			: message.content.map((block) => {
				const text = rewriteDocs(block.text);
				return text === block.text ? block : { ...block, text };
			});
		const contentChanged = typeof content === "string"
			? content !== message.content
			: content.some((block, index) => block !== message.content[index]);
		if (rewrittenDocs === docs && !contentChanged) return message;
		changed = true;
		return {
			...message,
			content,
			...(rewrittenDocs !== docs ? { sections: { ...message.sections, docs: rewrittenDocs } } : {}),
		};
	});
	return changed ? { ...context, messages } : context;
}

export function guardProvider(provider) {
	const wrap = (stream) => (model, context, options) =>
		stream.call(provider, model, rewriteContext(model, context), options);
	return { ...provider, stream: wrap(provider.stream), streamSimple: wrap(provider.streamSimple) };
}
