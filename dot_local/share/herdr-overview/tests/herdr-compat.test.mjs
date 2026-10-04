import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { HERDR_API_CONTRACT, herdrSchemaProblems, manifestEvents } from "../src/herdr-compat.mjs";

// A minimal schema that offers exactly the contract and the manifest's events.
function compatibleSchema() {
  const requestDefs = {};
  const oneOf = Object.entries(HERDR_API_CONTRACT.methods).map(([method, params], index) => {
    requestDefs[`P${index}`] = { properties: Object.fromEntries(params.map((name) => [name, {}])), required: params.slice(0, 1) };
    return { properties: { method: { const: method }, params: { $ref: `#/schemas/request/$defs/P${index}` } } };
  });
  const responseDefs = Object.fromEntries(Object.entries(HERDR_API_CONTRACT.results)
    .map(([name, fields]) => [name, { properties: Object.fromEntries(fields.map((field) => [field, {}])) }]));
  responseDefs.ResponseResult = { oneOf: HERDR_API_CONTRACT.resultTypes.map((type) => ({ properties: { type: { const: type } } })) };
  responseDefs.EventKind = { enum: manifestEvents().map((event) => event.replace(".", "_")) };
  return { protocol: 99, schemas: { request: { oneOf, $defs: requestDefs }, success_response: { $defs: responseDefs } } };
}

test("compatibility depends on the API the plugin uses, not the protocol or version number", () => {
  assert.deepEqual(herdrSchemaProblems(compatibleSchema()), []);
});

test("each kind of break is reported", () => {
  const schema = compatibleSchema();
  const { request, success_response: response } = schema.schemas;
  request.oneOf = request.oneOf.filter((entry) => entry.properties.method.const !== "pane.focus");
  const renameParams = request.$defs[request.oneOf.find((entry) => entry.properties.method.const === "pane.rename").properties.params.$ref.split("/").pop()];
  delete renameParams.properties.label;
  renameParams.required.push("expected_revision");
  delete response.$defs.PaneInfo.properties.terminal_id;
  response.$defs.ResponseResult.oneOf.pop();
  response.$defs.EventKind.enum = response.$defs.EventKind.enum.filter((kind) => kind !== "pane_moved");
  assert.deepEqual(herdrSchemaProblems(schema).sort(), [
    "PaneInfo no longer has terminal_id",
    "event pane.moved is missing",
    "method pane.focus is missing",
    "pane.rename no longer accepts label",
    "pane.rename now requires expected_revision",
    `result type ${HERDR_API_CONTRACT.resultTypes.at(-1)} is missing`,
  ]);
});

test("the installed Herdr meets the contract", { skip: !hasHerdr() && "no installed Herdr" }, () => {
  const output = execFileSync(process.execPath, [new URL("../check-herdr-api.mjs", import.meta.url).pathname,
    execFileSync("mise", ["where", "github:herdrdev/herdr"], { encoding: "utf8" }).trim() + "/herdr"], { encoding: "utf8" });
  assert.match(output, /meets Herdr Overview's needs/);
});

function hasHerdr() {
  try { execFileSync("mise", ["where", "github:herdrdev/herdr"], { stdio: "ignore" }); return true; } catch { return false; }
}
