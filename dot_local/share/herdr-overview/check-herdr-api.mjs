#!/usr/bin/env node
// Usage: node check-herdr-api.mjs <herdr-binary>
// Exits 0 when the binary's bundled API schema offers everything Herdr
// Overview uses, whatever its version number; otherwise lists what is missing.
import { herdrSchemaProblems, readHerdrSchema } from "./src/herdr-compat.mjs";

const binary = process.argv[2];
if (!binary) {
  process.stderr.write("usage: node check-herdr-api.mjs <herdr-binary>\n");
  process.exit(2);
}
let schema;
try { schema = readHerdrSchema(binary); }
catch (error) {
  process.stderr.write(`could not read the API schema from ${binary}: ${error.message}\n`);
  process.exit(1);
}
const problems = herdrSchemaProblems(schema);
if (problems.length) {
  process.stderr.write(`Herdr API (protocol ${schema.protocol}) does not meet Herdr Overview's needs:\n${problems.map((problem) => `  - ${problem}`).join("\n")}\n`);
  process.exit(1);
}
process.stdout.write(`Herdr API (protocol ${schema.protocol}) meets Herdr Overview's needs\n`);
