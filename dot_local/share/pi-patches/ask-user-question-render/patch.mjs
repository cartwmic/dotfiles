#!/usr/bin/env node
// chezmoi-pi-patch:ask-user-question-render
//
// rpiv-ask-user-question 2.15.0 renders ask_user_question calls from session
// history without its own prepareArguments decoding. Some models sent
// `questions` as a JSON string; a session holding such a call kills Pi on
// resume (`args.questions.map is not a function`). The row is laid out lazily,
// so Pi's renderer try/catch does not catch it. This patch decodes the args the
// same way the tool does before rendering and drops anything still unusable.
//
// Targets the agent-npm install (~/.pi/agent/npm). Override the package root
// with PI_ASK_USER_QUESTION_PACKAGE. Anchor-gated: on drift it fails and writes
// nothing. Absent package: nothing to patch. Flags: --check, --rollback.

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const NAME = "ask-user-question-render";
const MARKER = `chezmoi-pi-patch:${NAME} v1`;
const log = (msg) => console.log(`[pi-patch:${NAME}] ${msg}`);
const fail = (msg) => { console.error(`[pi-patch:${NAME}] ERROR: ${msg}`); process.exit(1); };
const check = process.argv.includes("--check");
const rollback = process.argv.includes("--rollback");

const pkg = process.env.PI_ASK_USER_QUESTION_PACKAGE
	|| join(homedir(), ".pi", "agent", "npm", "node_modules", "@juicesharp", "rpiv-ask-user-question");
const file = join(pkg, "view", "transcript.ts");
if (!existsSync(file)) { log(`not installed at ${pkg}; nothing to patch`); process.exit(0); }

const EDITS = [
	{
		old: 'import { stripFenceMarkers } from "./components/preview/preview-box-renderer.ts";\n',
		new: 'import { stripFenceMarkers } from "./components/preview/preview-box-renderer.ts";\n'
			+ `import { prepareQuestionArguments } from "../tool/normalize-params.ts"; // ${MARKER}\n`,
	},
	{
		old: "/** `Ask Format · Migration`: the headers name the questions. */\nexport function renderAskCall(args: QuestionParams | undefined, theme: Theme): Component {\n",
		new: `/** ${MARKER}: history args, decoded like the tool's prepareArguments; unusable questions dropped. */\n`
			+ "function renderableArgs(args: QuestionParams | undefined): QuestionParams | undefined {\n"
			+ "\tconst prepared = prepareQuestionArguments(args) as QuestionParams | undefined;\n"
			+ "\tif (!prepared || !Array.isArray(prepared.questions)) return undefined;\n"
			+ "\tconst questions = prepared.questions\n"
			+ "\t\t.filter((q) => typeof q === \"object\" && q !== null)\n"
			+ "\t\t.map((q) => ({ ...q, header: typeof q.header === \"string\" ? q.header : \"\" }));\n"
			+ "\treturn { ...prepared, questions };\n"
			+ "}\n\n"
			+ "/** `Ask Format · Migration`: the headers name the questions. */\n"
			+ "export function renderAskCall(args: QuestionParams | undefined, theme: Theme): Component {\n"
			+ `\targs = renderableArgs(args); // ${MARKER}\n`,
	},
	{
		old: "): Component {\n\tconst details = isQuestionnaireResult(result.details) ? result.details : undefined;\n",
		new: `): Component {\n\targs = renderableArgs(args); // ${MARKER}\n`
			+ "\tconst details = isQuestionnaireResult(result.details) ? result.details : undefined;\n",
	},
];

const count = (text, s) => text.split(s).length - 1;
const text = readFileSync(file, "utf8");
const patched = text.includes(MARKER);

if (check) {
	if (!patched) fail(`not patched: ${file}`);
	for (const e of EDITS) if (count(text, e.new) !== 1) fail(`patch block drift in ${file}`);
	log(`verified ${EDITS.length} blocks in ${file}`);
	process.exit(0);
}

const [from, to] = rollback ? ["new", "old"] : ["old", "new"];
if (patched !== rollback) { log(rollback ? "already unpatched" : "already patched"); process.exit(0); }
let out = text;
for (const e of EDITS) {
	if (count(out, e[from]) !== 1) fail(`unsupported or ambiguous anchor in ${file}: ${JSON.stringify(e[from].slice(0, 80))}`);
	out = out.replace(e[from], () => e[to]);
}
if (!rollback && count(out, MARKER) !== EDITS.length + 1) fail("marker count mismatch; nothing written");
writeFileSync(file, out);
log(`${rollback ? "unpatched" : "patched"} ${file}`);
