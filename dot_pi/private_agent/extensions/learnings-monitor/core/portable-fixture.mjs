#!/usr/bin/env node
// Standalone non-Pi producer: node portable-fixture.mjs
import { reviewActivity } from "./index.mjs";

const activity = {
	source: { id: "fixture-run-1", label: "standalone fixture" },
	evidence: [
		{
			id: "failed-command",
			summary: "A formatter command failed because its configuration was missing.",
			outcome: "failed",
			provenance: { pointer: "fixture://run-1#failed-command", context: "branch:experiment" },
		},
		{
			id: "one-off-procedure",
			summary: "A one-time log cleanup required several manual edits.",
			outcome: "completed",
			provenance: { pointer: "fixture://run-1#one-off-procedure" },
		},
		{
			id: "manual-step-1",
			summary: "The same report setup steps were performed manually.",
			outcome: "completed",
			provenance: { pointer: "fixture://run-1#manual-step-1" },
		},
		{
			id: "manual-step-2",
			summary: "The report setup steps were performed manually again.",
			outcome: "completed",
			provenance: { pointer: "fixture://run-1#manual-step-2" },
		},
	],
};

const result = reviewActivity({
	activity,
	proposals: [
		{
			type: "friction",
			observation: "The formatter could not run because configuration was missing.",
			evidenceIds: ["failed-command"],
		},
		{
			type: "improvement",
			observation: "A one-time log cleanup required several manual edits.",
			recommendation: "Consider a helper if this cleanup recurs.",
			evidenceIds: ["one-off-procedure"],
		},
		{
			type: "improvement",
			observation: "Report setup is being done manually.",
			recommendation: "Consider a small reusable setup script.",
			evidenceIds: ["manual-step-1", "manual-step-2"],
		},
	],
});

process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
