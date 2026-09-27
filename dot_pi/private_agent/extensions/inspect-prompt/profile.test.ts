import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const sourceDir = fileURLToPath(new URL("../../../../", import.meta.url));
const settingsTemplate = path.join(sourceDir, "dot_pi/private_agent/private_settings.json.tmpl");
const inspectPromptTarget = ".pi/agent/extensions/inspect-prompt";
const desktopProfiles = ["personal", "axon-work-computer"];

test("desktop profiles render fullscreen and include inspect-prompt without applying", () => {
	const tempHome = mkdtempSync(path.join(tmpdir(), "pi-profile-render-"));
	const stubBin = path.join(tempHome, "bin");
	mkdirSync(stubBin);
	const opStub = path.join(stubBin, "op");
	writeFileSync(opStub, '#!/bin/sh\nprintf \'{"models":[]}\\n\'\n');
	chmodSync(opStub, 0o755);
	const env = {
		...process.env,
		PATH: `${stubBin}${path.delimiter}${process.env.PATH ?? ""}`,
	};

	try {
		for (const profile of desktopProfiles) {
			const overrideData = {
				profile,
				...(profile === "axon-work-computer"
					? { privatePiGlmProviderRef: "op://test/provider" }
					: {}),
			};
			const chezmoiArgs = [
				"--source",
				sourceDir,
				"--destination",
				path.join(tempHome, profile),
				"--override-data",
				JSON.stringify(overrideData),
			];
			const renderedSettings = execFileSync(
				"chezmoi",
				[...chezmoiArgs, "execute-template", "--file", settingsTemplate],
				{ encoding: "utf8", env },
			);
			const settings = JSON.parse(renderedSettings) as { tuiMode?: unknown };
			assert.equal(settings.tuiMode, "fullscreen", `${profile} should select fullscreen mode`);

			const managedTargets = execFileSync(
				"chezmoi",
				[...chezmoiArgs, "managed", "--path-style", "relative"],
				{ encoding: "utf8" },
			)
				.trim()
				.split(/\r?\n/);
			assert.ok(
				managedTargets.includes(inspectPromptTarget),
				`${profile} should include ${inspectPromptTarget}`,
			);
		}
	} finally {
		rmSync(tempHome, { recursive: true, force: true });
	}
});
