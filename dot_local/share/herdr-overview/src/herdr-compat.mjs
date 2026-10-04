import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// What the plugin and its Pi adapter actually use from Herdr's socket API.
// A Herdr release is compatible when its bundled schema still offers all of
// it; the version and protocol numbers do not matter. Update this list when
// the code starts using another method, parameter, or field.
export const HERDR_API_CONTRACT = {
  // method -> parameters we send. Any other required parameter is a break.
  methods: {
    "session.snapshot": [],
    "pane.read": ["pane_id", "source", "lines", "format", "strip_ansi"],
    "pane.process_info": ["pane_id"],
    "pane.focus": ["pane_id"],
    "pane.rename": ["pane_id", "label"],
    "tab.rename": ["tab_id", "label"],
    "pane.close": ["pane_id"],
    "plugin.action.invoke": ["action_id", "context"],
    "plugin.pane.open": ["plugin_id", "entrypoint", "placement", "width", "height", "focus"],
    // Pi adapter (dot_pi/private_agent/extensions/herdr-overview).
    "pane.current": ["caller_pane_id"],
    "pane.report_metadata": ["pane_id", "source", "agent", "applies_to_source", "seq", "state_labels", "clear_state_labels"],
  },
  // success_response definition -> fields we read.
  results: {
    SessionSnapshot: ["workspaces", "tabs", "panes", "agents", "focused_workspace_id", "focused_tab_id", "focused_pane_id"],
    WorkspaceInfo: ["workspace_id", "number", "label", "focused", "active_tab_id", "agent_status"],
    TabInfo: ["tab_id", "workspace_id", "number", "label", "focused", "agent_status"],
    PaneInfo: ["pane_id", "terminal_id", "workspace_id", "tab_id", "label", "focused", "agent", "agent_session",
      "agent_status", "display_agent", "title", "terminal_title", "terminal_title_stripped", "cwd", "foreground_cwd", "state_labels"],
    AgentInfo: ["pane_id", "agent", "agent_session", "agent_status", "display_agent", "name", "state_labels", "foreground_cwd"],
  },
  // ResponseResult type tags we read.
  resultTypes: ["session_snapshot", "pane_read", "pane_process_info", "pane_current", "plugin_action_invoked", "plugin_pane_opened"],
};

const MANIFEST = fileURLToPath(new URL("../herdr-plugin.toml", import.meta.url));

export function manifestEvents(manifestText = readFileSync(MANIFEST, "utf8")) {
  return [...manifestText.matchAll(/^on = "([^"]+)"/gm)].map((match) => match[1]);
}

const refName = (ref) => String(ref ?? "").split("/").pop();

// Returns a list of unmet dependencies; empty means compatible.
export function herdrSchemaProblems(schema, { contract = HERDR_API_CONTRACT, events = manifestEvents() } = {}) {
  const problems = [];
  const schemas = schema?.schemas;
  if (!schemas?.request?.oneOf || !schemas?.success_response?.$defs) return ["schema has no request/response definitions"];
  const requestDefs = schemas.request.$defs ?? {};
  const methods = new Map(schemas.request.oneOf.map((entry) => [entry?.properties?.method?.const, entry]));
  for (const [method, sent] of Object.entries(contract.methods)) {
    const entry = methods.get(method);
    if (!entry) { problems.push(`method ${method} is missing`); continue; }
    const params = requestDefs[refName(entry.properties.params?.$ref)] ?? {};
    const known = Object.keys(params.properties ?? {});
    for (const name of sent) if (!known.includes(name)) problems.push(`${method} no longer accepts ${name}`);
    for (const name of params.required ?? []) if (!sent.includes(name)) problems.push(`${method} now requires ${name}`);
  }
  const responseDefs = schemas.success_response.$defs;
  for (const [definition, fields] of Object.entries(contract.results)) {
    const properties = responseDefs[definition]?.properties;
    if (!properties) { problems.push(`result ${definition} is missing`); continue; }
    for (const field of fields) if (!Object.hasOwn(properties, field)) problems.push(`${definition} no longer has ${field}`);
  }
  const resultTypes = new Set((responseDefs.ResponseResult?.oneOf ?? []).map((entry) => entry?.properties?.type?.const));
  for (const type of contract.resultTypes) if (!resultTypes.has(type)) problems.push(`result type ${type} is missing`);
  const eventKinds = new Set(responseDefs.EventKind?.enum ?? []);
  for (const event of events) if (!eventKinds.has(event.replace(".", "_"))) problems.push(`event ${event} is missing`);
  return problems;
}

// Reads the schema bundled in a Herdr binary. Offline: the nonexistent socket
// keeps it from contacting or starting a server.
export function readHerdrSchema(herdrBinary) {
  const socket = path.join(path.dirname(fileURLToPath(import.meta.url)), ".herdr-compat-offline.sock");
  return JSON.parse(execFileSync(herdrBinary, ["api", "schema", "--json"], {
    encoding: "utf8", env: { ...process.env, HERDR_SOCKET_PATH: socket }, maxBuffer: 16 * 1024 * 1024,
  }));
}
